# Task4 review package

Unified diff against immediate pre-task snapshot (includes previous tasks baseline). New files against /dev/null.

## backend/app/transcripts.py
```diff
--- before/backend/app/transcripts.py
+++ after/backend/app/transcripts.py
@@ -0,0 +1,87 @@
+"""Revision transitions. Callers own the enclosing transaction and commit."""
+from __future__ import annotations
+
+from fastapi import HTTPException
+from sqlalchemy import select
+from sqlalchemy.orm import Session
+
+from .grounding import mask_segments, normalize_segments
+from .models import Consultation, DocumentRow, TranscriptRevisionRow, TranscriptRow, now_utc
+from .schemas import StoredTranscriptSegment, TranscriptPatch
+from .service import claim_write
+
+
+def canonical_source(row: TranscriptRow):
+    return mask_segments([StoredTranscriptSegment.model_validate(s) for s in row.segments], revision=row.revision)
+
+
+def _snapshot(session: Session, row: TranscriptRow, *, actor_id: str | None, source: str) -> None:
+    session.flush()
+    session.add(TranscriptRevisionRow(
+        transcript_id=row.id, revision=row.revision, segments=row.segments,
+        normalized_text=row.normalized_text, masked_text=row.masked_text,
+        pii_entities=row.pii_entities, actor_id=actor_id, source=source,
+    ))
+
+
+def _project(row: TranscriptRow, segments: list[StoredTranscriptSegment]) -> None:
+    normalized = normalize_segments(segments)
+    source = mask_segments(segments, revision=row.revision)
+    row.segments = [s.model_dump(mode="json") for s in segments]
+    row.normalized_text = "\n".join(s.text for s in normalized)
+    row.masked_text = source.text
+    row.pii_entities = [entity.model_dump(mode="json") for entity in source.entities]
+
+
+def save_initial_transcript(session: Session, consultation: Consultation, transcript, *, actor_id: str | None, source: str, stt_model: str) -> TranscriptRow:
+    raw = transcript.model_dump() if hasattr(transcript, "model_dump") else dict(transcript)
+    parts = raw.get("segments", [])
+    text = raw.get("text") or raw.get("raw_text") or "\n".join(s["text"] for s in parts)
+    if not text.strip():
+        raise ValueError("empty transcription")
+    duration = float(raw.get("duration_seconds", raw.get("duration", 0)))
+    if not parts:
+        parts = [{"start": 0, "end": duration, "text": text}]
+    row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation.id).execution_options(populate_existing=True))
+    if row is None:
+        row = TranscriptRow(consultation_id=consultation.id, raw_text=text, revision=1)
+        session.add(row)
+    else:
+        row.revision += 1
+    segments = [StoredTranscriptSegment.model_validate({**s, "id": f"seg-{index:06d}"}) for index, s in enumerate(parts, 1)]
+    row.language = raw.get("language") or "ru"
+    row.duration_seconds = duration
+    row.stt_model = stt_model
+    _project(row, segments)
+    _snapshot(session, row, actor_id=actor_id, source=source)
+    return row
+
+
+def edit_transcript(session: Session, consultation: Consultation, patch: TranscriptPatch, *, actor_id: str) -> TranscriptRow:
+    claim_write(session, consultation, {"TRANSCRIBED", "AI_GENERATED", "REVIEWED", "FAILED"}, expected_revision=patch.expected_revision)
+    row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation.id))
+    if row is None or row.revision != patch.expected_revision:
+        raise HTTPException(409, "Версия транскрипции устарела")
+    changes = {change.segment_id: change.text for change in patch.changes}
+    if not changes.keys() <= {segment["id"] for segment in row.segments}:
+        raise HTTPException(422, "Неизвестный фрагмент транскрипции")
+    segments = [StoredTranscriptSegment.model_validate({**s, "text": changes.get(s["id"], s["text"])}) for s in row.segments]
+    current = "\n".join(s.text for s in segments)
+    if len(current) > 500000 or not current.strip():
+        raise HTTPException(422, "Некорректный текст транскрипции")
+    if all(s.text == previous["text"] for s, previous in zip(segments, row.segments, strict=True)):
+        return row
+    row.revision += 1
+    _project(row, segments)
+    _snapshot(session, row, actor_id=actor_id, source="doctor")
+    consultation.status = "TRANSCRIBED"
+    consultation.error_message = None
+    consultation.updated_at = now_utc()
+    return row
+
+
+def require_fresh_document(document: DocumentRow, transcript: TranscriptRow | None) -> None:
+    if (transcript is None and document.source_transcript_revision is not None) or (
+        transcript is not None and document.source_transcript_revision != transcript.revision
+    ):
+        raise HTTPException(409, "Документ устарел. Сформируйте его заново.")

```

