# Task 1 review package

No Git repository. Unified diffs against pre-task source snapshot. Scope additionally authorized hardcoded migration-head assertion in test_api.py.

## backend/app/models.py
```diff
--- before/backend/app/models.py
+++ after/backend/app/models.py
@@ -49,39 +49,69 @@
 class TranscriptRow(Base):
     __tablename__ = "transcripts"
     id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
     consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
     raw_text: Mapped[str] = mapped_column(Text, nullable=False)
     normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
     masked_text: Mapped[str] = mapped_column(Text, nullable=False)
     language: Mapped[str] = mapped_column(String(20), nullable=False)
     duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
     stt_model: Mapped[str] = mapped_column(String(120), nullable=False)
+    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
     segments: Mapped[list] = mapped_column(JSONValue, nullable=False)
     pii_entities: Mapped[list] = mapped_column(JSONValue, nullable=False)
     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
 
 
+class TranscriptRevisionRow(Base):
+    __tablename__ = "transcript_revisions"
+    __table_args__ = (UniqueConstraint("transcript_id", "revision"),)
+    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
+    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"), nullable=False, index=True)
+    revision: Mapped[int] = mapped_column(Integer, nullable=False)
+    segments: Mapped[list] = mapped_column(JSONValue, nullable=False)
+    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
+    masked_text: Mapped[str] = mapped_column(Text, nullable=False)
+    pii_entities: Mapped[list] = mapped_column(JSONValue, nullable=False)
+    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
+    source: Mapped[str] = mapped_column(String(20), nullable=False)
+    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=True)
+
+
 class DocumentRow(Base):
     __tablename__ = "consultation_documents"
     id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
     consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
     ai_generated_data: Mapped[dict] = mapped_column(JSONValue, nullable=False)
     doctor_approved_data: Mapped[dict | None] = mapped_column(JSONValue, nullable=True)
     working_data: Mapped[dict] = mapped_column(JSONValue, nullable=False)
     llm_provider: Mapped[str] = mapped_column(String(100), nullable=False)
     llm_model: Mapped[str] = mapped_column(String(120), nullable=False)
     version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
+    source_transcript_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    evidence: Mapped[list] = mapped_column(JSONValue, nullable=False, default=list, server_default="[]")
+    source_masked_text: Mapped[str | None] = mapped_column(Text, nullable=True)
     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
     updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
 
 
+class ProcessingRunRow(Base):
+    __tablename__ = "processing_runs"
+    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
+    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), nullable=False, index=True)
+    operation: Mapped[str] = mapped_column(String(20), nullable=False)
+    status: Mapped[str] = mapped_column(String(20), nullable=False)
+    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
+    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
+    stages: Mapped[list] = mapped_column(JSONValue, nullable=False, default=list, server_default="[]")
+
+
 class ConsultationEdit(Base):
     __tablename__ = "consultation_edits"
     id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
     consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
     field: Mapped[str] = mapped_column(String(100), nullable=False)
     ai_value: Mapped[object] = mapped_column(JSONValue, nullable=True)
     doctor_value: Mapped[object] = mapped_column(JSONValue, nullable=True)
     changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
 

```

