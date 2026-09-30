from __future__ import annotations

import asyncio
import contextlib
import os
import stat
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
from starlette.concurrency import run_in_threadpool

from .auth import authenticate, create_initial_doctor, decode_token, make_token
from .config import Settings
from .db import make_engine, make_session_factory
from .models import AudioFile, Consultation, ConsultationEdit, DocumentRow, MISExport, TranscriptRow, User, now_utc
from .schemas import ConsultationData, ExtractionResult, TranscriptPatch
from .grounding import validate_evidence
from .transcripts import canonical_source, edit_transcript, require_fresh_document, save_initial_transcript
from .processing import ProcessingTracker, recover_interrupted_runs
from .service import (
    available_audio, claim_processing, claim_write, cleanup_expired_audio, consultation_response as _consultation_response, document_response,
    fail_processing, locked_consultation, require_consultation, require_status, transcript_response as _transcript_response,
)


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateConsultationRequest(BaseModel):
    external_patient_id: str = Field(min_length=1, max_length=200)
    template_id: str = Field(default="therapist", min_length=1, max_length=50)


class EditDocumentRequest(BaseModel):
    data: ConsultationData
    version: int = Field(ge=1)


class VersionRequest(BaseModel):
    version: int = Field(ge=1)


bearer = HTTPBearer(auto_error=False)


def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role, "display_name": user.display_name}