## backend/app/main.py
```diff
--- before/backend/app/main.py
+++ after/backend/app/main.py
@@ -12,23 +12,25 @@
 from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
 from pydantic import BaseModel, Field
 from sqlalchemy import delete, select, update
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.orm import Session
 
 from .auth import authenticate, create_initial_doctor, decode_token, make_token
 from .config import Settings
 from .db import make_engine, make_session_factory
 from .models import AudioFile, Consultation, ConsultationEdit, DocumentRow, MISExport, TranscriptRow, User, now_utc
-from .schemas import ConsultationData
+from .schemas import ConsultationData, ExtractionResult, TranscriptPatch
+from .grounding import validate_evidence
+from .transcripts import canonical_source, edit_transcript, require_fresh_document, save_initial_transcript
 from .service import (
-    claim_processing, cleanup_expired_audio, consultation_response, document_response,
+    claim_processing, claim_write, cleanup_expired_audio, consultation_response, document_response,
     fail_processing, locked_consultation, require_consultation, require_status, transcript_response,
 )
 
 
 class LoginRequest(BaseModel):
     username: str
     password: str
 
 
 class CreateConsultationRequest(BaseModel):
@@ -62,52 +64,20 @@
         "audio/mp4": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
         "audio/x-m4a": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
         "audio/m4a": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
     }
     valid, extension = signatures.get(media_type, (False, ""))
     if not valid:
         raise HTTPException(415, "Неподдерживаемый аудиофайл")
     return media_type, extension
 
 
-def _transcript_parts(transcript) -> tuple[str, str, float, list]:
-    raw = transcript.model_dump() if hasattr(transcript, "model_dump") else dict(transcript)
-    segments = raw.get("segments", [])
-    text = raw.get("text") or raw.get("raw_text") or "\n".join(segment["text"] for segment in segments)
-    if not text.strip():
-        raise ValueError("empty transcription")
-    return text, raw.get("language") or "ru", float(raw.get("duration_seconds", raw.get("duration", 0))), segments
-
-
-def _save_transcript(session: Session, consultation_id: str, transcript, stt_model: str) -> TranscriptRow:
-    from .normalization import normalize_transcript
-    from .pii import PIIMaskingService
-
-    raw_text, language, duration, segments = _transcript_parts(transcript)
-    normalized = normalize_transcript(raw_text)
-    masked = PIIMaskingService().mask(normalized)
-    entities = [entry.model_dump() if hasattr(entry, "model_dump") else dict(entry) for entry in masked.entities]
-    row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id))
-    if row is None:
-        row = TranscriptRow(consultation_id=consultation_id)
-        session.add(row)
-    row.raw_text = raw_text
-    row.normalized_text = normalized
-    row.masked_text = masked.text
-    row.language = language
-    row.duration_seconds = duration
-    row.stt_model = stt_model
-    row.segments = segments
-    row.pii_entities = entities
-    return row
-
-
 def create_app(settings: Settings | None = None) -> FastAPI:
     settings = settings or Settings.from_env()
     settings.validate()
     engine = make_engine(settings.database_url)
     session_factory = make_session_factory(engine)
 
     @asynccontextmanager
     async def lifespan(app: FastAPI):
         from .providers.demo import DemoLLMProvider
         from .providers.llm import OpenAIProvider
@@ -299,142 +269,156 @@
     async def transcribe(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"CREATED", "RECORDING", "FAILED"})
         audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
         if audio is None:
             raise HTTPException(409, "Сначала загрузите аудио")
         claim_processing(session, item, {"CREATED", "RECORDING", "FAILED"})
         try:
             path = app.state.storage.get(audio.storage_key)
             transcript = await app.state.stt.transcribe(str(path))
-            row = _save_transcript(session, item.id, transcript, settings.whisper_model)
+            row = save_initial_transcript(session, item, transcript, actor_id=user.id, source="stt", stt_model=settings.whisper_model)
             item.status = "TRANSCRIBED"
             item.updated_at = now_utc()
             session.commit()
             return transcript_response(row)
         except Exception:
             session.rollback()
             fail_processing(session, item.id, "Не удалось распознать аудио. Повторите попытку.")
             raise HTTPException(502, "Не удалось распознать аудио") from None
 
     @app.post("/api/v1/consultations/{consultation_id}/demo")
     def demo_transcript(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         if settings.app_mode != "demo":
             raise HTTPException(404, "Недоступно")
         from .providers.demo import DEMO_TRANSCRIPT
 
-        item = locked_consultation(session, consultation_id, user)
-        require_status(item, {"CREATED", "RECORDING", "FAILED"})
-        changed = session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["CREATED", "RECORDING", "FAILED"]))
-                                  .values(status="TRANSCRIBED", updated_at=now_utc(), error_message=None))
-        if changed.rowcount != 1:
-            session.rollback()
-            raise HTTPException(409, "Консультация уже изменена")
-        row = _save_transcript(session, item.id, DEMO_TRANSCRIPT, "demo-fixture")
+        item = require_consultation(session, consultation_id, user)
+        claim_write(session, item, {"CREATED", "RECORDING", "FAILED"})
+        row = save_initial_transcript(session, item, DEMO_TRANSCRIPT, actor_id=user.id, source="demo", stt_model="demo-fixture")
+        item.status = "TRANSCRIBED"
+        item.error_message = None
         session.commit()
         session.refresh(item)
         return transcript_response(row)
 
     @app.get("/api/v1/consultations/{consultation_id}/transcript")
     def get_transcript(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         require_consultation(session, consultation_id, user)
         row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id))
         if row is None:
             raise HTTPException(404, "Транскрипция не найдена")
         return transcript_response(row)
 
+    @app.patch("/api/v1/consultations/{consultation_id}/transcript")
+    def correct_transcript(consultation_id: str, payload: TranscriptPatch, user: User = Depends(current_user), session: Session = Depends(db_session)):
+        item = require_consultation(session, consultation_id, user)
+        row = edit_transcript(session, item, payload, actor_id=user.id)
+        session.commit()
+        return transcript_response(row)
+
     @app.post("/api/v1/consultations/{consultation_id}/generate")
     async def generate_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         from .forms import get_template, validate_template_fields
 
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
         transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id))
         if transcript is None:
             raise HTTPException(409, "Сначала выполните транскрипцию")
         claim_processing(session, item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
         try:
+            session.refresh(transcript)
+            source = canonical_source(transcript)
             template = get_template(item.template_id)
-            result = await app.state.llm.extract_consultation(transcript.masked_text, template_fields=template["fields"])
-            parsed = ConsultationData.model_validate(result)
+            result = await app.state.llm.extract_consultation(source, template_fields=template["fields"])
+            result = ExtractionResult.model_validate(result)
+            evidence = validate_evidence(result, source)
+            parsed = result.data
             if parsed.diagnosis_code is not None:
                 raise ValueError("LLM cannot select a diagnosis code")
             validate_template_fields(item.template_id, parsed)
             payload = parsed.model_dump(mode="json")
             row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
             if row is None:
                 row = DocumentRow(consultation_id=item.id, version=1)
                 session.add(row)
             else:
                 row.version += 1
             row.ai_generated_data = payload
             row.doctor_approved_data = None
             row.working_data = payload
+            row.source_transcript_revision = source.revision
+            row.source_masked_text = source.text
+            row.evidence = [link.model_dump(mode="json") for link in evidence]
             row.llm_provider = settings.effective_llm_provider
             row.llm_model = "demo" if settings.effective_llm_provider == "demo" else settings.openai_model
             row.updated_at = now_utc()
             item.status = "AI_GENERATED"
             item.error_message = None
             item.updated_at = now_utc()
             session.commit()
             return document_response(row)
         except Exception:
             session.rollback()
             fail_processing(session, item.id, "Не удалось сформировать документ. Повторите попытку.")
             raise HTTPException(502, "Не удалось сформировать документ") from None
 
     @app.get("/api/v1/consultations/{consultation_id}/document")
     def get_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         require_consultation(session, consultation_id, user)
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == consultation_id))
         if row is None:
             raise HTTPException(404, "Документ не найден")
+        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         return document_response(row)
 
     @app.get("/api/v1/consultations/{consultation_id}/document.docx")
     def download_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         from .forms import render_docx, validate_template_fields
 
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"APPROVED", "SENT_TO_MIS"})
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
         if row is None or row.doctor_approved_data is None or item.approved_at is None:
             raise HTTPException(409, "Документ не подтверждён")
+        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         try:
             data = ConsultationData.model_validate(row.doctor_approved_data)
             validate_template_fields(item.template_id, data)
             docx = render_docx(item.template_id, data, patient_id=item.external_patient_id,
                                consultation_id=item.id, doctor_name=item.approved_by_name or "Не указан", approved_at=item.approved_at)
         except Exception:
             raise HTTPException(502, "Не удалось подготовить документ") from None
         return Response(
             content=docx,
             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             headers={"Content-Disposition": f'attachment; filename="consultation-{item.id}.docx"'},
         )
 
     @app.patch("/api/v1/consultations/{consultation_id}/document")
     def edit_document(consultation_id: str, payload: EditDocumentRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
         from .forms import validate_template_fields
         from .diagnoses import get_diagnosis
 
-        item = locked_consultation(session, consultation_id, user)
-        require_status(item, {"AI_GENERATED", "REVIEWED"})
+        item = require_consultation(session, consultation_id, user)
+        claim_write(session, item, {"AI_GENERATED", "REVIEWED"})
         try:
             validate_template_fields(item.template_id, payload.data)
         except ValueError:
             raise HTTPException(422, "Некорректные поля шаблона") from None
         if payload.data.diagnosis_code is not None and get_diagnosis(payload.data.diagnosis_code) is None:
             raise HTTPException(422, "Неизвестный код диагноза")
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
         if row is None or row.version != payload.version:
             raise HTTPException(409, "Версия документа устарела")
+        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         data = payload.data.model_dump(mode="json")
         previous_data = row.working_data
         for field, value in data.items():
             if previous_data.get(field) != value:
                 session.add(ConsultationEdit(
                     consultation_id=item.id,
                     field=field,
                     ai_value=row.ai_generated_data.get(field),
                     doctor_value=value,
                     changed=row.ai_generated_data.get(field) != value,
@@ -452,25 +436,26 @@
         )
         if status_change.rowcount != 1:
             session.rollback()
             raise HTTPException(409, "Консультация уже изменена")
         session.commit()
         session.refresh(row)
         return document_response(row)
 
     @app.post("/api/v1/consultations/{consultation_id}/approve")
     def approve(consultation_id: str, payload: VersionRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
-        item = locked_consultation(session, consultation_id, user)
-        require_status(item, {"REVIEWED"})
+        item = require_consultation(session, consultation_id, user)
+        claim_write(session, item, {"REVIEWED"})
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
         if row is None or row.version != payload.version:
             raise HTTPException(409, "Версия документа устарела")
+        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         approved_at = now_utc()
         changed = session.execute(
             update(DocumentRow).where(DocumentRow.id == row.id, DocumentRow.version == payload.version)
             .values(doctor_approved_data=row.working_data, updated_at=approved_at)
         )
         if changed.rowcount != 1:
             session.rollback()
             raise HTTPException(409, "Версия документа устарела")
         status_change = session.execute(
             update(Consultation).where(Consultation.id == item.id, Consultation.status == "REVIEWED")

```