## backend/app/schemas.py
```diff
--- before/backend/app/schemas.py
+++ after/backend/app/schemas.py
@@ -1,16 +1,17 @@
 """Shared clinical contracts. Unknown fields are rejected at every boundary."""
 
+from datetime import datetime, timezone
 from enum import StrEnum
 from typing import Annotated, Self
 
-from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
+from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
 
 
 ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
 LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]
 
 
 class StrictModel(BaseModel):
     model_config = ConfigDict(extra="forbid", validate_assignment=True)
 
 
@@ -68,35 +69,132 @@
     text: str = Field(max_length=20000)
     speaker: ShortText | None = None
 
     @model_validator(mode="after")
     def ordered_times(self) -> Self:
         if self.end < self.start:
             raise ValueError("Segment end must not precede its start")
         return self
 
 
+class StoredTranscriptSegment(TranscriptSegment):
+    id: str = Field(min_length=1, max_length=64)
+
+
+class TranscriptTextChange(StrictModel):
+    segment_id: str = Field(min_length=1, max_length=64)
+    text: str = Field(max_length=20000)
+
+
+class TranscriptPatch(StrictModel):
+    expected_revision: int = Field(ge=1)
+    changes: list[TranscriptTextChange] = Field(min_length=1, max_length=50000)
+
+    @model_validator(mode="after")
+    def valid_changes(self) -> Self:
+        ids = [change.segment_id for change in self.changes]
+        if len(ids) != len(set(ids)):
+            raise ValueError("Segment IDs must be unique")
+        if sum(len(change.text) for change in self.changes) > 500000:
+            raise ValueError("Changed text is too long")
+        return self
+
+
 class Transcript(StrictModel):
     language: str = Field(min_length=2, max_length=12)
     duration: float = Field(ge=0, allow_inf_nan=False)
     segments: list[TranscriptSegment] = Field(default_factory=list, max_length=50000)
     stt_model: ShortText = "unknown"
 
     @property
     def raw_text(self) -> str:
         return " ".join(segment.text.strip() for segment in self.segments).strip()
 
 
 class PIIEntity(StrictModel):
     type: str = Field(min_length=1, max_length=50)
     placeholder: str = Field(min_length=1, max_length=100)
 
 
+class CanonicalTranscript(StrictModel):
+    revision: int = Field(ge=1)
+    segments: list[StoredTranscriptSegment] = Field(max_length=50000)
+    text: str = Field(max_length=500000)
+    entities: list[PIIEntity] = Field(default_factory=list)
+
+
+class EvidenceClaim(StrictModel):
+    field_path: str = Field(min_length=1, max_length=200)
+    segment_id: str = Field(min_length=1, max_length=64)
+    quote: str = Field(min_length=1, max_length=2000)
+
+    @field_validator("quote")
+    @classmethod
+    def nonblank_quote(cls, value: str) -> str:
+        if not value.strip():
+            raise ValueError("Quote must contain non-whitespace text")
+        return value
+
+
+class EvidenceLink(EvidenceClaim):
+    transcript_revision: int = Field(ge=1)
+    start: float = Field(ge=0, allow_inf_nan=False)
+    end: float = Field(ge=0, allow_inf_nan=False)
+
+    @model_validator(mode="after")
+    def ordered_times(self) -> Self:
+        if self.end < self.start:
+            raise ValueError("Evidence end must not precede its start")
+        return self
+
+
+class ExtractionResult(StrictModel):
+    data: ConsultationData
+    evidence: list[EvidenceClaim] = Field(default_factory=list, max_length=1000)
+
+
+class ProcessingStage(StrictModel):
+    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
+    attempt: int = Field(ge=1)
+    status: str = Field(pattern=r"^(pending|running|done|error)$")
+    started_at: datetime | None = None
+    finished_at: datetime | None = None
+    duration_ms: int | None = Field(default=None, ge=0)
+    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
+
+    @field_validator("started_at", "finished_at")
+    @classmethod
+    def utc_time(cls, value: datetime | None) -> datetime | None:
+        if value is None:
+            return None
+        if value.tzinfo is None or value.utcoffset() is None:
+            raise ValueError("Timestamp must be timezone-aware")
+        return value.astimezone(timezone.utc)
+
+
+class ProcessingRun(StrictModel):
+    id: str = Field(min_length=1, max_length=36)
+    operation: str = Field(pattern=r"^(upload|transcribe|generate)$")
+    status: str = Field(pattern=r"^(running|done|error)$")
+    started_at: datetime
+    finished_at: datetime | None = None
+    stages: list[ProcessingStage] = Field(default_factory=list)
+
+    @field_validator("started_at", "finished_at")
+    @classmethod
+    def utc_time(cls, value: datetime | None) -> datetime | None:
+        if value is None:
+            return None
+        if value.tzinfo is None or value.utcoffset() is None:
+            raise ValueError("Timestamp must be timezone-aware")
+        return value.astimezone(timezone.utc)
+
+
 class MaskedTranscript(StrictModel):
     text: str = Field(max_length=500000)
     entities: list[PIIEntity] = Field(default_factory=list)
 
 
 class MISResult(StrictModel):
     success: bool
     document_id: str = Field(min_length=1, max_length=200)
     provider: str = "mock"

```

