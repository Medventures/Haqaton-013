from __future__ import annotations

import asyncio
import contextlib
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

from .auth import authenticate, create_initial_doctor, decode_token, make_token
from .config import Settings
from .db import make_engine, make_session_factory
from .models import AudioFile, Consultation, ConsultationEdit, DocumentRow, MISExport, TranscriptRow, User, now_utc
from .schemas import ConsultationData
from .service import (
    claim_processing, cleanup_expired_audio, consultation_response, document_response,
    fail_processing, locked_consultation, require_consultation, require_status, transcript_response,
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


def _transcript_parts(transcript) -> tuple[str, str, float, list]:
    raw = transcript.model_dump() if hasattr(transcript, "model_dump") else dict(transcript)
    segments = raw.get("segments", [])
    text = raw.get("text") or raw.get("raw_text") or "\n".join(segment["text"] for segment in segments)
    if not text.strip():
        raise ValueError("empty transcription")
    return text, raw.get("language") or "ru", float(raw.get("duration_seconds", raw.get("duration", 0))), segments


def _save_transcript(session: Session, consultation_id: str, transcript, stt_model: str) -> TranscriptRow:
    from .normalization import normalize_transcript
    from .pii import PIIMaskingService

    raw_text, language, duration, segments = _transcript_parts(transcript)
    normalized = normalize_transcript(raw_text)
    masked = PIIMaskingService().mask(normalized)
    entities = [entry.model_dump() if hasattr(entry, "model_dump") else dict(entry) for entry in masked.entities]
    row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id))
    if row is None:
        row = TranscriptRow(consultation_id=consultation_id)
        session.add(row)
    row.raw_text = raw_text
    row.normalized_text = normalized
    row.masked_text = masked.text
    row.language = language
    row.duration_seconds = duration
    row.stt_model = stt_model
    row.segments = segments
    row.pii_entities = entities
    return row


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
        item = locked_consultation(session, consultation_id, user)
        require_status(item, {"CREATED", "RECORDING", "FAILED"})
        changed = session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["CREATED", "RECORDING", "FAILED"]))
                                  .values(updated_at=now_utc()))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Консультация уже изменена")
        max_bytes = settings.max_upload_mb * 1024 * 1024
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(413, "Аудиофайл слишком большой")
        media_type, extension = _sniff_audio(file.content_type or "", data)
        key = f"{item.id}.{extension}"
        app.state.storage.save(key, data)
        previous = session.scalar(select(AudioFile).where(AudioFile.consultation_id == item.id))
        if previous is None:
            previous = AudioFile(consultation_id=item.id)
            session.add(previous)
        elif previous.storage_key != key:
            app.state.storage.delete(previous.storage_key)
        previous.storage_key = key
        previous.content_type = media_type
        previous.size_bytes = len(data)
        previous.created_at = now_utc()
        item.status = "RECORDING"
        item.error_message = None
        item.updated_at = now_utc()
        session.commit()
        return consultation_response(item)

    @app.post("/api/v1/consultations/{consultation_id}/transcribe")
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
            row = _save_transcript(session, item.id, transcript, settings.whisper_model)
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

        item = locked_consultation(session, consultation_id, user)
        require_status(item, {"CREATED", "RECORDING", "FAILED"})
        changed = session.execute(update(Consultation).where(Consultation.id == item.id, Consultation.status.in_(["CREATED", "RECORDING", "FAILED"]))
                                  .values(status="TRANSCRIBED", updated_at=now_utc(), error_message=None))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Консультация уже изменена")
        row = _save_transcript(session, item.id, DEMO_TRANSCRIPT, "demo-fixture")
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
            template = get_template(item.template_id)
            result = await app.state.llm.extract_consultation(transcript.masked_text, template_fields=template["fields"])
            parsed = ConsultationData.model_validate(result)
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
        return document_response(row)

    @app.get("/api/v1/consultations/{consultation_id}/document.docx")
    def download_document(consultation_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
        from .forms import render_docx, validate_template_fields

        item = require_consultation(session, consultation_id, user)
        require_status(item, {"APPROVED", "SENT_TO_MIS"})
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id))
        if row is None or row.doctor_approved_data is None or item.approved_at is None:
            raise HTTPException(409, "Документ не подтверждён")
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

        item = locked_consultation(session, consultation_id, user)
        require_status(item, {"AI_GENERATED", "REVIEWED"})
        try:
            validate_template_fields(item.template_id, payload.data)
        except ValueError:
            raise HTTPException(422, "Некорректные поля шаблона") from None
        if payload.data.diagnosis_code is not None and get_diagnosis(payload.data.diagnosis_code) is None:
            raise HTTPException(422, "Неизвестный код диагноза")
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
        if row is None or row.version != payload.version:
            raise HTTPException(409, "Версия документа устарела")
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
        item = locked_consultation(session, consultation_id, user)
        require_status(item, {"REVIEWED"})
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == item.id).with_for_update())
        if row is None or row.version != payload.version:
            raise HTTPException(409, "Версия документа устарела")
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