## backend/app/service.py
```diff
--- before/backend/app/service.py
+++ after/backend/app/service.py
@@ -1,66 +1,82 @@
 from __future__ import annotations
 
 from datetime import datetime, timedelta, timezone
 
 from fastapi import HTTPException
 from sqlalchemy import select, update
-from sqlalchemy.orm import Session
+from sqlalchemy.orm import Session, object_session
 
 from .models import AudioFile, Consultation, DocumentRow, TranscriptRow, now_utc
 
 
 def iso(value: datetime | None) -> str | None:
     if value is None:
         return None
     if value.tzinfo is None:
         value = value.replace(tzinfo=timezone.utc)
     return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
 
 
 def consultation_response(item: Consultation) -> dict:
+    session = object_session(item)
+    transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id)) if session else None
+    audio = session.scalar(select(AudioFile.id).where(AudioFile.consultation_id == item.id)) if session else None
     return {
         "id": item.id,
         "external_patient_id": item.external_patient_id,
         "template_id": item.template_id,
         "status": item.status,
         "created_at": iso(item.created_at),
         "updated_at": iso(item.updated_at),
         "approved_at": iso(item.approved_at),
         "error_message": item.error_message,
+        "transcript_revision": transcript.revision if transcript else None,
+        "audio_available": audio is not None,
+        "processing_runs": [],
     }
 
 
 def transcript_response(item: TranscriptRow) -> dict:
+    from .transcripts import canonical_source
+    source = canonical_source(item)
+    session = object_session(item)
+    audio = session.scalar(select(AudioFile.id).where(AudioFile.consultation_id == item.consultation_id)) if session else None
     return {
         "raw_text": item.raw_text,
         "normalized_text": item.normalized_text,
-        "masked_text": item.masked_text,
+        "masked_text": source.text,
         "language": item.language,
         "duration_seconds": item.duration_seconds,
         "stt_model": item.stt_model,
         "segments": item.segments,
-        "pii_entities": item.pii_entities,
+        "pii_entities": [entity.model_dump(mode="json") for entity in source.entities],
+        "revision": item.revision,
+        "current_text": "\n".join(segment["text"] for segment in item.segments),
+        "audio_available": audio is not None,
     }
 
 
 def document_response(item: DocumentRow) -> dict:
     return {
         "id": item.id,
         "consultation_id": item.consultation_id,
         "ai_generated_data": item.ai_generated_data,
         "doctor_approved_data": item.doctor_approved_data,
         "data": item.working_data,
         "llm_provider": item.llm_provider,
         "llm_model": item.llm_model,
         "updated_at": iso(item.updated_at),
         "version": item.version,
+        "source_transcript_revision": item.source_transcript_revision,
+        "source_masked_text": item.source_masked_text,
+        "evidence": item.evidence,
     }
 
 
 def require_consultation(session: Session, consultation_id: str, user) -> Consultation:
     item = session.get(Consultation, consultation_id)
     if item is None or (item.created_by != user.id and user.role != "admin"):
         raise HTTPException(404, "Консультация не найдена")
     return item
 
 
@@ -69,30 +85,51 @@
     if item is None or (item.created_by != user.id and user.role != "admin"):
         raise HTTPException(404, "Консультация не найдена")
     return item
 
 
 def require_status(item: Consultation, allowed: set[str]) -> None:
     if item.status not in allowed:
         raise HTTPException(409, "Действие недоступно в текущем статусе")
 
 
-def claim_processing(session: Session, item: Consultation, allowed: set[str]) -> None:
-    result = session.execute(
-        update(Consultation)
-        .where(Consultation.id == item.id, Consultation.status.in_(allowed))
-        .values(status="PROCESSING", updated_at=now_utc(), error_message=None)
+def claim_write(session: Session, item: Consultation, allowed: set[str], *, expected_revision: int | None = None, processing: bool = False) -> None:
+    """CAS the observed consultation before touching children on either database.
+
+    UPDATE takes a write lock on SQLite and a retained row lock on PostgreSQL.
+    The timestamp predicate also detects competing writes that retain status.
+    Expire identity-map state only after winning: expire_on_commit is disabled.
+    """
+    statement = update(Consultation).where(
+        Consultation.id == item.id, Consultation.updated_at == item.updated_at,
+        Consultation.status.in_(allowed),
     )
+    if expected_revision is not None:
+        statement = statement.where(select(TranscriptRow.id).where(
+            TranscriptRow.consultation_id == item.id, TranscriptRow.revision == expected_revision,
+        ).exists())
+    values = {"updated_at": now_utc()}
+    if processing:
+        values.update(status="PROCESSING", error_message=None)
+    result = session.execute(statement.values(**values).execution_options(synchronize_session=False))
     if result.rowcount != 1:
         session.rollback()
-        raise HTTPException(409, "Консультация уже обрабатывается")
+        raise HTTPException(409, "Консультация уже изменена")
+    session.expire_all()
+    session.refresh(item, with_for_update=True)
+
+
+def claim_processing(session: Session, item: Consultation, allowed: set[str]) -> None:
+    claim_write(session, item, allowed, processing=True)
     session.commit()
+    session.expire_all()
+    session.refresh(item)
 
 
 def fail_processing(session: Session, consultation_id: str, message: str) -> None:
     session.execute(
         update(Consultation)
         .where(Consultation.id == consultation_id, Consultation.status == "PROCESSING")
         .values(status="FAILED", error_message=message, updated_at=now_utc())
     )
     session.commit()
 

```