## backend/alembic/versions/0003_trust_workflow.py
```diff
--- before/backend/alembic/versions/0003_trust_workflow.py
+++ after/backend/alembic/versions/0003_trust_workflow.py
@@ -0,0 +1,108 @@
+"""Add transcript revisions, document provenance, and processing runs.
+
+Revision ID: 0003_trust_workflow
+Revises: 0002_consultation_template
+"""
+
+from uuid import NAMESPACE_URL, uuid5
+
+from alembic import op
+import sqlalchemy as sa
+from sqlalchemy.dialects.postgresql import JSONB
+
+
+revision = "0003_trust_workflow"
+down_revision = "0002_consultation_template"
+branch_labels = None
+depends_on = None
+
+JSONValue = sa.JSON().with_variant(JSONB(), "postgresql")
+
+
+def upgrade() -> None:
+    op.add_column("transcripts", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
+    op.add_column("consultation_documents", sa.Column("source_transcript_revision", sa.Integer(), nullable=True))
+    op.add_column("consultation_documents", sa.Column("evidence", JSONValue, nullable=False, server_default="[]"))
+    op.add_column("consultation_documents", sa.Column("source_masked_text", sa.Text(), nullable=True))
+    op.create_table(
+        "transcript_revisions",
+        sa.Column("id", sa.String(36), primary_key=True),
+        sa.Column("transcript_id", sa.String(36), sa.ForeignKey("transcripts.id"), nullable=False),
+        sa.Column("revision", sa.Integer(), nullable=False),
+        sa.Column("segments", JSONValue, nullable=False),
+        sa.Column("normalized_text", sa.Text(), nullable=False),
+        sa.Column("masked_text", sa.Text(), nullable=False),
+        sa.Column("pii_entities", JSONValue, nullable=False),
+        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
+        sa.Column("source", sa.String(20), nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
+        sa.UniqueConstraint("transcript_id", "revision"),
+    )
+    op.create_index("ix_transcript_revisions_transcript_id", "transcript_revisions", ["transcript_id"])
+    op.create_table(
+        "processing_runs",
+        sa.Column("id", sa.String(36), primary_key=True),
+        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False),
+        sa.Column("operation", sa.String(20), nullable=False),
+        sa.Column("status", sa.String(20), nullable=False),
+        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
+        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
+        sa.Column("stages", JSONValue, nullable=False, server_default="[]"),
+    )
+    op.create_index("ix_processing_runs_consultation_id", "processing_runs", ["consultation_id"])
+
+    transcripts = sa.table(
+        "transcripts",
+        sa.column("id", sa.String(36)),
+        sa.column("stt_model", sa.String(120)),
+        sa.column("segments", JSONValue),
+        sa.column("normalized_text", sa.Text()),
+        sa.column("masked_text", sa.Text()),
+        sa.column("pii_entities", JSONValue),
+        sa.column("created_at", sa.DateTime(timezone=True)),
+    )
+    snapshots = sa.table(
+        "transcript_revisions",
+        sa.column("id", sa.String(36)),
+        sa.column("transcript_id", sa.String(36)),
+        sa.column("revision", sa.Integer()),
+        sa.column("segments", JSONValue),
+        sa.column("normalized_text", sa.Text()),
+        sa.column("masked_text", sa.Text()),
+        sa.column("pii_entities", JSONValue),
+        sa.column("actor_id", sa.String(36)),
+        sa.column("source", sa.String(20)),
+        sa.column("created_at", sa.DateTime(timezone=True)),
+    )
+    connection = op.get_bind()
+    for transcript in connection.execute(sa.select(transcripts)).mappings():
+        segments = [dict(segment, id=f"seg-{index:06d}") for index, segment in enumerate(transcript["segments"], 1)]
+        connection.execute(sa.update(transcripts).where(transcripts.c.id == transcript["id"]).values(segments=segments))
+        connection.execute(sa.insert(snapshots).values(
+            id=str(uuid5(NAMESPACE_URL, f"medhub/transcript-revision/{transcript['id']}/1")),
+            transcript_id=transcript["id"],
+            revision=1,
+            segments=segments,
+            normalized_text=transcript["normalized_text"],
+            masked_text=transcript["masked_text"],
+            pii_entities=transcript["pii_entities"],
+            actor_id=None,
+            source="demo" if transcript["stt_model"] == "demo-fixture" else "stt",
+            created_at=transcript["created_at"],
+        ))
+
+    connection.execute(sa.text("""UPDATE consultation_documents
+        SET source_transcript_revision = 1
+        WHERE EXISTS (SELECT 1 FROM transcripts
+                      WHERE transcripts.consultation_id = consultation_documents.consultation_id)"""))
+
+
+def downgrade() -> None:
+    op.drop_index("ix_processing_runs_consultation_id", table_name="processing_runs")
+    op.drop_table("processing_runs")
+    op.drop_index("ix_transcript_revisions_transcript_id", table_name="transcript_revisions")
+    op.drop_table("transcript_revisions")
+    op.drop_column("consultation_documents", "source_masked_text")
+    op.drop_column("consultation_documents", "evidence")
+    op.drop_column("consultation_documents", "source_transcript_revision")
+    op.drop_column("transcripts", "revision")

```

