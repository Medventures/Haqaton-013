from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, object_session

from .models import AudioFile, Consultation, DocumentRow, ProcessingRunRow, TranscriptRow, now_utc


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def available_audio(session: Session, consultation_id: str, storage, retention_days: int):
    if storage is None:
        return None
    audio = session.scalar(select(AudioFile).where(AudioFile.consultation_id == consultation_id))
    transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation_id))
    if audio is None or (transcript is not None and transcript.stt_model in {"demo-fixture", "synthetic-demo"}):
        return None
    created_at = audio.created_at.replace(tzinfo=timezone.utc) if audio.created_at.tzinfo is None else audio.created_at
    if created_at < now_utc() - timedelta(days=retention_days):
        return None
    try:
        path = storage.get(audio.storage_key)
        return (audio, path) if path.is_file() else None
    except (OSError, ValueError):
        return None


def processing_response(session: Session, consultation_id: str) -> list[dict]:
    latest = {}
    for row in session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.consultation_id == consultation_id)
                              .order_by(ProcessingRunRow.started_at.desc(), ProcessingRunRow.id.desc())):
        if row.operation not in latest:
            latest[row.operation] = {"id": row.id, "operation": row.operation, "status": row.status,
                "started_at": iso(row.started_at), "finished_at": iso(row.finished_at), "stages": row.stages}
    return [latest[key] for key in ("upload", "transcribe", "generate") if key in latest]


def consultation_response(item: Consultation, *, storage=None, retention_days: int = 7) -> dict:
    session = object_session(item)
    transcript = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == item.id)) if session else None
    audio = available_audio(session, item.id, storage, retention_days) if session else None
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
        "processing_runs": processing_response(session, item.id) if session else [],
    }


def transcript_response(item: TranscriptRow, *, storage=None, retention_days: int = 7) -> dict:
    from .transcripts import canonical_source
    source = canonical_source(item)
    session = object_session(item)
    audio = available_audio(session, item.consultation_id, storage, retention_days) if session else None
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
        "current_text": "\n".join(segment["text"] for segment in item.segments),
        "audio_available": audio is not None,
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
        "source_transcript_revision": item.source_transcript_revision,
        "source_masked_text": item.source_masked_text,
        "evidence": item.evidence,
    }


def require_consultation(session: Session, consultation_id: str, user) -> Consultation:
    item = session.get(Consultation, consultation_id)
    if item is None or (item.created_by != user.id and user.role != "admin"):
        raise HTTPException(404, "Консультация не найдена")
    return item


def locked_consultation(session: Session, consultation_id: str, user) -> Consultation:
    item = session.scalar(select(Consultation).where(Consultation.id == consultation_id).with_for_update())
    if item is None or (item.created_by != user.id and user.role != "admin"):
        raise HTTPException(404, "Консультация не найдена")
    return item


def require_status(item: Consultation, allowed: set[str]) -> None:
    if item.status not in allowed:
        raise HTTPException(409, "Действие недоступно в текущем статусе")


def claim_write(session: Session, item: Consultation, allowed: set[str], *, expected_revision: int | None = None, processing: bool = False) -> None:
    """CAS the observed consultation before touching children on either database.

    UPDATE takes a write lock on SQLite and a retained row lock on PostgreSQL.
    The timestamp predicate also detects competing writes that retain status.
    Expire identity-map state only after winning: expire_on_commit is disabled.
    """
    statement = update(Consultation).where(
        Consultation.id == item.id, Consultation.updated_at == item.updated_at,
        Consultation.status.in_(allowed),
    )
    if expected_revision is not None:
        statement = statement.where(select(TranscriptRow.id).where(
            TranscriptRow.consultation_id == item.id, TranscriptRow.revision == expected_revision,
        ).exists())
    values = {"updated_at": now_utc()}
    if processing:
        values.update(status="PROCESSING", error_message=None)
    result = session.execute(statement.values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Консультация уже изменена")
    session.expire_all()
    session.refresh(item, with_for_update=True)


def claim_processing(session: Session, item: Consultation, allowed: set[str]) -> None:
    claim_write(session, item, allowed, processing=True)
    session.commit()
    session.expire_all()
    session.refresh(item)


def fail_processing(session: Session, consultation_id: str, message: str) -> None:
    session.execute(
        update(Consultation)
        .where(Consultation.id == consultation_id, Consultation.status == "PROCESSING")
        .values(status="FAILED", error_message=message, updated_at=now_utc())
    )
    session.commit()


def cleanup_expired_audio(session: Session, storage, retention_days: int, *, at: datetime | None = None) -> int:
    cutoff = (at or now_utc()) - timedelta(days=retention_days)
    old = session.scalars(
        select(AudioFile)
        .join(Consultation, Consultation.id == AudioFile.consultation_id)
        .where(AudioFile.created_at < cutoff, Consultation.status != "PROCESSING")
    ).all()
    count = 0
    for row in old:
        storage.delete(row.storage_key)
        session.delete(row)
        count += 1
    session.commit()
    return count