## backend/tests/test_transcript_revisions.py
```diff
--- before/backend/tests/test_transcript_revisions.py
+++ after/backend/tests/test_transcript_revisions.py
@@ -0,0 +1,290 @@
+from concurrent.futures import ThreadPoolExecutor
+from threading import Barrier
+import os
+
+import pytest
+from fastapi.testclient import TestClient
+from sqlalchemy import select
+
+from app.models import Consultation, DocumentRow, TranscriptRevisionRow, TranscriptRow
+from test_api import client as sqlite_client, consultation, login as api_login
+
+
+def login(client):
+    return api_login(client, password="revision-test" if client.app.state.settings.database_url.startswith("postgresql") else "demo-doctor")
+
+
+@pytest.fixture(params=["sqlite", "postgresql"])
+def client(request, sqlite_client, tmp_path):
+    if request.param == "sqlite":
+        yield sqlite_client
+        return
+    url = os.environ.get("MEDHUB_P0_REVISION_DATABASE_URL")
+    if not url:
+        pytest.skip("Dedicated disposable PostgreSQL URL not supplied")
+    from app.config import Settings
+    from app.auth import password_hash
+    from app.db import Base, make_engine
+    from app.main import create_app
+    engine = make_engine(url)
+    # The explicit task database is disposable; never accept the configured live URL.
+    assert engine.url.database == "medhub_p0_task4_20260930"
+    Base.metadata.create_all(engine)
+    with engine.begin() as connection:
+        for table in reversed(Base.metadata.sorted_tables):
+            connection.execute(table.delete())
+    engine.dispose()
+    settings = Settings(app_mode="live", database_url=url, audio_storage_dir=tmp_path / "pg-audio",
+                        jwt_secret="test-only-secret-with-enough-length-123456",
+                        doctor_password_hash=password_hash.hash("revision-test"),
+                        openai_api_key="synthetic-test-key")
+    # Startup must avoid demo migration; after startup enable synthetic fixture routes.
+    with TestClient(create_app(settings)) as pg_client:
+        from app.providers.demo import DemoLLMProvider
+        settings.app_mode = "demo"
+        pg_client.app.state.llm = DemoLLMProvider()
+        yield pg_client
+
+
+def prepared(client, *, generate=False, review=False):
+    headers = login(client)
+    item = consultation(client, headers)
+    prefix = f"/api/v1/consultations/{item['id']}"
+    response = client.post(prefix + "/demo", headers=headers)
+    assert response.status_code == 200
+    transcript = response.json()
+    doc = None
+    if generate or review:
+        response = client.post(prefix + "/generate", headers=headers)
+        assert response.status_code == 200, response.text
+        doc = response.json()
+    if review:
+        response = client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]})
+        assert response.status_code == 200
+        doc = response.json()
+    return headers, item["id"], prefix, transcript, doc
+
+
+def patch(transcript, text="Телефон 87011234567. Кашель пять дней."):
+    return {"expected_revision": transcript.get("revision", 1), "changes": [{"segment_id": transcript["segments"][0].get("id", "seg-000001"), "text": text}]}
+
+
+def test_edit_preserves_original_and_invalidates_document(client):
+    headers, cid, prefix, original, doc = prepared(client, review=True)
+    response = client.patch(prefix + "/transcript", headers=headers, json=patch(original))
+    assert response.status_code == 200, response.text
+    current = response.json()
+    assert current["revision"] == original["revision"] + 1
+    assert current["raw_text"] == original["raw_text"]
+    assert [(s["id"], s["start"], s["end"]) for s in current["segments"]] == [(s["id"], s["start"], s["end"]) for s in original["segments"]]
+    assert "87011234567" not in current["masked_text"]
+    assert "87011234567" in current["current_text"]
+    assert client.get(prefix, headers=headers).json()["status"] == "TRANSCRIBED"
+    assert client.get(prefix + "/document", headers=headers).status_code == 409
+    assert client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]}).status_code == 409
+    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 409
+    with client.app.state.session_factory() as session:
+        row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
+        revisions = session.scalars(select(TranscriptRevisionRow).where(TranscriptRevisionRow.transcript_id == row.id).order_by(TranscriptRevisionRow.revision)).all()
+        assert [r.revision for r in revisions] == [1, 2]
+        assert revisions[1].actor_id == session.get(Consultation, cid).created_by
+        assert revisions[1].source == "doctor"
+        assert revisions[0].segments == original["segments"]
+        stored = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
+        assert stored.working_data == doc["data"]
+        assert stored.evidence == doc["evidence"]
+    from app.schemas import ConsultationData, EvidenceClaim, ExtractionResult
+    class CorrectedSourceLLM:
+        async def extract_consultation(self, source, *, template_fields=None, on_stage=None):
+            return ExtractionResult(data=ConsultationData(complaints=["Кашель пять дней"]), evidence=[
+                EvidenceClaim(field_path="complaints/0", segment_id=source.segments[0].id, quote="Кашель пять дней")
+            ])
+    client.app.state.llm = CorrectedSourceLLM()
+    regenerated = client.post(prefix + "/generate", headers=headers)
+    assert regenerated.status_code == 200, regenerated.text
+    assert regenerated.json()["version"] == doc["version"] + 1
+    assert regenerated.json()["source_transcript_revision"] == 2
+    assert regenerated.json()["source_masked_text"] == current["masked_text"]
+    assert client.post(prefix + "/approve", headers=headers, json={"version": regenerated.json()["version"]}).status_code == 409
+
+
+def test_noop_edit_does_not_invalidate(client):
+    headers, cid, prefix, transcript, doc = prepared(client, review=True)
+    response = client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, transcript["segments"][0]["text"]))
+    assert response.status_code == 200
+    assert response.json() == transcript
+    assert client.get(prefix, headers=headers).json()["status"] == "REVIEWED"
+    assert client.get(prefix + "/document", headers=headers).json() == doc
+
+
+@pytest.mark.parametrize("state", ["APPROVED", "SENT_TO_MIS", "PROCESSING", "CREATED", "RECORDING"])
+def test_approved_and_processing_transcripts_are_locked(client, state):
+    headers, cid, prefix, transcript, _ = prepared(client)
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = state
+        session.commit()
+    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 409
+
+
+@pytest.mark.parametrize("changes", [[{"segment_id": "unknown", "text": "x"}], [{"segment_id": "seg-000001", "text": "x"}] * 2, [{"segment_id": "seg-000001", "text": "x", "start": 8}]])
+def test_invalid_segment_edits_do_not_create_snapshots(client, changes):
+    headers, cid, prefix, transcript, _ = prepared(client)
+    response = client.patch(prefix + "/transcript", headers=headers, json={"expected_revision": 1, "changes": changes})
+    assert response.status_code == 422
+    with client.app.state.session_factory() as session:
+        assert session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid)).revision == 1
+        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 1
+
+
+def test_competing_transcript_edits_have_one_winner(client):
+    headers, cid, prefix, transcript, _ = prepared(client)
+    barrier = Barrier(2)
+    def edit(text):
+        barrier.wait(timeout=10)
+        return client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, text)).status_code
+    with ThreadPoolExecutor(2) as pool:
+        codes = list(pool.map(edit, ["Кашель пять дней", "Кашель десять дней"]))
+    assert sorted(codes) == [200, 409]
+    current = client.get(prefix + "/transcript", headers=headers).json()
+    assert current["revision"] == 2
+    assert current["raw_text"] == transcript["raw_text"]
+
+
+@pytest.mark.parametrize("operation", ["generate", "save", "approve"])
+def test_edit_races_with_generation_save_and_approval(client, monkeypatch, operation):
+    import app.main as main
+    headers, cid, prefix, transcript, doc = prepared(client, generate=True, review=operation == "approve")
+    barrier = Barrier(2)
+    original = main.require_consultation
+    def synchronized_read(*args, **kwargs):
+        item = original(*args, **kwargs)
+        barrier.wait(timeout=10)
+        return item
+    monkeypatch.setattr(main, "require_consultation", synchronized_read)
+    # Separate request event loops permit a real overlap even for async generation.
+    edit_client = TestClient(client.app)
+    document_client = TestClient(client.app)
+    def write_document():
+        if operation == "generate":
+            return document_client.post(prefix + "/generate", headers=headers)
+        if operation == "approve":
+            return document_client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]})
+        return document_client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]})
+    with ThreadPoolExecutor(2) as pool:
+        edit = pool.submit(edit_client.patch, prefix + "/transcript", headers=headers, json=patch(transcript))
+        write = pool.submit(write_document)
+        responses = [edit.result(timeout=20), write.result(timeout=20)]
+    monkeypatch.setattr(main, "require_consultation", original)
+    assert sorted(r.status_code for r in responses) == [200, 409]
+    if responses[0].status_code == 200:
+        assert client.get(prefix + "/document", headers=headers).status_code == 409
+        assert client.get(prefix, headers=headers).json()["status"] == "TRANSCRIBED"
+
+
+def test_stt_retry_appends_revision_without_replacing_original(client, monkeypatch):
+    import app.providers.demo as demo
+    from app.schemas import Transcript, TranscriptSegment
+    headers, cid, prefix, transcript, _ = prepared(client)
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "FAILED"
+        session.commit()
+    monkeypatch.setattr(demo, "DEMO_TRANSCRIPT", Transcript(language="ru", duration=2, segments=[
+        TranscriptSegment(start=0, end=2, text="Повторное распознавание: кашель неделю.")
+    ]))
+    response = client.post(prefix + "/demo", headers=headers)
+    assert response.status_code == 200
+    assert response.json()["revision"] == 2
+    assert response.json()["raw_text"] == transcript["raw_text"]
+    assert response.json()["current_text"] == "Повторное распознавание: кашель неделю."
+    with client.app.state.session_factory() as session:
+        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 2
+
+
+def test_another_doctor_cannot_read_or_correct_transcript(client):
+    from app.auth import make_token, password_hash
+    from app.models import User
+    headers, _, prefix, transcript, _ = prepared(client)
+    with client.app.state.session_factory() as session:
+        other = User(username="other", password_hash=password_hash.hash("test"), role="doctor", display_name="Other")
+        session.add(other)
+        session.commit()
+        headers = {"Authorization": "Bearer " + make_token(other, client.app.state.settings.jwt_secret)}
+    assert client.get(prefix + "/transcript", headers=headers).status_code == 404
+    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 404
+
+
+def test_freshness_does_not_depend_on_lifecycle_status(client):
+    headers, cid, prefix, transcript, doc = prepared(client, review=True)
+    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 200
+    # A legacy/manual status change must not revive stale clinical data.
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "REVIEWED"
+        session.commit()
+    assert client.get(prefix + "/document", headers=headers).status_code == 409
+    assert client.patch(prefix + "/document", headers=headers, json={"version": doc["version"], "data": doc["data"]}).status_code == 409
+    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 409
+
+
+@pytest.mark.parametrize("text_value", ["", " \n\t"])
+def test_final_transcript_cannot_be_blank(client, text_value):
+    headers, _, prefix, transcript, _ = prepared(client)
+    assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript, text_value)).status_code == 422
+    assert client.get(prefix + "/transcript", headers=headers).json()["revision"] == 1
+
+
+def test_combined_limit_includes_unchanged_segments(client):
+    headers, cid, prefix, transcript, _ = prepared(client)
+    with client.app.state.session_factory() as session:
+        row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
+        row.segments = [{"id": f"seg-{i:06d}", "start": i, "end": i + 1, "text": "a" * 19000} for i in range(1, 27)]
+        row.segments += [{"id": "seg-000027", "start": 27, "end": 28, "text": "x"}]
+        session.commit()
+    response = client.patch(prefix + "/transcript", headers=headers, json={"expected_revision": 1, "changes": [{"segment_id": "seg-000027", "text": "b" * 10000}]})
+    assert response.status_code == 422
+    with client.app.state.session_factory() as session:
+        assert session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid)).revision == 1
+        assert len(session.scalars(select(TranscriptRevisionRow)).all()) == 1
+
+
+def test_failed_without_transcript_cannot_be_edited(client):
+    headers = login(client)
+    cid = consultation(client, headers)["id"]
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "FAILED"
+        session.commit()
+    response = client.patch(f"/api/v1/consultations/{cid}/transcript", headers=headers, json={"expected_revision": 1, "changes": [{"segment_id": "seg-000001", "text": "x"}]})
+    assert response.status_code == 409
+
+
+def test_processing_gate_expires_previously_loaded_transcript(client):
+    from app.service import claim_processing
+    headers, cid, prefix, transcript, _ = prepared(client)
+    with client.app.state.session_factory() as first:
+        cached = first.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == cid))
+        first.commit()  # Explicitly retain the cached row (expire_on_commit=False).
+        assert client.patch(prefix + "/transcript", headers=headers, json=patch(transcript)).status_code == 200
+        item = first.get(Consultation, cid)
+        assert cached.revision == 1
+        claim_processing(first, item, {"TRANSCRIBED"})
+        assert cached.revision == 2
+        assert "Кашель пять дней" in cached.normalized_text
+
+
+def test_approved_legacy_document_without_transcript_remains_exportable(client):
+    from app.models import now_utc
+    from app.schemas import ConsultationData
+    headers = login(client)
+    cid = consultation(client, headers)["id"]
+    with client.app.state.session_factory() as session:
+        item = session.get(Consultation, cid)
+        item.status = "APPROVED"
+        item.approved_at = now_utc()
+        payload = ConsultationData(complaints=["Синтетическая архивная запись"]).model_dump(mode="json")
+        session.add(DocumentRow(consultation_id=cid, ai_generated_data=payload, working_data=payload,
+                                doctor_approved_data=payload, llm_provider="legacy", llm_model="unknown"))
+        session.commit()
+    response = client.get(f"/api/v1/consultations/{cid}/document", headers=headers)
+    assert response.status_code == 200
+    assert response.json()["source_transcript_revision"] is None
+    assert response.json()["source_masked_text"] is None
+    assert client.get(f"/api/v1/consultations/{cid}/document.docx", headers=headers).status_code == 200

```

