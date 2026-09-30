# Task5 implementation review package

Base after Task4; no Git. Read task-5-brief.md, context.md, task-5-report.md, task-reviewer-prompt.md. Scope ONLY processing/protected files; no source raw identifiers in telemetry, ownership/approval and revision guards preserved. Implementer p0_revisions; reviewer must be distinct. Full-suite report explicitly separates concurrent Task9 harness failures from own tests. Final integration run required later. Package assembled on reported Task5 freeze.

## backend/app/processing.py
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ backend/app/processing.py	2026-09-30 14:40:34.566635877 +0500
@@ -0,0 +1,139 @@
+"""Measured operational stages; never store provider input or exception text."""
+from __future__ import annotations
+
+from copy import deepcopy
+from time import monotonic_ns
+
+from sqlalchemy import select
+from sqlalchemy.orm import Session
+
+from .models import Consultation, ProcessingRunRow, now_utc
+from .schemas import ProcessingStage
+
+
+STAGES = {"upload": ("upload",), "transcribe": ("stt", "normalization", "pii_masking"),
+          "generate": ("llm_extraction", "output_validation")}
+ERRORS = {"upload": "UPLOAD_FAILED", "stt": "STT_FAILED", "normalization": "NORMALIZATION_FAILED",
+          "pii_masking": "MASKING_FAILED", "llm_extraction": "LLM_FAILED", "output_validation": "VALIDATION_FAILED"}
+SAFE_CODES = {*ERRORS.values(), "INTERRUPTED"}
+
+
+class ProcessingTracker:
+    def __init__(self, session_factory, consultation_id: str, operation: str):
+        if operation not in STAGES:
+            raise ValueError("Unknown operation")
+        self.session_factory = session_factory
+        self.consultation_id = consultation_id
+        self.operation = operation
+        self.run_id: str | None = None
+        self._started: dict[tuple[str, int], int] = {}
+        self._attempts: dict[str, int] = {}
+        self._active: str | None = None
+
+    def start(self) -> str:
+        if self.run_id is not None:
+            raise ValueError("Run already started")
+        with self.session_factory() as session:
+            row = ProcessingRunRow(consultation_id=self.consultation_id, operation=self.operation, status="running",
+                stages=[ProcessingStage(key=key, attempt=1, status="pending").model_dump(mode="json") for key in STAGES[self.operation]])
+            session.add(row)
+            session.commit()
+            self.run_id = row.id
+        return self.run_id
+
+    def latest_attempt(self, key: str) -> int:
+        return self._attempts.get(key, 1)
+
+    def failure_code(self, fallback: str) -> str:
+        return ERRORS.get(self._active, fallback)
+
+    def stage(self, key: str, state: str, attempt: int = 1) -> None:
+        if key not in STAGES[self.operation] or state not in {"running", "done", "error"} or attempt < 1:
+            raise ValueError("Invalid processing stage")
+        if self.run_id is None:
+            raise ValueError("Run not started")
+        with self.session_factory() as session:
+            row = session.get(ProcessingRunRow, self.run_id)
+            if row.status != "running":
+                raise ValueError("Run is terminal")
+            stages = deepcopy(row.stages)
+            stage = next((s for s in stages if s["key"] == key and s["attempt"] == attempt), None)
+            if stage is None:
+                if state != "running":
+                    raise ValueError("Stage was not started")
+                stage = ProcessingStage(key=key, attempt=attempt, status="pending").model_dump(mode="json")
+                stages.append(stage)
+            if stage["status"] == state:
+                return
+            timestamp = now_utc().isoformat()
+            if state == "running":
+                if stage["status"] != "pending":
+                    raise ValueError("Stage is terminal")
+                self._started[key, attempt] = monotonic_ns()
+                self._attempts[key] = attempt
+                self._active = key
+                stage.update(status=state, started_at=timestamp)
+            else:
+                if stage["status"] != "running":
+                    raise ValueError("Stage was not started")
+                elapsed = max(0, (monotonic_ns() - self._started[key, attempt]) // 1_000_000)
+                stage.update(status=state, finished_at=timestamp, duration_ms=elapsed,
+                             error_code=ERRORS[key] if state == "error" else None)
+                if state == "error":
+                    self._active = key
+            row.stages = stages
+            session.commit()
+
+    def _terminal(self, session: Session, state: str, error_code: str | None = None) -> None:
+        if self.run_id is None:
+            return
+        row = session.get(ProcessingRunRow, self.run_id)
+        stages = deepcopy(row.stages)
+        at = now_utc()
+        if state == "error":
+            for stage in stages:
+                if stage["status"] == "running":
+                    start = self._started.get((stage["key"], stage["attempt"]))
+                    stage.update(status="error", error_code=error_code, finished_at=at.isoformat(),
+                                 duration_ms=max(0, (monotonic_ns() - start) // 1_000_000) if start is not None else None)
+        row.stages = stages
+        row.status = state
+        row.finished_at = at
+
+    def finish(self, *, session: Session | None = None) -> None:
+        """Optional caller session makes terminal telemetry and clinical save atomic."""
+        if session is not None:
+            self._terminal(session, "done")
+            return
+        with self.session_factory() as owned:
+            self._terminal(owned, "done")
+            owned.commit()
+
+    def fail(self, error_code: str, *, session: Session | None = None) -> None:
+        if error_code not in SAFE_CODES:
+            raise ValueError("Unknown processing error code")
+        if session is not None:
+            self._terminal(session, "error", error_code)
+            return
+        with self.session_factory() as owned:
+            self._terminal(owned, "error", error_code)
+            owned.commit()
+
+
+def recover_interrupted_runs(session: Session) -> int:
+    rows = session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.status == "running")).all()
+    at = now_utc()
+    for row in rows:
+        stages = deepcopy(row.stages)
+        for stage in stages:
+            if stage["status"] == "running":
+                stage.update(status="error", error_code="INTERRUPTED", finished_at=at.isoformat(), duration_ms=None)
+        row.stages = stages
+        row.status = "error"
+        row.finished_at = at
+        consultation = session.get(Consultation, row.consultation_id)
+        if consultation.status == "PROCESSING":
+            consultation.status = "FAILED"
+            consultation.error_message = "Обработка прервана. Повторите действие."
+            consultation.updated_at = at
+    return len(rows)

```

## backend/app/main.py
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-5-base/backend/app/main.py	2026-09-30 14:31:08.590951220 +0500
+++ backend/app/main.py	2026-09-30 14:43:28.752924721 +0500
@@ -1,37 +1,41 @@
 from __future__ import annotations
 
 import asyncio
 import contextlib
+import os
+import stat
 from contextlib import asynccontextmanager
 from pathlib import Path
 
 from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
 from fastapi.exceptions import RequestValidationError
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.responses import JSONResponse, Response
 from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
 from pydantic import BaseModel, Field
 from sqlalchemy import delete, select, update
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.orm import Session
+from starlette.concurrency import run_in_threadpool
 
 from .auth import authenticate, create_initial_doctor, decode_token, make_token
 from .config import Settings
 from .db import make_engine, make_session_factory
 from .models import AudioFile, Consultation, ConsultationEdit, DocumentRow, MISExport, TranscriptRow, User, now_utc
 from .schemas import ConsultationData, ExtractionResult, TranscriptPatch
 from .grounding import validate_evidence
 from .transcripts import canonical_source, edit_transcript, require_fresh_document, save_initial_transcript
+from .processing import ProcessingTracker, recover_interrupted_runs
 from .service import (
-    claim_processing, claim_write, cleanup_expired_audio, consultation_response, document_response,
-    fail_processing, locked_consultation, require_consultation, require_status, transcript_response,
+    available_audio, claim_processing, claim_write, cleanup_expired_audio, consultation_response as _consultation_response, document_response,
+    fail_processing, locked_consultation, require_consultation, require_status, transcript_response as _transcript_response,
 )
 
 
 class LoginRequest(BaseModel):
     username: str
     password: str
 
 
 class CreateConsultationRequest(BaseModel):
     external_patient_id: str = Field(min_length=1, max_length=200)
@@ -91,20 +95,21 @@
             from alembic import command
             from alembic.config import Config
 
             backend_dir = Path(__file__).resolve().parents[1]
             migration_config = Config(str(backend_dir / "alembic.ini"))
             migration_config.set_main_option("script_location", str(backend_dir / "alembic"))
             migration_config.attributes["database_url"] = settings.database_url
             command.upgrade(migration_config, "head")
         with session_factory() as session:
             create_initial_doctor(session, settings)
+            recover_interrupted_runs(session)
             session.execute(
                 update(Consultation)
                 .where(Consultation.status == "PROCESSING")
                 .values(status="FAILED", error_message="Обработка прервана. Повторите действие.", updated_at=now_utc())
             )
             # Only the local mock has no external side effect to reconcile after a crash.
             session.execute(
                 delete(MISExport).where(
                     MISExport.provider == "mock",
                     MISExport.success.is_(False),
@@ -140,20 +145,33 @@
             task.cancel()
             with contextlib.suppress(asyncio.CancelledError):
                 await task
             engine.dispose()
 
     app = FastAPI(title="AI Medical Scribe", lifespan=lifespan)
     app.state.settings = settings
     app.state.session_factory = session_factory
     app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
 
+    def consultation_response(item):
+        return _consultation_response(item, storage=app.state.storage, retention_days=settings.audio_retention_days)
+
+    def transcript_response(item):
+        return _transcript_response(item, storage=app.state.storage, retention_days=settings.audio_retention_days)
+
+    def processing_failed(session, item, tracker, message, code):
+        session.rollback()
+        tracker.fail(tracker.failure_code(code), session=session)
+        session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status == "PROCESSING")
+                        .values(status="FAILED", error_message=message, updated_at=now_utc()))
+        session.commit()
+
     @app.exception_handler(RequestValidationError)
     async def validation_error(_request: Request, _error: RequestValidationError):
         return JSONResponse(status_code=422, content={"detail": "Некорректные данные запроса"})
 
     def db_session():
         with session_factory() as session:
             yield session
 
     def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(db_session)) -> User:
         if credentials is None:
@@ -228,70 +246,97 @@
                                   .values(status="RECORDING", updated_at=now_utc()))
         if changed.rowcount != 1:
             session.rollback()
             raise HTTPException(409, "Консультация уже изменена")
         session.commit()
         session.refresh(item)
         return consultation_response(item)
 
     @app.post("/api/v1/consultations/{consultation_id}/audio")
     async def upload_audio(consultation_id: str, file: UploadFile = File(...), user: User = Depends(current_user), session: Session = Depends(db_session)):
-        item = locked_consultation(session, consultation_id, user)
-        require_status(item, {"CREATED", "RECORDING", "FAILED"})
-        changed = session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["CREATED", "RECORDING", "FAILED"]))
-                                  .values(updated_at=now_utc()))
-        if changed.rowcount != 1:
-            session.rollback()
-            raise HTTPException(409, "Консультация уже изменена")
-        max_bytes = settings.max_upload_mb * 1024 * 1024
-        data = await file.read(max_bytes + 1)
-        if len(data) > max_bytes:
-            raise HTTPException(413, "Аудиофайл слишком большой")
-        media_type, extension = _sniff_audio(file.content_type or "", data)
-        key = f"{item.id}.{extension}"
-        app.state.storage.save(key, data)
-        previous = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
-        if previous is None:
-            previous = AudioFile(consultation_id=item.id)
-            session.add(previous)
-        elif previous.storage_key != key:
-            app.state.storage.delete(previous.storage_key)
-        previous.storage_key = key
-        previous.content_type = media_type
-        previous.size_bytes = len(data)
-        previous.created_at = now_utc()
-        item.status = "RECORDING"
-        item.error_message = None
-        item.updated_at = now_utc()
-        session.commit()
+        item = require_consultation(session, consultation_id, user)
+        claim_processing(session, item, {"CREATED", "RECORDING", "FAILED"})
+        tracker = ProcessingTracker(session_factory, item.id, "upload")
+        try:
+            tracker.start()
+            tracker.stage("upload", "running")
+            max_bytes = settings.max_upload_mb * 1024 * 1024
+            data = await file.read(max_bytes + 1)
+            if len(data) > max_bytes:
+                raise HTTPException(413, "Аудиофайл слишком большой")
+            media_type, extension = _sniff_audio(file.content_type or "", data)
+            key = f"{item.id}.{extension}"
+            await run_in_threadpool(app.state.storage.save, key, data)
+            previous = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
+            if previous is not None and previous.storage_key != key:
+                await run_in_threadpool(app.state.storage.delete, previous.storage_key)
+            tracker.stage("upload", "done")
+            if previous is None:
+                previous = AudioFile(consultation_id=item.id)
+                session.add(previous)
+            previous.storage_key = key
+            previous.content_type = media_type
+            previous.size_bytes = len(data)
+            previous.created_at = now_utc()
+            item.status = "RECORDING"
+            item.error_message = None
+            item.updated_at = now_utc()
+            tracker.finish(session=session)
+            session.commit()
+        except Exception as error:
+            processing_failed(session, item, tracker, "Не удалось загрузить аудио. Повторите попытку.", "UPLOAD_FAILED")
+            if isinstance(error, HTTPException):
+                raise
+            raise HTTPException(502, "Не удалось загрузить аудио") from None
         return consultation_response(item)
 
+    @app.get("/api/v1/consultations/{consultation_id}/audio")
+    def download_audio(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
+        require_consultation(session, consultation_id, user)
+        result = available_audio(session, consultation_id, app.state.storage, settings.audio_retention_days)
+        if result is None:
+            raise HTTPException(404, "Аудиозапись недоступна")
+        audio, path = result
+        try:
+            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
+            with os.fdopen(descriptor, "rb") as source:
+                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
+                    raise OSError("Audio is not a regular file")
+                content = source.read()
+        except OSError:
+            raise HTTPException(404, "Аудиозапись недоступна") from None
+        return Response(content, media_type=audio.content_type, headers={"Cache-Control": "no-store"})
+
     @app.post("/api/v1/consultations/{consultation_id}/transcribe")
     async def transcribe(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"CREATED", "RECORDING", "FAILED"})
         audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
         if audio is None:
             raise HTTPException(409, "Сначала загрузите аудио")
         claim_processing(session, item, {"CREATED", "RECORDING", "FAILED"})
+        tracker = ProcessingTracker(session_factory, item.id, "transcribe")
         try:
+            tracker.start()
+            tracker.stage("stt", "running")
             path = app.state.storage.get(audio.storage_key)
             transcript = await app.state.stt.transcribe(str(path))
-            row = save_initial_transcript(session, item, transcript, actor_id=user.id, source="stt", stt_model=settings.whisper_model)
+            tracker.stage("stt", "done")
+            row = save_initial_transcript(session, item, transcript, actor_id=user.id, source="stt", stt_model=settings.whisper_model, on_stage=tracker.stage)
             item.status = "TRANSCRIBED"
             item.updated_at = now_utc()
+            tracker.finish(session=session)
             session.commit()
-            return transcript_response(row)
         except Exception:
-            session.rollback()
-            fail_processing(session, item.id, "Не удалось распознать аудио. Повторите попытку.")
+            processing_failed(session, item, tracker, "Не удалось распознать аудио. Повторите попытку.", "STT_FAILED")
             raise HTTPException(502, "Не удалось распознать аудио") from None
+        return transcript_response(row)
 
     @app.post("/api/v1/consultations/{consultation_id}/demo")
     def demo_transcript(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         if settings.app_mode != "demo":
             raise HTTPException(404, "Недоступно")
         from .providers.demo import DEMO_TRANSCRIPT
 
         item = require_consultation(session, consultation_id, user)
         claim_write(session, item, {"CREATED", "RECORDING", "FAILED"})
         row = save_initial_transcript(session, item, DEMO_TRANSCRIPT, actor_id=user.id, source="demo", stt_model="demo-fixture")
@@ -319,89 +364,107 @@
     @app.post("/api/v1/consultations/{consultation_id}/generate")
     async def generate_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         from .forms import get_template, validate_template_fields
 
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
         transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id))
         if transcript is None:
             raise HTTPException(409, "Сначала выполните транскрипцию")
         claim_processing(session, item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
+        tracker = ProcessingTracker(session_factory, item.id, "generate")
+        def provider_stage(key, state, attempt=1):
+            # Include the server's evidence/template validation in this stage.
+            if key == "output_validation" and state == "done":
+                return
+            tracker.stage(key, state, attempt)
         try:
+            tracker.start()
             session.refresh(transcript)
             source = canonical_source(transcript)
             template = get_template(item.template_id)
-            result = await app.state.llm.extract_consultation(source, template_fields=template["fields"])
+            tracker.stage("llm_extraction", "running")
+            result = await app.state.llm.extract_consultation(source, template_fields=template["fields"], on_stage=provider_stage)
+            tracker.stage("llm_extraction", "done", tracker.latest_attempt("llm_extraction"))
+            tracker.stage("output_validation", "running", tracker.latest_attempt("output_validation"))
             result = ExtractionResult.model_validate(result)
             evidence = validate_evidence(result, source)
             parsed = result.data
             if parsed.diagnosis_code is not None:
                 raise ValueError("LLM cannot select a diagnosis code")
             validate_template_fields(item.template_id, parsed)
             payload = parsed.model_dump(mode="json")
+            tracker.stage("output_validation", "done", tracker.latest_attempt("output_validation"))
             row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
             if row is None:
                 row = DocumentRow(consultation_id=item.id, version=1)
                 session.add(row)
             else:
                 row.version += 1
             row.ai_generated_data = payload
             row.doctor_approved_data = None
             row.working_data = payload
             row.source_transcript_revision = source.revision
             row.source_masked_text = source.text
             row.evidence = [link.model_dump(mode="json") for link in evidence]
             row.llm_provider = settings.effective_llm_provider
             row.llm_model = "demo" if settings.effective_llm_provider == "demo" else settings.openai_model
             row.updated_at = now_utc()
             item.status = "AI_GENERATED"
             item.error_message = None
             item.updated_at = now_utc()
+            tracker.finish(session=session)
             session.commit()
-            return document_response(row)
         except Exception:
-            session.rollback()
-            fail_processing(session, item.id, "Не удалось сформировать документ. Повторите попытку.")
+            processing_failed(session, item, tracker, "Не удалось сформировать документ. Повторите попытку.", "LLM_FAILED")
             raise HTTPException(502, "Не удалось сформировать документ") from None
+        return document_response(row)
 
     @app.get("/api/v1/consultations/{consultation_id}/document")
     def get_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
         require_consultation(session, consultation_id, user)
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == consultation_id))
         if row is None:
             raise HTTPException(404, "Документ не найден")
         require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         return document_response(row)
 
-    @app.get("/api/v1/consultations/{consultation_id}/document.docx")
-    def download_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
-        from .forms import render_docx, validate_template_fields
-
+    def approved_file(consultation_id: str, user: User, session: Session, kind: str):
+        from .forms import render_docx, render_pdf, validate_template_fields
         item = require_consultation(session, consultation_id, user)
         require_status(item, {"APPROVED", "SENT_TO_MIS"})
         row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
         if row is None or row.doctor_approved_data is None or item.approved_at is None:
             raise HTTPException(409, "Документ не подтверждён")
         require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
         try:
             data = ConsultationData.model_validate(row.doctor_approved_data)
             validate_template_fields(item.template_id, data)
-            docx = render_docx(item.template_id, data, patient_id=item.external_patient_id,
+            render = render_pdf if kind == "pdf" else render_docx
+            content = render(item.template_id, data, patient_id=item.external_patient_id,
                                consultation_id=item.id, doctor_name=item.approved_by_name or "Не указан", approved_at=item.approved_at)
         except Exception:
             raise HTTPException(502, "Не удалось подготовить документ") from None
         return Response(
-            content=docx,
-            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
-            headers={"Content-Disposition": f'attachment; filename="consultation-{item.id}.docx"'},
+            content=content,
+            media_type="application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
+            headers={"Content-Disposition": f'attachment; filename="consultation-{item.id}.{kind}"', "Cache-Control": "no-store"},
         )
 
+    @app.get("/api/v1/consultations/{consultation_id}/document.docx")
+    def download_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
+        return approved_file(consultation_id, user, session, "docx")
+
+    @app.get("/api/v1/consultations/{consultation_id}/document.pdf")
+    def download_pdf(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
+        return approved_file(consultation_id, user, session, "pdf")
+
     @app.patch("/api/v1/consultations/{consultation_id}/document")
     def edit_document(consultation_id: str, payload: EditDocumentRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
         from .forms import validate_template_fields
         from .diagnoses import get_diagnosis
 
         item = require_consultation(session, consultation_id, user)
         claim_write(session, item, {"AI_GENERATED", "REVIEWED"})
         try:
             validate_template_fields(item.template_id, payload.data)
         except ValueError:

```

## backend/app/service.py
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-5-base/backend/app/service.py	2026-09-30 14:31:08.591014429 +0500
+++ backend/app/service.py	2026-09-30 14:41:01.268985174 +0500
@@ -1,53 +1,80 @@
 from __future__ import annotations
 
 from datetime import datetime, timedelta, timezone
 
 from fastapi import HTTPException
 from sqlalchemy import select, update
 from sqlalchemy.orm import Session, object_session
 
-from .models import AudioFile, Consultation, DocumentRow, TranscriptRow, now_utc
+from .models import AudioFile, Consultation, DocumentRow, ProcessingRunRow, TranscriptRow, now_utc
 
 
 def iso(value: datetime | None) -> str | None:
     if value is None:
         return None
     if value.tzinfo is None:
         value = value.replace(tzinfo=timezone.utc)
     return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
 
 
-def consultation_response(item: Consultation) -> dict:
+def available_audio(session: Session, consultation_id: str, storage, retention_days: int):
+    if storage is None:
+        return None
+    audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == consultation_id))
+    transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id))
+    if audio is None or (transcript is not None and transcript.stt_model in {"demo-fixture", "synthetic-demo"}):
+        return None
+    created_at = audio.created_at.replace(tzinfo=timezone.utc) if audio.created_at.tzinfo is None else audio.created_at
+    if created_at < now_utc() - timedelta(days=retention_days):
+        return None
+    try:
+        path = storage.get(audio.storage_key)
+        return (audio, path) if path.is_file() else None
+    except (OSError, ValueError):
+        return None
+
+
+def processing_response(session: Session, consultation_id: str) -> list[dict]:
+    latest = {}
+    for row in session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.consultation_id == consultation_id)
+                              .order_by(ProcessingRunRow.started_at.desc(), ProcessingRunRow.id.desc())):
+        if row.operation not in latest:
+            latest[row.operation] = {"id": row.id, "operation": row.operation, "status": row.status,
+                "started_at": iso(row.started_at), "finished_at": iso(row.finished_at), "stages": row.stages}
+    return [latest[key] for key in ("upload", "transcribe", "generate") if key in latest]
+
+
+def consultation_response(item: Consultation, *, storage=None, retention_days: int = 7) -> dict:
     session = object_session(item)
     transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id)) if session else None
