from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.config import Settings
from app.auth import make_token, password_hash
from app.models import AudioFile, Consultation, MISExport, User, now_utc
from app.service import cleanup_expired_audio
from app.schemas import ConsultationData, ExtractionResult, TemplateFieldValue, Transcript, TranscriptSegment
from datetime import timedelta


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        app_mode="demo",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-only-secret-with-enough-length-123456",
        audio_storage_dir=tmp_path / "audio",
    )
    with TestClient(create_app(settings)) as app_client:
        yield app_client


def login(client: TestClient, username="doctor", password="demo-doctor") -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def consultation(client: TestClient, headers: dict) -> dict:
    response = client.post("/api/v1/consultations", json={"external_patient_id": "SYN-1024"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_authentication_required_and_bad_password_rejected(client):
    assert client.get("/api/v1/consultations").status_code == 401
    assert client.post("/api/v1/protocols/search", json={"query": "ринит"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "doctor", "password": "wrong"}).status_code == 401
    headers = login(client)
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "doctor"


def test_new_demo_database_records_alembic_revision(client):
    with client.app.state.session_factory() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0004_export_artifacts"


def test_template_catalog_requires_auth_and_selection_persists(client):
    assert client.get("/api/v1/templates").status_code == 401
    headers = login(client)
    templates = client.get("/api/v1/templates", headers=headers)
    assert templates.status_code == 200
    assert {template["id"] for template in templates.json()} == {
        "therapist", "therapist_initial", "cardiologist", "pediatrician", "proctologist", "surgeon"
    }
    default = consultation(client, headers)
    assert default["template_id"] == "therapist"
    selected = client.post("/api/v1/consultations", headers=headers,
                           json={"external_patient_id": "SYN-1025", "template_id": "cardiologist"})
    assert selected.status_code == 201, selected.text
    assert selected.json()["template_id"] == "cardiologist"
    assert client.get(f"/api/v1/consultations/{selected.json()['id']}", headers=headers).json()["template_id"] == "cardiologist"
    assert client.post("/api/v1/consultations", headers=headers,
                       json={"external_patient_id": "SYN-1026", "template_id": "../../tmp"}).status_code == 422


def test_diagnosis_catalog_search_requires_auth_and_bounds_results(client):
    assert client.get("/api/v1/diagnoses", params={"q": "A00"}).status_code == 401
    headers = login(client)
    response = client.get("/api/v1/diagnoses", headers=headers, params={"q": "A00", "limit": 3})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] >= 1
    assert len(payload["items"]) <= 3
    assert any(item["code"] == "A00" and item["name_ru"] == "Холера" for item in payload["items"])
    assert client.get("/api/v1/diagnoses", headers=headers, params={"q": "x" * 101}).status_code == 422
    assert client.get("/api/v1/diagnoses", headers=headers, params={"q": "A00", "limit": 51}).status_code == 422
    assert client.get("/api/v1/diagnoses", headers=headers, params={"q": "A00", "limit": 0}).status_code == 422


def test_doctor_selected_diagnosis_code_is_validated_audited_and_approved(client):
    headers = login(client)
    item = consultation(client, headers)
    prefix = f"/api/v1/consultations/{item['id']}"
    assert client.post(prefix + "/demo", headers=headers).status_code == 200
    draft = client.post(prefix + "/generate", headers=headers).json()
    assert draft["data"]["diagnosis_code"] is None
    invalid = {**draft["data"], "diagnosis_code": "NOT-A-CODE"}
    assert client.patch(prefix + "/document", headers=headers,
                        json={"version": draft["version"], "data": invalid}).status_code == 422
    selected = {**draft["data"], "diagnosis_code": "A00"}
    edited = client.patch(prefix + "/document", headers=headers,
                          json={"version": draft["version"], "data": selected})
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["diagnosis_code"] == "A00"
    assert client.post(prefix + "/approve", headers=headers,
                       json={"version": edited.json()["version"]}).status_code == 200
    approved = client.get(prefix + "/document", headers=headers).json()
    assert approved["doctor_approved_data"]["diagnosis_code"] == "A00"
    audit = client.get(prefix + "/audit", headers=headers).json()
    assert any(row["field"] == "diagnosis_code" and row["doctor_value"] == "A00" for row in audit)

    class CapturingMIS:
        received_code = None

        async def send_consultation(self, consultation, *, consultation_id, patient_id):
            from app.schemas import MISResult

            self.received_code = consultation.diagnosis_code
            return MISResult(success=True, document_id="MIS-ICD-TEST", provider="mock")

    mis = CapturingMIS()
    client.app.state.mis = mis
    assert client.post(prefix + "/send-to-mis", headers=headers).status_code == 200
    assert mis.received_code == "A00"


def test_template_fields_allow_selected_keys_and_reject_unknown_or_duplicates(client):
    headers = login(client)
    catalog = client.get("/api/v1/templates", headers=headers).json()
    selected = next(item for item in catalog if item["id"] == "cardiologist")
    specialty_key = next(field["key"] for field in selected["fields"] if not field.get("clinical_field"))
    created = client.post("/api/v1/consultations", headers=headers,
                          json={"external_patient_id": "SYN-1027", "template_id": "cardiologist"}).json()
    prefix = f"/api/v1/consultations/{created['id']}"
    assert client.post(prefix + "/demo", headers=headers).status_code == 200
    draft = client.post(prefix + "/generate", headers=headers)
    assert draft.status_code == 200, draft.text
    doc = draft.json()
    allowed = {**doc["data"], "template_fields": [{"key": specialty_key, "value": "Только записано врачом"}]}
    assert client.patch(prefix + "/document", headers=headers,
                        json={"version": doc["version"], "data": allowed}).status_code == 200
    duplicate = {**allowed, "template_fields": [{"key": specialty_key, "value": "A"}, {"key": specialty_key, "value": "B"}]}
    assert client.patch(prefix + "/document", headers=headers,
                        json={"version": doc["version"] + 1, "data": duplicate}).status_code == 422
    unknown = {**allowed, "template_fields": [{"key": "not_a_template_field", "value": "A"}]}
    assert client.patch(prefix + "/document", headers=headers,
                        json={"version": doc["version"] + 1, "data": unknown}).status_code == 422


def test_generation_passes_selected_catalog_and_rejects_out_of_template_output(client):
    headers = login(client)
    created = client.post("/api/v1/consultations", headers=headers,
                          json={"external_patient_id": "SYN-1028", "template_id": "cardiologist"}).json()
    prefix = f"/api/v1/consultations/{created['id']}"
    assert client.post(prefix + "/demo", headers=headers).status_code == 200

    class InvalidFieldLLM:
        fields = None

        async def extract_consultation(self, transcript, *, template_fields=None, on_stage=None):
            self.fields = template_fields
            return ExtractionResult(data=ConsultationData(template_fields=[TemplateFieldValue(key="outside_form", value="X")]))

    llm = InvalidFieldLLM()
    client.app.state.llm = llm
    result = client.post(prefix + "/generate", headers=headers)
    assert result.status_code == 502
    assert "outside_form" not in result.text
    assert client.get(prefix + "/document", headers=headers).status_code == 404
    assert client.get(prefix, headers=headers).json()["status"] == "FAILED"
    assert llm.fields and any(field.get("clinical_field") for field in llm.fields)
    assert any(not field.get("clinical_field") for field in llm.fields)


def test_docx_requires_approval_and_uses_frozen_data(client):
    headers = login(client)
    created = consultation(client, headers)
    prefix = f"/api/v1/consultations/{created['id']}"
    assert client.get(prefix + "/document.docx", headers=headers).status_code == 409
    assert client.post(prefix + "/demo", headers=headers).status_code == 200
    draft = client.post(prefix + "/generate", headers=headers).json()
    assert client.get(prefix + "/document.docx", headers=headers).status_code == 409
    reviewed = client.patch(prefix + "/document", headers=headers,
                            json={"version": draft["version"], "data": draft["data"]}).json()
    assert client.get(prefix + "/document.docx", headers=headers).status_code == 409
    assert client.post(prefix + "/approve", headers=headers, json={"version": reviewed["version"]}).status_code == 200
    exported = client.get(prefix + "/document.docx", headers=headers)
    assert exported.status_code == 200, exported.text if exported.status_code != 200 else ""
    assert exported.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert exported.headers["content-disposition"].startswith("attachment; filename=")
    assert exported.content.startswith(b"PK\x03\x04")
    assert client.post(prefix + "/send-to-mis", headers=headers).status_code == 200
    assert client.get(prefix + "/document.docx", headers=headers).status_code == 200


def test_docx_uses_approval_actor_snapshot_after_profile_rename(client, monkeypatch):
    import app.forms as forms

    headers = login(client)
    created = consultation(client, headers)
    prefix = f"/api/v1/consultations/{created['id']}"
    assert client.post(prefix + "/demo", headers=headers).status_code == 200
    draft = client.post(prefix + "/generate", headers=headers).json()
    reviewed = client.patch(prefix + "/document", headers=headers,
                            json={"version": draft["version"], "data": draft["data"]}).json()
    assert client.post(prefix + "/approve", headers=headers, json={"version": reviewed["version"]}).status_code == 200
    with client.app.state.session_factory() as session:
        doctor = session.query(User).filter_by(username="doctor").one()
        doctor.display_name = "Переименован"
        session.commit()
    captured = {}

    def render(_template_id, _data, *, patient_id, consultation_id, doctor_name, approved_at):
        captured["doctor_name"] = doctor_name
        return b"PK\x03\x04"

    monkeypatch.setattr(forms, "render_docx", render)
    assert client.get(prefix + "/document.docx", headers=headers).status_code == 200
    assert captured["doctor_name"] == "Демо врач"


def test_consultation_owner_cannot_be_bypassed(client):
    headers = login(client)
    item = consultation(client, headers)
    assert client.get(f"/api/v1/consultations/{item['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/consultations/{item['id']}", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/v1/consultations", headers=headers).json()[0]["id"] == item["id"]
    with client.app.state.session_factory() as session:
        other = User(username="other", password_hash=password_hash.hash("other-pass"), role="doctor", display_name="Другой врач")
        session.add(other)
        session.commit()
        other_token = make_token(other, client.app.state.settings.jwt_secret)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get(f"/api/v1/consultations/{item['id']}", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/consultations/{item['id']}/demo", headers=other_headers).status_code == 404
    assert client.get("/api/v1/consultations", headers=other_headers).json() == []


def test_unknown_role_cannot_use_doctor_routes(client):
    with client.app.state.session_factory() as session:
        user = User(username="readonly", password_hash=password_hash.hash("read-only"), role="observer", display_name="Наблюдатель")
        session.add(user)
        session.commit()
        token = make_token(user, client.app.state.settings.jwt_secret)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/consultations", headers=headers).status_code == 403


def test_switching_demo_database_to_live_revokes_demo_password(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'mode.db'}"
    audio_dir = tmp_path / "audio"
    with TestClient(create_app(Settings(app_mode="demo", database_url=db_url, audio_storage_dir=audio_dir))) as demo_client:
        assert demo_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}).status_code == 200
    live_settings = Settings(app_mode="live", database_url=db_url, audio_storage_dir=audio_dir,
                             jwt_secret="live-secret-longer-than-thirty-two-characters",
                             doctor_password_hash=password_hash.hash("live-password"), openai_api_key="test-key")
    with TestClient(create_app(live_settings)) as live_client:
        assert live_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}).status_code == 401
        assert live_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "live-password"}).status_code == 200