## backend/tests/test_api.py
```diff
--- before/backend/tests/test_api.py
+++ after/backend/tests/test_api.py
@@ -4,21 +4,21 @@
 
 import pytest
 from fastapi.testclient import TestClient
 from sqlalchemy import text
 
 from app.main import create_app
 from app.config import Settings
 from app.auth import make_token, password_hash
 from app.models import AudioFile, Consultation, MISExport, User, now_utc
 from app.service import cleanup_expired_audio
-from app.schemas import ConsultationData, TemplateFieldValue, Transcript, TranscriptSegment
+from app.schemas import ConsultationData, ExtractionResult, TemplateFieldValue, Transcript, TranscriptSegment
 from datetime import timedelta
 
 
 @pytest.fixture
 def client(tmp_path: Path):
     settings = Settings(
         app_mode="demo",
         database_url=f"sqlite:///{tmp_path / 'test.db'}",
         jwt_secret="test-only-secret-with-enough-length-123456",
         audio_storage_dir=tmp_path / "audio",
@@ -147,23 +147,23 @@
 def test_generation_passes_selected_catalog_and_rejects_out_of_template_output(client):
     headers = login(client)
     created = client.post("/api/v1/consultations", headers=headers,
                           json={"external_patient_id": "SYN-1028", "template_id": "cardiologist"}).json()
     prefix = f"/api/v1/consultations/{created['id']}"
     assert client.post(prefix + "/demo", headers=headers).status_code == 200
 
     class InvalidFieldLLM:
         fields = None
 
-        async def extract_consultation(self, transcript, *, template_fields=None):
+        async def extract_consultation(self, transcript, *, template_fields=None, on_stage=None):
             self.fields = template_fields
-            return ConsultationData(template_fields=[TemplateFieldValue(key="outside_form", value="X")])
+            return ExtractionResult(data=ConsultationData(template_fields=[TemplateFieldValue(key="outside_form", value="X")]))
 
     llm = InvalidFieldLLM()
     client.app.state.llm = llm
     result = client.post(prefix + "/generate", headers=headers)
     assert result.status_code == 502
     assert "outside_form" not in result.text
     assert client.get(prefix + "/document", headers=headers).status_code == 404
     assert client.get(prefix, headers=headers).json()["status"] == "FAILED"
     assert llm.fields and any(field.get("clinical_field") for field in llm.fields)
     assert any(not field.get("clinical_field") for field in llm.fields)
@@ -434,23 +434,23 @@
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
-        async def extract_consultation(self, transcript, *, template_fields=None):
-            self.input_text = transcript
-            return ConsultationData(complaints=["Кашель три дня"])
+        async def extract_consultation(self, transcript, *, template_fields=None, on_stage=None):
+            self.input_text = transcript.text
+            return ExtractionResult(data=ConsultationData(complaints=["Кашель три дня"]))
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

```