-    audio = session.scalar(select(AudioFile.id).where(AudioFile.consultation_id == item.id)) if session else None
+    audio = available_audio(session, item.id, storage, retention_days) if session else None
     return {
         "id": item.id,
         "external_patient_id": item.external_patient_id,
         "template_id": item.template_id,
         "status": item.status,
         "created_at": iso(item.created_at),
         "updated_at": iso(item.updated_at),
         "approved_at": iso(item.approved_at),
         "error_message": item.error_message,
         "transcript_revision": transcript.revision if transcript else None,
         "audio_available": audio is not None,
-        "processing_runs": [],
+        "processing_runs": processing_response(session, item.id) if session else [],
     }
 
 
-def transcript_response(item: TranscriptRow) -> dict:
+def transcript_response(item: TranscriptRow, *, storage=None, retention_days: int = 7) -> dict:
     from .transcripts import canonical_source
     source = canonical_source(item)
     session = object_session(item)
-    audio = session.scalar(select(AudioFile.id).where(AudioFile.consultation_id == item.consultation_id)) if session else None
+    audio = available_audio(session, item.consultation_id, storage, retention_days) if session else None
     return {
         "raw_text": item.raw_text,
         "normalized_text": item.normalized_text,
         "masked_text": source.text,
         "language": item.language,
         "duration_seconds": item.duration_seconds,
         "stt_model": item.stt_model,
         "segments": item.segments,
         "pii_entities": [entity.model_dump(mode="json") for entity in source.entities],
         "revision": item.revision,

```

## backend/app/transcripts.py
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-5-base/backend/app/transcripts.py	2026-09-30 14:31:08.591061227 +0500
+++ backend/app/transcripts.py	2026-09-30 14:41:01.227984637 +0500
@@ -17,49 +17,56 @@
 
 def _snapshot(session: Session, row: TranscriptRow, *, actor_id: str | None, source: str) -> None:
     session.flush()
     session.add(TranscriptRevisionRow(
         transcript_id=row.id, revision=row.revision, segments=row.segments,
         normalized_text=row.normalized_text, masked_text=row.masked_text,
         pii_entities=row.pii_entities, actor_id=actor_id, source=source,
     ))
 
 
-def _project(row: TranscriptRow, segments: list[StoredTranscriptSegment]) -> None:
+def _project(row: TranscriptRow, segments: list[StoredTranscriptSegment], on_stage=None) -> None:
+    if on_stage:
+        on_stage("normalization", "running", 1)
     normalized = normalize_segments(segments)
+    if on_stage:
+        on_stage("normalization", "done", 1)
+        on_stage("pii_masking", "running", 1)
     source = mask_segments(segments, revision=row.revision)
+    if on_stage:
+        on_stage("pii_masking", "done", 1)
     row.segments = [s.model_dump(mode="json") for s in segments]
     row.normalized_text = "\n".join(s.text for s in normalized)
     row.masked_text = source.text
     row.pii_entities = [entity.model_dump(mode="json") for entity in source.entities]
 
 
-def save_initial_transcript(session: Session, consultation: Consultation, transcript, *, actor_id: str | None, source: str, stt_model: str) -> TranscriptRow:
+def save_initial_transcript(session: Session, consultation: Consultation, transcript, *, actor_id: str | None, source: str, stt_model: str, on_stage=None) -> TranscriptRow:
     raw = transcript.model_dump() if hasattr(transcript, "model_dump") else dict(transcript)
     parts = raw.get("segments", [])
     text = raw.get("text") or raw.get("raw_text") or "\n".join(s["text"] for s in parts)
     if not text.strip():
         raise ValueError("empty transcription")
     duration = float(raw.get("duration_seconds", raw.get("duration", 0)))
     if not parts:
         parts = [{"start": 0, "end": duration, "text": text}]
     row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation.id).execution_options(populate_existing=True))
     if row is None:
         row = TranscriptRow(consultation_id=consultation.id, raw_text=text, revision=1)
         session.add(row)
     else:
         row.revision += 1
     segments = [StoredTranscriptSegment.model_validate({**s, "id": f"seg-{index:06d}"}) for index, s in enumerate(parts, 1)]
     row.language = raw.get("language") or "ru"
     row.duration_seconds = duration
     row.stt_model = stt_model
-    _project(row, segments)
+    _project(row, segments, on_stage)
     _snapshot(session, row, actor_id=actor_id, source=source)
     return row
 
 
 def edit_transcript(session: Session, consultation: Consultation, patch: TranscriptPatch, *, actor_id: str) -> TranscriptRow:
     claim_write(session, consultation, {"TRANSCRIBED", "AI_GENERATED", "REVIEWED", "FAILED"}, expected_revision=patch.expected_revision)
     row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation.id))
     if row is None or row.revision != patch.expected_revision:
         raise HTTPException(409, "Версия транскрипции устарела")
     changes = {change.segment_id: change.text for change in patch.changes}

```

## backend/tests/test_processing.py
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ backend/tests/test_processing.py	2026-09-30 14:43:18.153784807 +0500
@@ -0,0 +1,189 @@
+from concurrent.futures import ThreadPoolExecutor
+from threading import Event
+
+from fastapi.testclient import TestClient
+from sqlalchemy import select
+
+from app.models import Consultation, ProcessingRunRow
+from app.schemas import ConsultationData, ExtractionResult, Transcript, TranscriptSegment
+from test_transcript_revisions import client, sqlite_client, consultation, login, prepared
+
+
+WAV = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "
+
+
+def upload(client, prefix, headers):
+    return client.post(prefix + "/audio", headers=headers, files={"file": ("synthetic.wav", WAV, "audio/wav")})
+
+
+def test_stage_updates_visible_before_request_finishes(client):
+    headers = login(client)
+    cid = consultation(client, headers)["id"]
+    prefix = f"/api/v1/consultations/{cid}"
+    assert upload(client, prefix, headers).status_code == 200
+    entered, release = Event(), Event()
+    class BlockingSTT:
+        async def transcribe(self, _path):
+            entered.set()
+            assert release.wait(10)
+            return Transcript(language="ru", duration=2, segments=[TranscriptSegment(start=0, end=2, text="Синтетический кашель")])
+    client.app.state.stt = BlockingSTT()
+    with ThreadPoolExecutor(1) as pool:
+        pending = pool.submit(TestClient(client.app).post, prefix + "/transcribe", headers=headers)
+        try:
+            assert entered.wait(10)
+            summary = client.get(prefix, headers=headers).json()
+            assert summary["status"] == "PROCESSING"
+            runs = {run["operation"]: run for run in summary["processing_runs"]}
+            assert runs["upload"]["status"] == "done"
+            assert runs["upload"]["stages"][0]["duration_ms"] >= 0
+            active = runs["transcribe"]
+            assert active["status"] == "running"
+            assert active["stages"][0]["status"] == "running"
+            assert active["stages"][0]["started_at"] is not None
+            for future in active["stages"][1:]:
+                assert future["status"] == "pending"
+                assert future["duration_ms"] is future["started_at"] is future["finished_at"] is None
+            assert "percent" not in str(summary).lower()
+        finally:
+            release.set()
+        assert pending.result(timeout=15).status_code == 200
+    stages = client.get(prefix, headers=headers).json()["processing_runs"][-1]["stages"]
+    assert [s["key"] for s in stages] == ["stt", "normalization", "pii_masking"]
+    assert all(s["status"] == "done" and s["duration_ms"] >= 0 for s in stages)
+
+
+def test_failed_retry_and_restart_preserve_actual_timings(client, caplog):
+    headers, cid, prefix, _, _ = prepared(client)
+    entered, release = Event(), Event()
+    class RetryingLLM:
+        async def extract_consultation(self, source, *, template_fields=None, on_stage=None):
+            on_stage("llm_extraction", "running", 1)
+            on_stage("llm_extraction", "done", 1)
+            on_stage("output_validation", "running", 1)
+            on_stage("output_validation", "error", 1)
+            on_stage("llm_extraction", "running", 2)
+            entered.set()
+            assert release.wait(10)
+            raise ValueError("SYNTHETIC_PRIVATE_TEXT")
+    client.app.state.llm = RetryingLLM()
+    with ThreadPoolExecutor(1) as pool:
+        pending = pool.submit(TestClient(client.app).post, prefix + "/generate", headers=headers)
+        try:
+            assert entered.wait(10)
+            run = client.get(prefix, headers=headers).json()["processing_runs"][-1]
+            assert [(s["key"], s["attempt"], s["status"]) for s in run["stages"]] == [
+                ("llm_extraction", 1, "done"), ("output_validation", 1, "error"), ("llm_extraction", 2, "running")]
+            completed_ms = run["stages"][0]["duration_ms"]
+        finally:
+            release.set()
+        response = pending.result(timeout=15)
+        assert response.status_code == 502
+        assert "SYNTHETIC_PRIVATE_TEXT" not in response.text
+    run = client.get(prefix, headers=headers).json()["processing_runs"][-1]
+    assert run["status"] == "error"
+    assert run["stages"][0]["duration_ms"] == completed_ms
+    assert run["stages"][-1]["error_code"] == "LLM_FAILED"
+    assert "SYNTHETIC_PRIVATE_TEXT" not in str(run)
+    assert "SYNTHETIC_PRIVATE_TEXT" not in caplog.text
+
+    from app.processing import ProcessingTracker, recover_interrupted_runs
+    tracker = ProcessingTracker(client.app.state.session_factory, cid, "transcribe")
+    tracker.start()
+    tracker.stage("stt", "running")
+    tracker.stage("stt", "done")
+    tracker.stage("normalization", "running")
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "PROCESSING"
+        session.commit()
+        assert recover_interrupted_runs(session) == 1
+        session.commit()
+    with client.app.state.session_factory() as session:
+        recovered = session.get(ProcessingRunRow, tracker.run_id)
+        assert recovered.status == "error"
+        assert recovered.stages[0]["status"] == "done"
+        assert recovered.stages[0]["duration_ms"] >= 0
+        assert recovered.stages[1]["error_code"] == "INTERRUPTED"
+        assert recovered.stages[1]["duration_ms"] is None
+        assert recovered.stages[2]["status"] == "pending"
+        assert session.get(Consultation, cid).status == "FAILED"
+
+
+def test_successful_generation_finishes_telemetry_in_clinical_transaction(client, monkeypatch):
+    from app.processing import ProcessingTracker
+    original_finish = ProcessingTracker.finish
+    def finish_only_in_clinical_transaction(self, *, session=None):
+        assert session is not None, "No independent telemetry cleanup after clinical commit"
+        return original_finish(self, session=session)
+    monkeypatch.setattr(ProcessingTracker, "finish", finish_only_in_clinical_transaction)
+    headers, cid, prefix, _, _ = prepared(client)
+    response = client.post(prefix + "/generate", headers=headers)
+    assert response.status_code == 200
+    summary = client.get(prefix, headers=headers).json()
+    assert summary["status"] == "AI_GENERATED"
+    run = summary["processing_runs"][-1]
+    assert run["status"] == "done"
+    assert [s["status"] for s in run["stages"]] == ["done", "done"]
+
+
+def test_tracker_does_not_commit_unrelated_clinical_changes(client):
+    from app.processing import ProcessingTracker
+    headers, cid, _, _, _ = prepared(client)
+    factory = client.app.state.session_factory
+    with factory() as clinical:
+        consultation = clinical.get(Consultation, cid)
+        consultation.external_patient_id = "UNCOMMITTED_SENTINEL"
+        tracker = ProcessingTracker(factory, cid, "generate")
+        tracker.start()
+        tracker.stage("llm_extraction", "running")
+        with factory() as observer:
+            assert observer.get(Consultation, cid).external_patient_id != "UNCOMMITTED_SENTINEL"
+        clinical.rollback()
+
+
+def test_startup_recovers_running_runs_without_changing_approved_or_completed(client):
+    from app.main import create_app
+    from app.processing import ProcessingTracker
+    headers, cid, prefix, _, _ = prepared(client)
+    tracker = ProcessingTracker(client.app.state.session_factory, cid, "transcribe")
+    tracker.start()
+    tracker.stage("stt", "running")
+    tracker.stage("stt", "done")
+    tracker.stage("normalization", "running")
+    other = consultation(client, headers)["id"]
+    done = ProcessingTracker(client.app.state.session_factory, other, "generate")
+    done.start()
+    done.stage("llm_extraction", "running")
+    done.stage("llm_extraction", "done")
+    done.stage("output_validation", "running")
+    done.stage("output_validation", "done")
+    done.finish()
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "PROCESSING"
+        session.get(Consultation, other).status = "APPROVED"
+        session.commit()
+        finished = session.get(ProcessingRunRow, done.run_id).stages
+    # Use existing disposable schema; PG fixture started in live mode intentionally.
+    from dataclasses import replace
+    settings = replace(client.app.state.settings)
+    if settings.database_url.startswith("postgresql"):
+        settings.app_mode = "live"
+    with TestClient(create_app(settings)):
+        pass
+    with client.app.state.session_factory() as session:
+        assert session.get(ProcessingRunRow, tracker.run_id).status == "error"
+        assert session.get(Consultation, cid).status == "FAILED"
+        assert session.get(Consultation, other).status == "APPROVED"
+        assert session.get(ProcessingRunRow, done.run_id).stages == finished
+
+
+def test_summaries_return_only_latest_run_per_operation(client):
+    headers, cid, prefix, _, _ = prepared(client)
+    for _ in range(2):
+        assert client.post(prefix + "/generate", headers=headers).status_code == 200
+    summary = client.get(prefix, headers=headers).json()
+    assert len(summary["processing_runs"]) == 1
+    with client.app.state.session_factory() as session:
+        runs = session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.consultation_id == cid).order_by(ProcessingRunRow.started_at)).all()
+        assert len(runs) == 2
+        assert summary["processing_runs"][0]["id"] == runs[-1].id

