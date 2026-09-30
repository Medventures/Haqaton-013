from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Consultation, DocumentRow, TranscriptRevisionRow, TranscriptRow
from test_api import client as sqlite_client, consultation, login as api_login


def login(client):
    return api_login(client, password="revision-test" if client.app.state.settings.database_url.startswith("postgresql") else "demo-doctor")


@pytest.fixture(params=["sqlite", "postgresql"])
def client(request, sqlite_client, tmp_path):
    if request.param == "sqlite":
        yield sqlite_client
        return
    url = os.environ.get("MEDHUB_P0_REVISION_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated disposable PostgreSQL URL not supplied")
    from app.config import Settings
    from app.auth import password_hash
    from app.db import Base, make_engine
    from app.main import create_app
    engine = make_engine(url)
    # The explicit task database is disposable; never accept the configured live URL.
    assert engine.url.database == "medhub_p0_task4_20260930"
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    engine.dispose()
    settings = Settings(app_mode="live", database_url=url, audio_storage_dir=tmp_path / "pg-audio",
                        jwt_secret="test-only-secret-with-enough-length-123456",
                        doctor_password_hash=password_hash.hash("revision-test"),
                        openai_api_key="synthetic-test-key")
    # Startup must avoid demo migration; after startup enable synthetic fixture routes.
    with TestClient(create_app(settings)) as pg_client:
        from app.providers.demo import DemoLLMProvider
        settings.app_mode = "demo"
        pg_client.app.state.llm = DemoLLMProvider()
        yield pg_client


def prepared(client, *, generate=False, review=False):
    headers = login(client)
    item = consultation(client, headers)
    prefix = f"/api/v1/consultations/{item['id']}"
    response = client.post(prefix + "/demo", headers=headers)
    assert response.status_code == 200
    transcript = response.json()
    doc = None
    if generate or review:
        response = client.post(prefix + "/generate", headers=headers)
        assert response.status_code == 200, response.text
        doc = response.json()
    if review:
        response = client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]})
        assert response.status_code == 200
        doc = response.json()
    return headers, item["id"], prefix, transcript, doc


def patch(transcript, text="Телефон 87011234567. Кашель пять дней."):
    return {"expected_revision": transcript.get("revision", 1), "changes": [{"segment_id": transcript["segments"][0].get("id", "seg-000001"), "text": text}]}


def test_edit_preserves_original_and_invalidates_document(client):
    headers, cid, prefix, original, doc = prepared(client, review=True)
    response = client.patch(prefix + "/transcript", headers=headers, json=patch(original))
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["revision"] == original["revision"] + 1
    assert current["raw_text"] == original["raw_text"]
    assert [(s["id"], s["start"], s["end"]) for s in current["segments"]] == [(s["id"], s["start"], s["end"]) for s in original["segments"]]
    assert "87011234567" not in current["masked_text"]
    assert "87011234567" in current["current_text"]
    assert client.get(prefix, headers=headers).json()["status"] == "TRANSCRIBED"
    assert client.get(prefix + "/document", headers=headers).status_code == 409
    assert client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]}).status_code == 409
    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 409
    with client.app.state.session_factory() as session:
        row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
        revisions = session.scalars(select(TranscriptRevisionRow).where(TranscriptRevisionRow.transcript_id == row.id).order_by(TranscriptRevisionRow.revision)).all()
        assert [r.revision for r in revisions] == [1, 2]
        assert revisions[1].actor_id == session.get(Consultation, cid).created_by
        assert revisions[1].source == "doctor"
        assert revisions[0].segments == original["segments"]
        stored = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
        assert stored.working_data == doc["data"]
        assert stored.evidence == doc["evidence"]
    from app.schemas import ConsultationData, EvidenceClaim, ExtractionResult
    class CorrectedSourceLLM:
        async def extract_consultation(self, source, *, template_fields=None, on_stage=None):
            return ExtractionResult(data=ConsultationData(complaints=["Кашель пять дней"]), evidence=[
                EvidenceClaim(field_path="complaints/0", segment_id=source.segments[0].id, quote="Кашель пять дней")
            ])
    client.app.state.llm = CorrectedSourceLLM()
    regenerated = client.post(prefix + "/generate", headers=headers)
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["version"] == doc["version"] + 1
    assert regenerated.json()["source_transcript_revision"] == 2
    assert regenerated.json()["source_masked_text"] == current["masked_text"]
    assert client.post(prefix + "/approve", headers=headers, json={"version": regenerated.json()["version"]}).status_code == 409