def test_demo_bootstrap_preserves_a_seeded_local_password_on_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'seeded-demo.db'}"
    audio_dir = tmp_path / "audio"
    settings = Settings(app_mode="demo", database_url=db_url, audio_storage_dir=audio_dir)
    with TestClient(create_app(settings)) as first_client:
        with first_client.app.state.session_factory() as session:
            doctor = session.query(User).filter_by(username="doctor").one()
            doctor.password_hash = password_hash.hash("doctor")
            doctor.display_name = "Абай Кандышев"
            session.commit()
    with TestClient(create_app(settings)) as restarted_client:
        login = restarted_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "doctor"})
        assert login.status_code == 200
        assert login.json()["user"]["display_name"] == "Абай Кандышев"
        assert restarted_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}).status_code == 401


def test_switching_live_username_disables_stale_demo_account(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'mode-change.db'}"
    with TestClient(create_app(Settings(app_mode="demo", database_url=db_url, audio_storage_dir=tmp_path / "audio"))) as demo_client:
        assert demo_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}).status_code == 200
    live_settings = Settings(app_mode="live", database_url=db_url, audio_storage_dir=tmp_path / "audio",
                             jwt_secret="live-secret-longer-than-thirty-two-characters",
                             doctor_username="clinician", doctor_password_hash=password_hash.hash("live-password"),
                             openai_api_key="test-key")
    with TestClient(create_app(live_settings)) as live_client:
        assert live_client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}).status_code == 401
        assert live_client.post("/api/v1/auth/login", json={"username": "clinician", "password": "live-password"}).status_code == 200