## backend/tests/test_schemas.py
```diff
--- before/backend/tests/test_schemas.py
+++ after/backend/tests/test_schemas.py
@@ -27,10 +27,53 @@
         TranscriptSegment(start=5, end=2, text="Синтетический пример")
 
 
 def test_specialty_values_are_retained_without_inventing_defaults():
     data = ConsultationData.model_validate({"template_fields": [
         {"key": "status_localis", "value": "Уточнение врача"},
         {"key": "growth", "value": None},
     ]})
     assert data.model_dump()["template_fields"][0]["value"] == "Уточнение врача"
     assert data.model_dump()["template_fields"][1]["value"] is None
+
+
+def test_evidence_rejects_model_owned_times_and_blank_quote():
+    from app.schemas import EvidenceClaim, ExtractionResult
+
+    data = {"field_path": "complaints/0", "segment_id": "seg-000001", "quote": "  боль  "}
+    assert EvidenceClaim.model_validate(data).quote == "  боль  "
+    for extra in ({"start": 0.0}, {"end": 1.0}, {"transcript_revision": 1}):
+        with pytest.raises(ValidationError):
+            EvidenceClaim.model_validate({**data, **extra})
+    with pytest.raises(ValidationError):
+        EvidenceClaim.model_validate({**data, "quote": " \t\n "})
+    with pytest.raises(ValidationError):
+        ExtractionResult.model_validate({"data": {}, "evidence": [{**data, "start": 0.0}]})
+    assert ExtractionResult.model_validate({"data": {}, "evidence": [data]}).evidence[0].quote == "  боль  "
+
+
+def test_transcript_patch_bounds():
+    from app.schemas import TranscriptPatch
+
+    valid = {"expected_revision": 1, "changes": [{"segment_id": "seg-000001", "text": "  исправлено  "}]}
+    assert TranscriptPatch.model_validate(valid).changes[0].text == "  исправлено  "
+    for invalid in (
+        {**valid, "expected_revision": -1},
+        {**valid, "expected_revision": 0},
+        {**valid, "changes": [{"segment_id": "seg-000001", "text": "x" * 20001}]},
+        {**valid, "changes": [{"segment_id": "seg-000001", "text": "a"}, {"segment_id": "seg-000001", "text": "b"}]},
+        {**valid, "changes": [{"segment_id": "seg-000001", "text": "a", "start": 0.0}]},
+    ):
+        with pytest.raises(ValidationError):
+            TranscriptPatch.model_validate(invalid)
+
+
+def test_processing_stage_rejects_invented_duration_and_run_status():
+    from app.schemas import ProcessingRun, ProcessingStage
+
+    stage = {"key": "stt", "attempt": 1, "status": "pending"}
+    assert ProcessingStage.model_validate(stage).duration_ms is None
+    for change in ({"attempt": 0}, {"duration_ms": -1}, {"status": "unknown"}):
+        with pytest.raises(ValidationError):
+            ProcessingStage.model_validate({**stage, **change})
+    with pytest.raises(ValidationError):
+        ProcessingRun.model_validate({"id": "run-1", "operation": "unknown", "status": "running", "started_at": "2026-01-01T00:00:00Z", "stages": []})

```