def test_noop_edit_does_not_invalidate(client):
    headers, cid, prefix, transcript, doc = prepared(client, review=True)
    response = client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, transcript["segments"][0]["text"]))
    assert response.status_code == 200
    assert response.json() == transcript
    assert client.get(prefix, headers=headers).json()["status"] == "REVIEWED"
    assert client.get(prefix + "/document", headers=headers).json() == doc


@pytest.mark.parametrize("state", ["APPROVED", "SENT_TO_MIS", "PROCESSING", "CREATED", "RECORDING"])
def test_approved_and_processing_transcripts_are_locked(client, state):
    headers, cid, prefix, transcript, _ = prepared(client)
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = state
        session.commit()
    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 409


@pytest.mark.parametrize("changes", [[{"segment_id": "unknown", "text": "x"}], [{"segment_id": "seg-000001", "text": "x"}] * 2, [{"segment_id": "seg-000001", "text": "x", "start": 8}]])
def test_invalid_segment_edits_do_not_create_snapshots(client, changes):
    headers, cid, prefix, transcript, _ = prepared(client)
    response = client.patch(prefix + "/transcript", headers=headers, json={"expected_revision": 1, "changes": changes})
    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        assert session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid)).revision == 1
        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 1


def test_competing_transcript_edits_have_one_winner(client):
    headers, cid, prefix, transcript, _ = prepared(client)
    barrier = Barrier(2)
    def edit(text):
        barrier.wait(timeout=10)
        return client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, text)).status_code
    with ThreadPoolExecutor(2) as pool:
        codes = list(pool.map(edit, ["Кашель пять дней", "Кашель десять дней"]))
    assert sorted(codes) == [200, 409]
    current = client.get(prefix + "/transcript", headers=headers).json()
    assert current["revision"] == 2
    assert current["raw_text"] == transcript["raw_text"]


@pytest.mark.parametrize("operation", ["generate", "save", "approve"])
def test_edit_races_with_generation_save_and_approval(client, monkeypatch, operation):
    import app.main as main
    headers, cid, prefix, transcript, doc = prepared(client, generate=True, review=operation == "approve")
    barrier = Barrier(2)
    original = main.require_consultation
    def synchronized_read(*args, **kwargs):
        item = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return item
    monkeypatch.setattr(main, "require_consultation", synchronized_read)
    # Separate request event loops permit a real overlap even for async generation.
    edit_client = TestClient(client.app)
    document_client = TestClient(client.app)
    def write_document():
        if operation == "generate":
            return document_client.post(prefix + "/generate", headers=headers)
        if operation == "approve":
            return document_client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]})
        return document_client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]})
    with ThreadPoolExecutor(2) as pool:
        edit = pool.submit(edit_client.patch, prefix + "/transcript", headers=headers, json=patch(transcript))
        write = pool.submit(write_document)
        responses = [edit.result(timeout=20), write.result(timeout=20)]
    monkeypatch.setattr(main, "require_consultation", original)
    assert sorted(r.status_code for r in responses) == [200, 409]
    if responses[0].status_code == 200:
        assert client.get(prefix + "/document", headers=headers).status_code == 409
        assert client.get(prefix, headers=headers).json()["status"] == "TRANSCRIBED"


def test_stt_retry_appends_revision_without_replacing_original(client, monkeypatch):
    import app.providers.demo as demo
    from app.schemas import Transcript, TranscriptSegment
    headers, cid, prefix, transcript, _ = prepared(client)
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "FAILED"
        session.commit()
    monkeypatch.setattr(demo, "DEMO_TRANSCRIPT", Transcript(language="ru", duration=2, segments=[
        TranscriptSegment(start=0, end=2, text="Повторное распознавание: кашель неделю.")
    ]))
    response = client.post(prefix + "/demo", headers=headers)
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["raw_text"] == transcript["raw_text"]
    assert response.json()["current_text"] == "Повторное распознавание: кашель неделю."
    with client.app.state.session_factory() as session:
        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 2


