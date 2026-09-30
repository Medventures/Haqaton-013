from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import AudioFile, Consultation, DocumentRow, TranscriptRow, now_utc


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def consultation_response(item: Consultation) -> dict:
    return {
        "id": item.id,
        "external_patient_id": item.external_patient_id,
        "template_id": item.template_id,
        "status": item.status,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "approved_at": iso(item.approved_at),
        "error_message": item.error_message,
    }


def transcript_response(item: TranscriptRow) -> dict:
    return {
        "raw_text": item.raw_text,
        "normalized_text": item.normalized_text,
        "masked_text": item.masked_text,
        "language": item.language,
        "duration_seconds": item.duration_seconds,
        "stt_model": item.stt_model,
        "segments": item.segments,
        "pii_entities": item.pii_entities,
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


def claim_processing(session: Session, item: Consultation, allowed: set[str]) -> None:
    result = session.execute(
        update(Consultation)
        .where(Consultation.id == item.id, Consultation.status.in_(allowed))
        .values(status="PROCESSING", updated_at=now_utc(), error_message=None)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Консультация уже обрабатывается")
    session.commit()


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