def _sniff_audio(content_type: str, data: bytes) -> tuple[str, str]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    signatures = {
        "audio/webm": (data.startswith(b"\x1a\x45\xdf\xa3"), "webm"),
        "audio/wav": (data.startswith(b"RIFF") and data[8:12] == b"WAVE", "wav"),
        "audio/x-wav": (data.startswith(b"RIFF") and data[8:12] == b"WAVE", "wav"),
        "audio/mpeg": (data.startswith(b"ID3") or (len(data) > 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0), "mp3"),
        "audio/mp4": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
        "audio/x-m4a": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
        "audio/m4a": (len(data) > 12 and data[4:8] == b"ftyp", "m4a"),
    }
    valid, extension = signatures.get(media_type, (False, ""))
    if not valid:
        raise HTTPException(415, "Неподдерживаемый аудиофайл")
    return media_type, extension


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from .providers.demo import DemoLLMProvider
        from .providers.llm import OpenAIProvider
        from .providers.mis import MockMISProvider
        from .providers.storage import LocalStorage
        from .providers.stt import WhisperSTTProvider

        if settings.database_url.startswith("sqlite:"):
            Path(settings.database_url.removeprefix("sqlite:///" )).parent.mkdir(parents=True, exist_ok=True)
        if settings.app_mode == "demo":
            from alembic import command
            from alembic.config import Config

            backend_dir = Path(__file__).resolve().parents[1]
            migration_config = Config(str(backend_dir / "alembic.ini"))
            migration_config.set_main_option("script_location", str(backend_dir / "alembic"))
            migration_config.attributes["database_url"] = settings.database_url
            command.upgrade(migration_config, "head")
        with session_factory() as session:
            create_initial_doctor(session, settings)
            recover_interrupted_runs(session)
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
                    MISExport.consultation_id.in_(select(Consultation.id).where(Consultation.status == "APPROVED")),
                )
            )
            session.commit()
        app.state.storage = LocalStorage(settings.audio_storage_dir)
        app.state.stt = WhisperSTTProvider(
            model=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        app.state.llm = DemoLLMProvider() if settings.effective_llm_provider == "demo" else OpenAIProvider(
            api_key=settings.openai_api_key, model=settings.openai_model,
        )
        app.state.mis = MockMISProvider()

        async def retention_loop():
            while True:
                try:
                    with session_factory() as session:
                        cleanup_expired_audio(session, app.state.storage, settings.audio_retention_days)
                except Exception:
                    # A storage/database outage must not stop the API or disable future cleanup.
                    pass
                await asyncio.sleep(24 * 3600)

        task = asyncio.create_task(retention_loop())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            engine.dispose()

    app = FastAPI(title="AI Medical Scribe", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    def consultation_response(item):
        return _consultation_response(item, storage=app.state.storage, retention_days=settings.audio_retention_days)

    def transcript_response(item):
        return _transcript_response(item, storage=app.state.storage, retention_days=settings.audio_retention_days)

    def processing_failed(session, item, tracker, message, code):
        session.rollback()
        tracker.fail(tracker.failure_code(code), session=session)
        session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status == "PROCESSING")
                        .values(status="FAILED", error_message=message, updated_at=now_utc()))
        session.commit()

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "Некорректные данные запроса"})

    def db_session():
        with session_factory() as session:
            yield session

    def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(db_session)) -> User:
        if credentials is None:
            raise HTTPException(401, "Требуется вход")
        user_id = decode_token(credentials.credentials, settings.jwt_secret)
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(401, "Требуется вход")
        if user.role not in {"doctor", "admin"}:
            raise HTTPException(403, "Доступ запрещён")
        return user

    from .protocols import create_protocol_router
    app.include_router(create_protocol_router(current_user))

    @app.get("/api/v1/verification/{public_id}")
    def verify_document(public_id: str, session: Session = Depends(db_session)):
        from .models import ExportArtifact
        from datetime import timezone
        record = session.execute(select(ExportArtifact.issued_at, ExportArtifact.sha256)
                                 .where(ExportArtifact.public_id == public_id)).first()
        if record is None:
            raise HTTPException(404, "Документ не найден")
        issued_at = record.issued_at
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        return JSONResponse({"issuer": "MedHub", "issued_at": issued_at.isoformat(),
                             "status": "valid", "sha256": record.sha256},
                            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "mode": settings.app_mode, "stt_model": settings.whisper_model,
                "llm_provider": settings.effective_llm_provider,
                "llm_model": "demo" if settings.effective_llm_provider == "demo" else settings.openai_model, "mis_provider": "mock"}

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, session: Session = Depends(db_session)):
        user = authenticate(session, payload.username, payload.password)
        return {"access_token": make_token(user, settings.jwt_secret), "token_type": "bearer", "user": public_user(user)}

    @app.get("/api/v1/auth/me")
    def me(user: User = Depends(current_user)):
        return public_user(user)

    @app.get("/api/v1/templates")
    def templates(_user: User = Depends(current_user)):
        from .forms import list_templates

        return list_templates()

    @app.get("/api/v1/diagnoses")
    def diagnoses(q: str = Query(default="", max_length=100), limit: int = Query(default=20, ge=1, le=50),
                  _user: User = Depends(current_user)):
        from .diagnoses import search_diagnoses

        return search_diagnoses(q, limit)

    @app.get("/api/v1/consultations")
    def list_consultations(user: User = Depends(current_user), session: Session = Depends(db_session)):
        query = select(Consultation).order_by(Consultation.created_at.desc())
        if user.role != "admin":
            query = query.where(Consultation.created_by == user.id)
        return [consultation_response(row) for row in session.scalars(query)]

    @app.post("/api/v1/consultations", status_code=201)
    def create_consultation(payload: CreateConsultationRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
        from .forms import get_template

        try:
            get_template(payload.template_id)
        except KeyError:
            raise HTTPException(422, "Неизвестный шаблон консультации") from None
        item = Consultation(external_patient_id=payload.external_patient_id.strip(), template_id=payload.template_id, created_by=user.id)
        if not item.external_patient_id:
            raise HTTPException(422, "Укажите идентификатор пациента")
        session.add(item)
        session.commit()
        return consultation_response(item)

    @app.get("/api/v1/consultations/{consultation_id}")
    def get_consultation(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        return consultation_response(require_consultation(session, consultation_id, user))

    @app.post("/api/v1/consultations/{consultation_id}/recording")
    def start_recording(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = locked_consultation(session, consultation_id, user)
        require_status(item, {"CREATED", "RECORDING"})
        changed = session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["CREATED", "RECORDING"]))
                                  .values(status="RECORDING", updated_at=now_utc()))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Консультация уже изменена")
        session.commit()
        session.refresh(item)
        return consultation_response(item)

    @app.post("/api/v1/consultations/{consultation_id}/audio")
    async def upload_audio(consultation_id: str, file: UploadFile = File(...), user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = require_consultation(session, consultation_id, user)
        claim_processing(session, item, {"CREATED", "RECORDING", "FAILED"})
        tracker = ProcessingTracker(session_factory, item.id, "upload")
        try:
            tracker.start()
            tracker.stage("upload", "running")
            max_bytes = settings.max_upload_mb * 1024 * 1024
            data = await file.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise HTTPException(413, "Аудиофайл слишком большой")
            media_type, extension = _sniff_audio(file.content_type or "", data)
            key = f"{item.id}.{extension}"
            await run_in_threadpool(app.state.storage.save, key, data)
            previous = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
            if previous is not None and previous.storage_key != key:
                await run_in_threadpool(app.state.storage.delete, previous.storage_key)
            tracker.stage("upload", "done")
            if previous is None:
                previous = AudioFile(consultation_id=item.id)
                session.add(previous)
            previous.storage_key = key
            previous.content_type = media_type
            previous.size_bytes = len(data)
            previous.created_at = now_utc()
            item.status = "RECORDING"
            item.error_message = None
            item.updated_at = now_utc()
            tracker.finish(session=session)
            session.commit()
        except Exception as error:
            processing_failed(session, item, tracker, "Не удалось загрузить аудио. Повторите попытку.", "UPLOAD_FAILED")
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(502, "Не удалось загрузить аудио") from None
        return consultation_response(item)

    @app.get("/api/v1/consultations/{consultation_id}/audio")
    def download_audio(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        require_consultation(session, consultation_id, user)
        result = available_audio(session, consultation_id, app.state.storage, settings.audio_retention_days)
        if result is None:
            raise HTTPException(404, "Аудиозапись недоступна")
        audio, path = result
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise OSError("Audio is not a regular file")
                content = source.read()
        except OSError:
            raise HTTPException(404, "Аудиозапись недоступна") from None
        return Response(content, media_type=audio.content_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/consultations/{consultation_id}/transcribe")
    async def transcribe(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = require_consultation(session, consultation_id, user)
        require_status(item, {"CREATED", "RECORDING", "FAILED"})
        audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
        if audio is None:
            raise HTTPException(409, "Сначала загрузите аудио")
        claim_processing(session, item, {"CREATED", "RECORDING", "FAILED"})
        tracker = ProcessingTracker(session_factory, item.id, "transcribe")
        try:
            tracker.start()
            tracker.stage("stt", "running")
            path = app.state.storage.get(audio.storage_key)
            transcript = await app.state.stt.transcribe(str(path))
            tracker.stage("stt", "done")
            row = save_initial_transcript(session, item, transcript, actor_id=user.id, source="stt", stt_model=settings.whisper_model, on_stage=tracker.stage)
            item.status = "TRANSCRIBED"
            item.updated_at = now_utc()
            tracker.finish(session=session)
            session.commit()
        except Exception:
            processing_failed(session, item, tracker, "Не удалось распознать аудио. Повторите попытку.", "STT_FAILED")
            raise HTTPException(502, "Не удалось распознать аудио") from None
        return transcript_response(row)

    @app.post("/api/v1/consultations/{consultation_id}/demo")
    def demo_transcript(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        if settings.app_mode != "demo":
            raise HTTPException(404, "Недоступно")
        from .providers.demo import DEMO_TRANSCRIPT

        item = require_consultation(session, consultation_id, user)
        claim_write(session, item, {"CREATED", "RECORDING", "FAILED"})
        row = save_initial_transcript(session, item, DEMO_TRANSCRIPT, actor_id=user.id, source="demo", stt_model="demo-fixture")
        item.status = "TRANSCRIBED"
        item.error_message = None
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

    @app.patch("/api/v1/consultations/{consultation_id}/transcript")
    def correct_transcript(consultation_id: str, payload: TranscriptPatch, user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = require_consultation(session, consultation_id, user)
        row = edit_transcript(session, item, payload, actor_id=user.id)
        session.commit()
        return transcript_response(row)

    @app.post("/api/v1/consultations/{consultation_id}/generate")
    async def generate_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        from .forms import get_template, validate_template_fields

        item = require_consultation(session, consultation_id, user)
        require_status(item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
        transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id))
        if transcript is None:
            raise HTTPException(409, "Сначала выполните транскрипцию")
        claim_processing(session, item, {"TRANSCRIBED", "AI_GENERATED", "FAILED"})
        tracker = ProcessingTracker(session_factory, item.id, "generate")
        def provider_stage(key, state, attempt=1):
            # Include the server's evidence/template validation in this stage.
            if key == "output_validation" and state == "done":
                return
            tracker.stage(key, state, attempt)
        try:
            tracker.start()
            session.refresh(transcript)
            source = canonical_source(transcript)
            template = get_template(item.template_id)
            tracker.stage("llm_extraction", "running")
            result = await app.state.llm.extract_consultation(source, template_fields=template["fields"], on_stage=provider_stage)
            tracker.stage("llm_extraction", "done", tracker.latest_attempt("llm_extraction"))
            tracker.stage("output_validation", "running", tracker.latest_attempt("output_validation"))
            result = ExtractionResult.model_validate(result)
            evidence = validate_evidence(result, source)
            parsed = result.data
            if parsed.diagnosis_code is not None:
                raise ValueError("LLM cannot select a diagnosis code")
            validate_template_fields(item.template_id, parsed)
            payload = parsed.model_dump(mode="json")
            tracker.stage("output_validation", "done", tracker.latest_attempt("output_validation"))
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
            tracker.finish(session=session)
            session.commit()
        except Exception:
            processing_failed(session, item, tracker, "Не удалось сформировать документ. Повторите попытку.", "LLM_FAILED")
            raise HTTPException(502, "Не удалось сформировать документ") from None
        return document_response(row)

    @app.get("/api/v1/consultations/{consultation_id}/document")
    def get_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        require_consultation(session, consultation_id, user)
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == consultation_id))
        if row is None:
            raise HTTPException(404, "Документ не найден")
        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
        return document_response(row)

    def approved_file(consultation_id: str, user: User, session: Session, kind: str):
        from .forms import render_docx, render_pdf, validate_template_fields
        item = require_consultation(session, consultation_id, user)
        require_status(item, {"APPROVED", "SENT_TO_MIS"})
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
        if row is None or row.doctor_approved_data is None or item.approved_at is None:
            raise HTTPException(409, "Документ не подтверждён")
        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
        try:
            data = ConsultationData.model_validate(row.doctor_approved_data)
            validate_template_fields(item.template_id, data)
            metadata = dict(patient_id=item.external_patient_id, consultation_id=item.id,
                            doctor_name=item.approved_by_name or "Не указан", approved_at=item.approved_at)
            if kind == "pdf":
                from .export_artifacts import issued_pdf
                content = issued_pdf(session, row, lambda public_id: render_pdf(item.template_id, data,
                    **metadata, verification_url=f"{settings.public_base_url.rstrip('/')}/verify/{public_id}"))
            else:
                content = render_docx(item.template_id, data, **metadata)
        except Exception:
            raise HTTPException(502, "Не удалось подготовить документ") from None
        return Response(
            content=content,
            media_type="application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="consultation-{item.id}.{kind}"', "Cache-Control": "no-store"},
        )

    @app.get("/api/v1/consultations/{consultation_id}/document.docx")
    def download_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        return approved_file(consultation_id, user, session, "docx")

    @app.get("/api/v1/consultations/{consultation_id}/document.pdf")
    def download_pdf(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        return approved_file(consultation_id, user, session, "pdf")

    @app.patch("/api/v1/consultations/{consultation_id}/document")
    def edit_document(consultation_id: str, payload: EditDocumentRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
        from .forms import validate_template_fields
        from .diagnoses import get_diagnosis

        item = require_consultation(session, consultation_id, user)
        claim_write(session, item, {"AI_GENERATED", "REVIEWED"})
        try:
            validate_template_fields(item.template_id, payload.data)
        except ValueError:
            raise HTTPException(422, "Некорректные поля шаблона") from None
        if payload.data.diagnosis_code is not None and get_diagnosis(payload.data.diagnosis_code) is None:
            raise HTTPException(422, "Неизвестный код диагноза")
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
        if row is None or row.version != payload.version:
            raise HTTPException(409, "Версия документа устарела")
        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
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
                ))
        changed = session.execute(
            update(DocumentRow).where(DocumentRow.id == row.id, DocumentRow.version == payload.version)
            .values(working_data=data, version=payload.version + 1, updated_at=now_utc())
        )
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Версия документа устарела")
        status_change = session.execute(
            update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["AI_GENERATED", "REVIEWED"]))
            .values(status="REVIEWED", updated_at=now_utc())
        )
        if status_change.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Консультация уже изменена")
        session.commit()
        session.refresh(row)
        return document_response(row)

    @app.post("/api/v1/consultations/{consultation_id}/approve")
    def approve(consultation_id: str, payload: VersionRequest, user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = require_consultation(session, consultation_id, user)
        claim_write(session, item, {"REVIEWED"})
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
        if row is None or row.version != payload.version:
            raise HTTPException(409, "Версия документа устарела")
        require_fresh_document(row, session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id)))
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
            .values(status="APPROVED", approved_at=approved_at, approved_by=user.id,
                    approved_by_name=user.display_name, updated_at=approved_at)
        )
        if status_change.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Консультация уже изменена")
        session.commit()
        session.refresh(item)
        return consultation_response(item)

    @app.post("/api/v1/consultations/{consultation_id}/send-to-mis")
    async def send_to_mis(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        item = locked_consultation(session, consultation_id, user)
        existing = session.scalar(select(MISExport).where(MISExport.consultation_id == item.id))
        if item.status == "SENT_TO_MIS" and existing and existing.success:
            return {"success": True, "document_id": existing.document_id, "provider": existing.provider}
        require_status(item, {"APPROVED"})
        if existing is not None:
            raise HTTPException(409, "Отправка уже выполняется")
        document = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
        if document is None or document.doctor_approved_data is None:
            raise HTTPException(409, "Документ не подтверждён")
        reservation = MISExport(consultation_id=item.id, provider="mock", success=False)
        session.add(reservation)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Отправка уже выполняется") from None
        try:
            result = await app.state.mis.send_consultation(
                ConsultationData.model_validate(document.doctor_approved_data),
                consultation_id=item.id,
                patient_id=item.external_patient_id,
            )
            if not result.success:
                raise ValueError("MIS rejected")
            reservation.document_id = result.document_id
            reservation.success = True
            item.status = "SENT_TO_MIS"
            item.updated_at = now_utc()
            session.commit()
            return {"success": True, "document_id": result.document_id, "provider": "mock"}
        except Exception:
            session.rollback()
            session.delete(reservation)
            session.commit()
            raise HTTPException(502, "Не удалось отправить документ в МИС") from None

    @app.get("/api/v1/consultations/{consultation_id}/audit")
    def audit(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        require_consultation(session, consultation_id, user)
        rows = session.scalars(select(ConsultationEdit).where(ConsultationEdit.consultation_id == consultation_id).order_by(ConsultationEdit.created_at)).all()
        from .service import iso
        return [{"id": row.id, "field": row.field, "ai_value": row.ai_value,
                 "doctor_value": row.doctor_value, "changed": row.changed,
                 "created_at": iso(row.created_at)} for row in rows]

    return app


app = create_app()