def test_another_doctor_cannot_read_or_correct_transcript(client):
    from app.auth import make_token, password_hash
    from app.models import User
    headers, _, prefix, transcript, _ = prepared(client)
    with client.app.state.session_factory() as session:
        other = User(username="other", password_hash=password_hash.hash("test"), role="doctor", display_name="Other")
        session.add(other)
        session.commit()
        headers = {"Authorization": "Bearer " + make_token(other, client.app.state.settings.jwt_secret)}
    assert client.get(prefix + "/transcript", headers=headers).status_code == 404
    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 404


def test_freshness_does_not_depend_on_lifecycle_status(client):
    headers, cid, prefix, transcript, doc = prepared(client, review=True)
    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 200
    # A legacy/manual status change must not revive stale clinical data.
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "REVIEWED"
        session.commit()
    assert client.get(prefix + "/document", headers=headers).status_code == 409
    assert client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]}).status_code == 409
    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 409


@pytest.mark.parametrize("text_value", ["", " \n\t"])
def test_final_transcript_cannot_be_blank(client, text_value):
    headers, _, prefix, transcript, _ = prepared(client)
    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, text_value)).status_code == 422
    assert client.get(prefix + "/transcript", headers=headers).json()["revision"] == 1


def test_combined_limit_includes_unchanged_segments(client):
    headers, cid, prefix, transcript, _ = prepared(client)
    with client.app.state.session_factory() as session:
        row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
        row.segments = [{"id": f"seg-{i:06d}", "start": i, "end": i + 1, "text": "a" * 19000} for i in range(1, 27)]
        row.segments += [{"id": "seg-000027", "start": 27, "end": 28, "text": "x"}]
        session.commit()
    response = client.patch(prefix + "/transcript", headers=headers, json={"expected_revision": 1, "changes": [{"segment_id": "seg-000027", "text": "b" * 10000}]})
    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        assert session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid)).revision == 1
        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 1


def test_failed_without_transcript_cannot_be_edited(client):
    headers = login(client)
    cid = consultation(client, headers)["id"]
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "FAILED"
        session.commit()
    response = client.patch(f"/api/v1/consultations/{cid}/transcript", headers=headers, json={"expected_revision": 1, "changes": [{"segment_id": "seg-000001", "text": "x"}]})
    assert response.status_code == 409


def test_processing_gate_expires_previously_loaded_transcript(client):
    from app.service import claim_processing
    headers, cid, prefix, transcript, _ = prepared(client)
    with client.app.state.session_factory() as first:
        cached = first.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
        first.commit()  # Explicitly retain the cached row (expire_on_commit=False).
        assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 200
        item = first.get(Consultation, cid)
        assert cached.revision == 1
        claim_processing(first, item, {"TRANSCRIBED"})
        assert cached.revision == 2
        assert "Кашель пять дней" in cached.normalized_text


def test_approved_legacy_document_without_transcript_remains_exportable(client):
    from app.models import now_utc
    from app.schemas import ConsultationData
    headers = login(client)
    cid = consultation(client, headers)["id"]
    with client.app.state.session_factory() as session:
        item = session.get(Consultation, cid)
        item.status = "APPROVED"
        item.approved_at = now_utc()
        payload = ConsultationData(complaints=["Синтетическая архивная запись"]).model_dump(mode="json")
        session.add(DocumentRow(consultation_id=cid, ai_generated_data=payload, working_data=payload,
                                doctor_approved_data=payload, llm_provider="legacy", llm_model="unknown"))
        session.commit()
    response = client.get(f"/api/v1/consultations/{cid}/document", headers=headers)
    assert response.status_code == 200
    assert response.json()["source_transcript_revision"] is None
    assert response.json()["source_masked_text"] is None
    assert client.get(f"/api/v1/consultations/{cid}/document.docx", headers=headers).status_code == 200