def test_switching_live_username_disables_custom_named_demo_account(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'custom-demo.db'}"
    with TestClient(create_app(Settings(app_mode="demo", database_url=db_url,
                                        doctor_username="demo-clinic", audio_storage_dir=tmp_path / "audio"))) as demo_client:
        assert demo_client.post("/api/v1/auth/login", json={"username": "demo-clinic", "password": "demo-doctor"}).status_code == 200
    live_settings = Settings(app_mode="live", database_url=db_url, audio_storage_dir=tmp_path / "audio",
                             jwt_secret="live-secret-longer-than-thirty-two-characters",
                             doctor_username="clinician", doctor_password_hash=password_hash.hash("live-password"),
                             openai_api_key="test-key")
    with TestClient(create_app(live_settings)) as live_client:
        assert live_client.post("/api/v1/auth/login", json={"username": "demo-clinic", "password": "demo-doctor"}).status_code == 401
        assert live_client.post("/api/v1/auth/login", json={"username": "clinician", "password": "live-password"}).status_code == 200


def test_full_demo_review_approval_export_and_audit(client):
    headers = login(client)
    item = consultation(client, headers)
    consultation_id = item["id"]
    prefix = f"/api/v1/consultations/{consultation_id}"
    assert client.post(prefix + "/approve", json={"version": 1}, headers=headers).status_code == 409
    transcript = client.post(prefix + "/demo", headers=headers)
    assert transcript.status_code == 200, transcript.text
    assert transcript.json()["masked_text"]
    generated = client.post(prefix + "/generate", headers=headers)
    assert generated.status_code == 200, generated.text
    document = generated.json()
    assert document["ai_generated_data"] == document["data"]
    assert client.post(prefix + "/send-to-mis", headers=headers).status_code == 409
    changed = {**document["data"], "diagnosis": "Подтверждено врачом"}
    edited = client.patch(prefix + "/document", json={"data": changed, "version": document["version"]}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["diagnosis"] == "Подтверждено врачом"
    assert edited.json()["ai_generated_data"] == document["ai_generated_data"]
    assert client.patch(prefix + "/document", json={"data": changed, "version": document["version"]}, headers=headers).status_code == 409
    approved = client.post(prefix + "/approve", json={"version": edited.json()["version"]}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert client.patch(prefix + "/document", json={"data": changed, "version": edited.json()["version"]}, headers=headers).status_code == 409
    class CountingMIS:
        calls = 0

        async def send_consultation(self, consultation, *, consultation_id, patient_id):
            from app.schemas import MISResult
            self.calls += 1
            return MISResult(success=True, document_id="MIS-TEST", provider="mock")

    mis = CountingMIS()
    client.app.state.mis = mis
    first = client.post(prefix + "/send-to-mis", headers=headers)
    second = client.post(prefix + "/send-to-mis", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["success"] is True
    assert mis.calls == 1
    audit = client.get(prefix + "/audit", headers=headers)
    assert audit.status_code == 200
    assert any(row["field"] == "diagnosis" and row["changed"] for row in audit.json())


def test_restart_releases_unfinished_mock_export(tmp_path):
    settings = Settings(app_mode="demo", database_url=f"sqlite:///{tmp_path / 'restart.db'}",
                        audio_storage_dir=tmp_path / "audio")
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        item = consultation(client, headers)
        prefix = f"/api/v1/consultations/{item['id']}"
        assert client.post(prefix + "/demo", headers=headers).status_code == 200
        draft = client.post(prefix + "/generate", headers=headers).json()
        reviewed = client.patch(prefix + "/document", json={"data": draft["data"], "version": draft["version"]}, headers=headers).json()
        assert client.post(prefix + "/approve", json={"version": reviewed["version"]}, headers=headers).status_code == 200
        with client.app.state.session_factory() as session:
            session.add(MISExport(consultation_id=item["id"], provider="mock", success=False))
            session.commit()
    with TestClient(create_app(settings)) as restarted:
        headers = login(restarted)
        sent = restarted.post(prefix + "/send-to-mis", headers=headers)
        assert sent.status_code == 200, sent.text
        assert sent.json()["success"] is True


def test_upload_rejects_bad_header_and_oversize(client):
    headers = login(client)
    item = consultation(client, headers)
    path = f"/api/v1/consultations/{item['id']}/audio"
    bad = client.post(path, headers=headers, files={"file": ("clip.wav", b"not-a-wave", "audio/wav")})
    assert bad.status_code == 415
    valid_header = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "
    uploaded = client.post(path, headers=headers, files={"file": ("clip.wav", valid_header, "audio/wav")})
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "RECORDING"


def test_recording_start_is_idempotent_before_transcription(client):
    headers = login(client)
    item = consultation(client, headers)
    path = f"/api/v1/consultations/{item['id']}/recording"
    assert client.post(path, headers=headers).json()["status"] == "RECORDING"
    assert client.post(path, headers=headers).json()["status"] == "RECORDING"


def test_upload_size_limit_is_enforced_before_storage(tmp_path):
    settings = Settings(app_mode="demo", database_url=f"sqlite:///{tmp_path / 'small.db'}",
                        jwt_secret="test-only-secret-with-enough-length-123456", audio_storage_dir=tmp_path / "audio", max_upload_mb=1)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        item = consultation(client, headers)
        path = f"/api/v1/consultations/{item['id']}/audio"
        response = client.post(path, headers=headers, files={"file": ("clip.wav", b"RIFF" + b"x" * (1024 * 1024), "audio/wav")})
        assert response.status_code == 413
        assert list((tmp_path / "audio").glob("*")) == [] if (tmp_path / "audio").exists() else True


def test_invalid_state_transition_and_regeneration_protects_review(client):
    headers = login(client)
    item = consultation(client, headers)
    prefix = f"/api/v1/consultations/{item['id']}"
    assert client.post(prefix + "/generate", headers=headers).status_code == 409
    assert client.post(prefix + "/demo", headers=headers).status_code == 200
    doc = client.post(prefix + "/generate", headers=headers).json()
    edited = client.patch(prefix + "/document", json={"data": doc["data"], "version": doc["version"]}, headers=headers)
    assert edited.status_code == 200
    assert client.post(prefix + "/generate", headers=headers).status_code == 409


def test_retention_only_removes_expired_registered_audio(client, tmp_path):
    headers = login(client)
    item = consultation(client, headers)
    path = f"/api/v1/consultations/{item['id']}/audio"
    valid_header = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "
    assert client.post(path, headers=headers, files={"file": ("clip.wav", valid_header, "audio/wav")}).status_code == 200
    storage = client.app.state.storage
    unrelated = storage.root / "unrelated.wav"
    unrelated.write_bytes(valid_header)
    with client.app.state.session_factory() as session:
        row = session.query(AudioFile).filter_by(consultation_id=item["id"]).one()
        stored = storage.get(row.storage_key)
        row.created_at = now_utc() - timedelta(days=8)
        session.commit()
        assert cleanup_expired_audio(session, storage, 7) == 1
        assert session.query(AudioFile).filter_by(consultation_id=item["id"]).count() == 0
    assert not stored.exists()
    assert unrelated.exists()


def test_retention_keeps_audio_while_consultation_processing(client):
    headers = login(client)
    item = consultation(client, headers)
    path = f"/api/v1/consultations/{item['id']}/audio"
    valid_header = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "
    assert client.post(path, headers=headers, files={"file": ("clip.wav", valid_header, "audio/wav")}).status_code == 200
    storage = client.app.state.storage
    with client.app.state.session_factory() as session:
        row = session.query(AudioFile).filter_by(consultation_id=item["id"]).one()
        consultation_row = session.get(Consultation, item["id"])
        row.created_at = now_utc() - timedelta(days=8)
        consultation_row.status = "PROCESSING"
        session.commit()
        assert cleanup_expired_audio(session, storage, 7) == 0
        assert storage.get(row.storage_key).is_file()


def test_transcribed_pii_is_masked_before_llm_boundary(client):
    headers = login(client)
    item = consultation(client, headers)
    prefix = f"/api/v1/consultations/{item['id']}"
    class LocalSTT:
        async def transcribe(self, _path):
            return Transcript(language="ru", duration=3.0, stt_model="fake", segments=[
                TranscriptSegment(start=0, end=3, text="Пациент Иванов Иван Иванович, ИИН 010203500123. Кашель три дня.")
            ])
    class CapturingLLM:
        input_text = ""
        async def extract_consultation(self, transcript, *, template_fields=None, on_stage=None):
            self.input_text = transcript.text
            return ExtractionResult(data=ConsultationData(complaints=["Кашель три дня"]))
    llm = CapturingLLM()
    client.app.state.stt = LocalSTT()
    client.app.state.llm = llm
    valid_header = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "
    assert client.post(prefix + "/audio", headers=headers, files={"file": ("clip.wav", valid_header, "audio/wav")}).status_code == 200
    assert client.post(prefix + "/transcribe", headers=headers).status_code == 200
    assert client.post(prefix + "/generate", headers=headers).status_code == 200
    assert "010203500123" not in llm.input_text
    assert "Иванов" not in llm.input_text
    assert "Кашель три дня" in llm.input_text
