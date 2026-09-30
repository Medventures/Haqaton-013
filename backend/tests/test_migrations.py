from pathlib import Path
import json
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_template_migration_preserves_existing_consultation_and_backfills_default(tmp_path: Path, monkeypatch):
    backend_dir = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'old.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "0001_initial")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, password_hash, role, display_name) VALUES ('user-1', 'doctor', 'hash', 'doctor', 'Doctor')"))
        connection.execute(text("INSERT INTO consultations (id, external_patient_id, status, created_by, created_at, updated_at) VALUES ('consult-1', 'SYN-1', 'CREATED', 'user-1', '2026-01-01', '2026-01-01')"))

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT template_id FROM consultations WHERE id='consult-1'")) == "therapist"
        assert connection.scalar(text("SELECT approved_by_name FROM consultations WHERE id='consult-1'")) is None

    command.downgrade(config, "0001_initial")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT template_id FROM consultations WHERE id='consult-1'")) == "therapist"
    engine.dispose()


def test_p0_migration_preserves_legacy_records(tmp_path: Path, monkeypatch):
    backend_dir = Path(__file__).resolve().parents[1]
    url = os.environ.get("MEDHUB_P0_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'legacy-p0.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "0002_consultation_template")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users VALUES ('user-1', 'doctor', 'legacy-hash', 'doctor', 'Врач')"))
        connection.execute(text("""INSERT INTO consultations
            (id, external_patient_id, template_id, status, created_by, created_at, updated_at, approved_at, approved_by, approved_by_name)
            VALUES ('consult-draft', 'SYN-DRAFT', 'therapist', 'REVIEWED', 'user-1', '2026-01-01', '2026-01-03', NULL, NULL, NULL),
                   ('consult-approved', 'SYN-APPROVED', 'therapist', 'APPROVED', 'user-1', '2026-01-02', '2026-01-04', '2026-01-04', 'user-1', 'Врач')"""))
        connection.execute(text("""INSERT INTO transcripts
            (id, consultation_id, raw_text, normalized_text, masked_text, language, duration_seconds, stt_model, segments, pii_entities, created_at)
            VALUES (:id, :consultation_id, :raw_text, :normalized_text, :masked_text, 'ru', 3.5, 'demo-fixture', :segments, :pii_entities, '2026-01-03')"""), {
                "id": "transcript-1", "consultation_id": "consult-draft",
                "raw_text": "  Исходная речь  ", "normalized_text": "Исправлено врачом", "masked_text": "[PERSON] обратился",
                "segments": json.dumps([{"start": 0.1, "end": 3.5, "text": "  Исходная речь  ", "speaker": None}], ensure_ascii=False),
                "pii_entities": json.dumps([{"type": "PERSON", "placeholder": "[PERSON]"}]),
            })
        connection.execute(text("""INSERT INTO consultation_documents
            (id, consultation_id, ai_generated_data, doctor_approved_data, working_data, llm_provider, llm_model, version, created_at, updated_at)
            VALUES (:id, :consultation_id, :ai, :approved, :working, 'demo', 'demo', :version, '2026-01-03', '2026-01-04')"""), [
                {"id": "document-draft", "consultation_id": "consult-draft", "ai": json.dumps({"complaints": ["AI"]}), "approved": None, "working": json.dumps({"complaints": ["Врач"]}, ensure_ascii=False), "version": 2},
                {"id": "document-approved", "consultation_id": "consult-approved", "ai": json.dumps({"complaints": ["AI"]}), "approved": json.dumps({"complaints": ["Утверждено"]}, ensure_ascii=False), "working": json.dumps({"complaints": ["Утверждено"]}, ensure_ascii=False), "version": 3},
            ])
        connection.execute(text("""INSERT INTO consultation_edits
            (id, consultation_id, field, ai_value, doctor_value, changed, created_at)
            VALUES ('edit-1', 'consult-draft', 'complaints', '["AI"]', '["Врач"]', TRUE, '2026-01-03')"""))
        before = connection.execute(text("SELECT * FROM transcripts WHERE id='transcript-1'")).mappings().one()
        approved_before = dict(connection.execute(text("SELECT * FROM consultations WHERE id='consult-approved'")).mappings().one())
        protected_before = {
            table: [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
            for table in ("users", "consultation_edits")
        }
        documents_before = [dict(row) for row in connection.execute(text("SELECT * FROM consultation_documents ORDER BY id")).mappings()]

    command.upgrade(config, "head")
    with engine.connect() as connection:
        from app.models import DocumentRow, TranscriptRevisionRow, TranscriptRow
        from sqlalchemy.orm import Session

        with Session(connection) as session:
            after = session.get(TranscriptRow, "transcript-1")
            assert after.raw_text == before["raw_text"]
            assert after.normalized_text == before["normalized_text"]
            assert after.masked_text == before["masked_text"]
            assert after.created_at == before["created_at"] or str(after.created_at).startswith("2026-01-03")
            assert after.revision == 1
            assert after.segments[0]["id"] == "seg-000001"
            assert after.segments[0]["text"] == "  Исходная речь  "
            snapshot = session.query(TranscriptRevisionRow).filter_by(transcript_id="transcript-1", revision=1).one()
            assert snapshot.segments == after.segments
            assert snapshot.masked_text == before["masked_text"]
            assert snapshot.actor_id is None
            assert snapshot.source == "demo"
            assert snapshot.created_at == after.created_at
            assert session.get(DocumentRow, "document-draft").source_transcript_revision == 1
            migrated_document = session.get(DocumentRow, "document-approved")
            assert migrated_document.source_transcript_revision is None
            assert migrated_document.source_masked_text is None
            assert migrated_document.evidence == []
        approved_after = dict(connection.execute(text("SELECT * FROM consultations WHERE id='consult-approved'")).mappings().one())
        assert approved_after == approved_before
        assert connection.scalar(text("SELECT count(*) FROM processing_runs")) == 0
        assert connection.scalar(text("SELECT count(*) FROM export_artifacts")) == 0
        for table, original in protected_before.items():
            assert [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()] == original
        for original in documents_before:
            row = dict(connection.execute(text("SELECT * FROM consultation_documents WHERE id=:id"), {"id": original["id"]}).mappings().one())
            for column, value in original.items():
                assert row[column] == value

    command.downgrade(config, "0002_consultation_template")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT revision FROM transcripts WHERE id='transcript-1'")) == 1
    engine.dispose()