```

## backend/tests/test_protected_files.py
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ backend/tests/test_protected_files.py	2026-09-30 14:43:16.908768378 +0500
@@ -0,0 +1,106 @@
+from datetime import timedelta
+from io import BytesIO
+
+import pytest
+from pypdf import PdfReader
+from sqlalchemy import select
+
+from app.models import AudioFile, Consultation, DocumentRow, now_utc
+from test_processing import WAV, upload
+from test_transcript_revisions import client, sqlite_client, consultation, login, prepared
+
+
+def test_audio_requires_auth_owner_and_actual_unexpired_file(client):
+    from app.auth import make_token, password_hash
+    from app.models import User
+    headers = login(client)
+    cid = consultation(client, headers)["id"]
+    prefix = f"/api/v1/consultations/{cid}"
+    assert client.get(prefix + "/audio").status_code == 401
+    assert client.get(prefix + "/audio", headers=headers).status_code == 404
+    assert upload(client, prefix, headers).status_code == 200
+    response = client.get(prefix + "/audio", headers=headers)
+    assert response.status_code == 200
+    assert response.content == WAV
+    assert response.headers["content-type"] == "audio/wav"
+    assert response.headers["cache-control"] == "no-store"
+    assert client.get(prefix, headers=headers).json()["audio_available"] is True
+    with client.app.state.session_factory() as session:
+        other = User(username="file-other", password_hash=password_hash.hash("test"), role="doctor", display_name="Other")
+        session.add(other)
+        session.commit()
+        other_headers = {"Authorization": "Bearer " + make_token(other, client.app.state.settings.jwt_secret)}
+    assert client.get(prefix + "/audio", headers=other_headers).status_code == 404
+    assert client.get(prefix + "/document.pdf", headers=other_headers).status_code == 404
+    with client.app.state.session_factory() as session:
+        audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == cid))
+        audio.created_at = now_utc() - timedelta(days=8)
+        session.commit()
+    assert client.get(prefix + "/audio", headers=headers).status_code == 404
+    assert client.get(prefix, headers=headers).json()["audio_available"] is False
+
+
+def test_demo_and_deleted_audio_are_unavailable(client, monkeypatch):
+    headers, cid, prefix, _, _ = prepared(client)
+    assert client.get(prefix + "/audio", headers=headers).status_code == 404
+    with client.app.state.session_factory() as session:
+        session.get(Consultation, cid).status = "FAILED"
+        session.commit()
+    assert upload(client, prefix, headers).status_code == 200
+    assert client.get(prefix + "/audio", headers=headers).status_code == 404
+    # A genuine recording without a synthetic transcript is available until deletion.
+    cid = consultation(client, headers)["id"]
+    prefix = f"/api/v1/consultations/{cid}"
+    assert upload(client, prefix, headers).status_code == 200
+    storage = client.app.state.storage
+    original_get = storage.get
+    def removed_after_check(key):
+        path = original_get(key)
+        path.unlink()
+        return path
+    monkeypatch.setattr(storage, "get", removed_after_check)
+    assert client.get(prefix + "/audio", headers=headers).status_code == 404
+    assert client.get(prefix, headers=headers).json()["audio_available"] is False
+
+
+def test_pdf_uses_approved_not_working_snapshot(client):
+    headers, cid, prefix, _, doc = prepared(client, review=True)
+    assert client.get(prefix + "/document.pdf").status_code == 401
+    assert client.get(prefix + "/document.pdf", headers=headers).status_code == 409
+    assert client.post(prefix + "/approve", headers=headers, json={"version": doc["version"]}).status_code == 200
+    with client.app.state.session_factory() as session:
+        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
+        row.working_data = {**row.working_data, "complaints": ["UNSAVED_SENTINEL"]}
+        # Historical optional metadata must not prevent an approved export.
+        row.source_masked_text = None
+        row.evidence = []
+        session.commit()
+    response = client.get(prefix + "/document.pdf", headers=headers)
+    assert response.status_code == 200
+    assert response.content.startswith(b"%PDF-")
+    assert response.headers["content-type"] == "application/pdf"
+    assert response.headers["cache-control"] == "no-store"
+    assert ".pdf" in response.headers["content-disposition"]
+    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
+    assert "UNSAVED_SENTINEL" not in text
+    assert "кашель" in text.lower()
+
+
+def test_audio_path_replaced_by_symlink_is_not_served(client, monkeypatch, tmp_path):
+    headers = login(client)
+    cid = consultation(client, headers)["id"]
+    prefix = f"/api/v1/consultations/{cid}"
+    assert upload(client, prefix, headers).status_code == 200
+    target = tmp_path / "unrelated-private-file"
+    target.write_bytes(b"DO_NOT_SERVE_THIS_FILE")
+    storage = client.app.state.storage
+    original_get = storage.get
+    def replaced_after_check(key):
+        path = original_get(key)
+        path.unlink()
+        path.symlink_to(target)
+        return path
+    monkeypatch.setattr(storage, "get", replaced_after_check)
+    response = client.get(prefix + "/audio", headers=headers)
+    assert response.status_code == 404
+    assert b"DO_NOT_SERVE_THIS_FILE" not in response.content

```