## backend/tests/test_migrations.py
```diff
--- before/backend/tests/test_migrations.py
+++ after/backend/tests/test_migrations.py
@@ -1,11 +1,13 @@
 from pathlib import Path
+import json
+import os
 
 from alembic import command
 from alembic.config import Config
 from sqlalchemy import create_engine, text
 
 
 def test_template_migration_preserves_existing_consultation_and_backfills_default(tmp_path: Path, monkeypatch):
     backend_dir = Path(__file__).resolve().parents[1]
     url = f"sqlite:///{tmp_path / 'old.db'}"
     monkeypatch.setenv("DATABASE_URL", url)
@@ -21,10 +23,91 @@
     command.upgrade(config, "head")
     with engine.connect() as connection:
         assert connection.scalar(text("SELECT template_id FROM consultations WHERE id='consult-1'")) == "therapist"
         assert connection.scalar(text("SELECT approved_by_name FROM consultations WHERE id='consult-1'")) is None
 
     command.downgrade(config, "0001_initial")
     command.upgrade(config, "head")
     with engine.connect() as connection:
         assert connection.scalar(text("SELECT template_id FROM consultations WHERE id='consult-1'")) == "therapist"
     engine.dispose()
+
+
+def test_p0_migration_preserves_legacy_records(tmp_path: Path, monkeypatch):
+    backend_dir = Path(__file__).resolve().parents[1]
+    url = os.environ.get("MEDHUB_P0_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'legacy-p0.db'}"
+    monkeypatch.setenv("DATABASE_URL", url)
+    config = Config(str(backend_dir / "alembic.ini"))
+    config.set_main_option("script_location", str(backend_dir / "alembic"))
+    command.upgrade(config, "0002_consultation_template")
+    engine = create_engine(url)
+    with engine.begin() as connection:
+        connection.execute(text("INSERT INTO users VALUES ('user-1', 'doctor', 'legacy-hash', 'doctor', 'Врач')"))
+        connection.execute(text("""INSERT INTO consultations
+            (id, external_patient_id, template_id, status, created_by, created_at, updated_at, approved_at, approved_by, approved_by_name)
+            VALUES ('consult-draft', 'SYN-DRAFT', 'therapist', 'REVIEWED', 'user-1', '2026-01-01', '2026-01-03', NULL, NULL, NULL),
+                   ('consult-approved', 'SYN-APPROVED', 'therapist', 'APPROVED', 'user-1', '2026-01-02', '2026-01-04', '2026-01-04', 'user-1', 'Врач')"""))
+        connection.execute(text("""INSERT INTO transcripts
+            (id, consultation_id, raw_text, normalized_text, masked_text, language, duration_seconds, stt_model, segments, pii_entities, created_at)
+            VALUES (:id, :consultation_id, :raw_text, :normalized_text, :masked_text, 'ru', 3.5, 'demo-fixture', :segments, :pii_entities, '2026-01-03')"""), {
+                "id": "transcript-1", "consultation_id": "consult-draft",
+                "raw_text": "  Исходная речь  ", "normalized_text": "Исправлено врачом", "masked_text": "[PERSON] обратился",
+                "segments": json.dumps([{"start": 0.1, "end": 3.5, "text": "  Исходная речь  ", "speaker": None}], ensure_ascii=False),
+                "pii_entities": json.dumps([{"type": "PERSON", "placeholder": "[PERSON]"}]),
+            })
+        connection.execute(text("""INSERT INTO consultation_documents
+            (id, consultation_id, ai_generated_data, doctor_approved_data, working_data, llm_provider, llm_model, version, created_at, updated_at)
+            VALUES (:id, :consultation_id, :ai, :approved, :working, 'demo', 'demo', :version, '2026-01-03', '2026-01-04')"""), [
+                {"id": "document-draft", "consultation_id": "consult-draft", "ai": json.dumps({"complaints": ["AI"]}), "approved": None, "working": json.dumps({"complaints": ["Врач"]}, ensure_ascii=False), "version": 2},
+                {"id": "document-approved", "consultation_id": "consult-approved", "ai": json.dumps({"complaints": ["AI"]}), "approved": json.dumps({"complaints": ["Утверждено"]}, ensure_ascii=False), "working": json.dumps({"complaints": ["Утверждено"]}, ensure_ascii=False), "version": 3},
+            ])
+        connection.execute(text("""INSERT INTO consultation_edits
+            (id, consultation_id, field, ai_value, doctor_value, changed, created_at)
+            VALUES ('edit-1', 'consult-draft', 'complaints', '["AI"]', '["Врач"]', TRUE, '2026-01-03')"""))
+        before = connection.execute(text("SELECT * FROM transcripts WHERE id='transcript-1'")).mappings().one()
+        approved_before = dict(connection.execute(text("SELECT * FROM consultations WHERE id='consult-approved'")).mappings().one())
+        protected_before = {
+            table: [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
+            for table in ("users", "consultation_edits")
+        }
+        documents_before = [dict(row) for row in connection.execute(text("SELECT * FROM consultation_documents ORDER BY id")).mappings()]
+
+    command.upgrade(config, "head")
+    with engine.connect() as connection:
+        from app.models import DocumentRow, TranscriptRevisionRow, TranscriptRow
+        from sqlalchemy.orm import Session
+
+        with Session(connection) as session:
+            after = session.get(TranscriptRow, "transcript-1")
+            assert after.raw_text == before["raw_text"]
+            assert after.normalized_text == before["normalized_text"]
+            assert after.masked_text == before["masked_text"]
+            assert after.created_at == before["created_at"] or str(after.created_at).startswith("2026-01-03")
+            assert after.revision == 1
+            assert after.segments[0]["id"] == "seg-000001"
+            assert after.segments[0]["text"] == "  Исходная речь  "
+            snapshot = session.query(TranscriptRevisionRow).filter_by(transcript_id="transcript-1", revision=1).one()
+            assert snapshot.segments == after.segments
+            assert snapshot.masked_text == before["masked_text"]
+            assert snapshot.actor_id is None
+            assert snapshot.source == "demo"
+            assert snapshot.created_at == after.created_at
+            assert session.get(DocumentRow, "document-draft").source_transcript_revision == 1
+            migrated_document = session.get(DocumentRow, "document-approved")
+            assert migrated_document.source_transcript_revision is None
+            assert migrated_document.source_masked_text is None
+            assert migrated_document.evidence == []
+        approved_after = dict(connection.execute(text("SELECT * FROM consultations WHERE id='consult-approved'")).mappings().one())
+        assert approved_after == approved_before
+        assert connection.scalar(text("SELECT count(*) FROM processing_runs")) == 0
+        for table, original in protected_before.items():
+            assert [dict(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()] == original
+        for original in documents_before:
+            row = dict(connection.execute(text("SELECT * FROM consultation_documents WHERE id=:id"), {"id": original["id"]}).mappings().one())
+            for column, value in original.items():
+                assert row[column] == value
+
+    command.downgrade(config, "0002_consultation_template")
+    command.upgrade(config, "head")
+    with engine.connect() as connection:
+        assert connection.scalar(text("SELECT revision FROM transcripts WHERE id='transcript-1'")) == 1
+    engine.dispose()

```

## backend/tests/test_api.py
```diff
--- before/backend/tests/test_api.py
+++ after/backend/tests/test_api.py
@@ -41,21 +41,21 @@
 
 def test_authentication_required_and_bad_password_rejected(client):
     assert client.get("/api/v1/consultations").status_code == 401
     assert client.post("/api/v1/auth/login", json={"username": "doctor", "password": "wrong"}).status_code == 401
     headers = login(client)
     assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "doctor"
 
 
 def test_new_demo_database_records_alembic_revision(client):
     with client.app.state.session_factory() as session:
-        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0002_consultation_template"
+        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0003_trust_workflow"
 
 
 def test_template_catalog_requires_auth_and_selection_persists(client):
     assert client.get("/api/v1/templates").status_code == 401
     headers = login(client)
     templates = client.get("/api/v1/templates", headers=headers)
     assert templates.status_code == 200
     assert {template["id"] for template in templates.json()} == {
         "therapist", "therapist_initial", "cardiologist", "pediatrician", "proctologist", "surgeon"
     }

```

