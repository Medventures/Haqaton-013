from datetime import timedelta
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.models import AudioFile, Consultation, DocumentRow, now_utc
from test_processing import WAV, upload
from test_transcript_revisions import client, sqlite_client, consultation, login, prepared


def test_audio_requires_auth_owner_and_actual_unexpired_file(client):
    from app.auth import make_token, password_hash
    from app.models import User
    headers = login(client)
    cid = consultation(client, headers)["id"]
    prefix = f"/api/v1/consultations/{cid}"
    assert client.get(prefix + "/audio").status_code == 401
    assert client.get(prefix + "/audio", headers=headers).status_code == 404
    assert upload(client, prefix, headers).status_code == 200
    response = client.get(prefix + "/audio", headers=headers)
    assert response.status_code == 200
    assert response.content == WAV
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert client.get(prefix, headers=headers).json()["audio_available"] is True
    with client.app.state.session_factory() as session:
        other = User(username="file-other", password_hash=password_hash.hash("test"), role="doctor", display_name="Other")
        session.add(other)
        session.commit()
        other_headers = {"Authorization": "Bearer " + make_token(other, client.app.state.settings.jwt_secret)}
    assert client.get(prefix + "/audio", headers=other_headers).status_code == 404
    assert client.get(prefix + "/document.pdf", headers=other_headers).status_code == 404
    with client.app.state.session_factory() as session:
        audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == cid))
        audio.created_at = now_utc() - timedelta(days=8)
        session.commit()
    assert client.get(prefix + "/audio", headers=headers).status_code == 404
    assert client.get(prefix, headers=headers).json()["audio_available"] is False


def test_demo_and_deleted_audio_are_unavailable(client, monkeypatch):
    headers, cid, prefix, _, _ = prepared(client)
    assert client.get(prefix + "/audio", headers=headers).status_code == 404
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "FAILED"
        session.commit()
    assert upload(client, prefix, headers).status_code == 200
    assert client.get(prefix + "/audio", headers=headers).status_code == 404
    # A genuine recording without a synthetic transcript is available until deletion.
    cid = consultation(client, headers)["id"]
    prefix = f"/api/v1/consultations/{cid}"
    assert upload(client, prefix, headers).status_code == 200
    storage = client.app.state.storage
    original_get = storage.get
    def removed_after_check(key):
        path = original_get(key)
        path.unlink()
        return path
    monkeypatch.setattr(storage, "get", removed_after_check)
    assert client.get(prefix + "/audio", headers=headers).status_code == 404
    assert client.get(prefix, headers=headers).json()["audio_available"] is False


def test_pdf_uses_approved_not_working_snapshot(client):
    headers, cid, prefix, _, doc = prepared(client, review=True)
    assert client.get(prefix + "/document.pdf").status_code == 401
    assert client.get(prefix + "/document.pdf", headers=headers).status_code == 409
    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 200
    with client.app.state.session_factory() as session:
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
        row.working_data = {**row.working_data, "complaints": ["UNSAVED_SENTINEL"]}
        # Historical optional metadata must not prevent an approved export.
        row.source_masked_text = None
        row.evidence = []
        session.commit()
    response = client.get(prefix + "/document.pdf", headers=headers)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert ".pdf" in response.headers["content-disposition"]
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "UNSAVED_SENTINEL" not in text
    assert "кашель" in text.lower()


def test_audio_path_replaced_by_symlink_is_not_served(client, monkeypatch, tmp_path):
    headers = login(client)
    cid = consultation(client, headers)["id"]
    prefix = f"/api/v1/consultations/{cid}"
    assert upload(client, prefix, headers).status_code == 200
    target = tmp_path / "unrelated-private-file"
    target.write_bytes(b"DO_NOT_SERVE_THIS_FILE")
    storage = client.app.state.storage
    original_get = storage.get
    def replaced_after_check(key):
        path = original_get(key)
        path.unlink()
        path.symlink_to(target)
        return path
    monkeypatch.setattr(storage, "get", replaced_after_check)
    response = client.get(prefix + "/audio", headers=headers)
    assert response.status_code == 404
    assert b"DO_NOT_SERVE_THIS_FILE" not in response.content