## backend/tests/test_runtime_llm.py
```diff
--- before/backend/tests/test_runtime_llm.py
+++ after/backend/tests/test_runtime_llm.py
@@ -1,19 +1,19 @@
 from pathlib import Path
 
 import pytest
 from fastapi.testclient import TestClient
 
 from app.config import Settings
 from app.main import create_app
 from app.providers.llm import OpenAIProvider
-from app.schemas import ConsultationData
+from app.schemas import ConsultationData, ExtractionResult
 
 
 def test_explicit_openai_selection_from_environment(monkeypatch):
     monkeypatch.setenv("APP_MODE", "demo")
     monkeypatch.setenv("LLM_PROVIDER", "openai")
     monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
     settings = Settings.from_env()
     settings.validate()
     assert settings.effective_llm_provider == "openai"
 
@@ -30,22 +30,22 @@
 
 def test_live_does_not_allow_demo_llm():
     with pytest.raises(ValueError, match="LLM_PROVIDER"):
         Settings(app_mode="live", llm_provider="demo").validate()
 
 
 @pytest.mark.parametrize("provider,expected", [("auto", "demo"), ("openai", "openai")])
 def test_demo_login_and_actual_document_provider_are_independent(tmp_path: Path, monkeypatch, provider, expected):
     # Only the external operation is replaced; startup, selection, auth,
     # document persistence and response metadata all execute normally.
-    async def extract(self, transcript, *, template_fields=None):
-        return ConsultationData(complaints=["synthetic OpenAI response"])
+    async def extract(self, transcript, *, template_fields=None, on_stage=None):
+        return ExtractionResult(data=ConsultationData(complaints=["synthetic OpenAI response"]))
 
     monkeypatch.setattr(OpenAIProvider, "extract_consultation", extract)
     settings = Settings(
         app_mode="demo", llm_provider=provider, openai_api_key="synthetic-key",
         database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
         audio_storage_dir=tmp_path / "audio",
     )
     with TestClient(create_app(settings)) as client:
         health = client.get("/api/v1/health").json()
         assert health["mode"] == "demo"

```

