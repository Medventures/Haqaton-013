"""Revision transitions. Callers own the enclosing transaction and commit."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .grounding import mask_segments, normalize_segments
from .models import Consultation, DocumentRow, TranscriptRevisionRow, TranscriptRow, now_utc
from .schemas import StoredTranscriptSegment, TranscriptPatch
from .service import claim_write


def canonical_source(row: TranscriptRow):
    return mask_segments([StoredTranscriptSegment.model_validate(s) for s in row.segments], revision=row.revision)


def _snapshot(session: Session, row: TranscriptRow, *, actor_id: str | None, source: str) -> None:
    session.flush()
    session.add(TranscriptRevisionRow(
        transcript_id=row.id, revision=row.revision, segments=row.segments,
        normalized_text=row.normalized_text, masked_text=row.masked_text,
        pii_entities=row.pii_entities, actor_id=actor_id, source=source,
    ))


def _project(row: TranscriptRow, segments: list[StoredTranscriptSegment], on_stage=None) -> None:
    if on_stage:
        on_stage("normalization", "running", 1)
    normalized = normalize_segments(segments)
    if on_stage:
        on_stage("normalization", "done", 1)
        on_stage("pii_masking", "running", 1)
    source = mask_segments(segments, revision=row.revision)
    if on_stage:
        on_stage("pii_masking", "done", 1)
    row.segments = [s.model_dump(mode="json") for s in segments]
    row.normalized_text = "\n".join(s.text for s in normalized)
    row.masked_text = source.text
    row.pii_entities = [entity.model_dump(mode="json") for entity in source.entities]


def save_initial_transcript(session: Session, consultation: Consultation, transcript, *, actor_id: str | None, source: str, stt_model: str, on_stage=None) -> TranscriptRow:
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
    _project(row, segments, on_stage)
    _snapshot(session, row, actor_id=actor_id, source=source)
    return row


def edit_transcript(session: Session, consultation: Consultation, patch: TranscriptPatch, *, actor_id: str) -> TranscriptRow:
    claim_write(session, consultation, {"TRANSCRIBED", "AI_GENERATED", "REVIEWED", "FAILED"}, expected_revision=patch.expected_revision)
    row = session.scalar(select(TranscriptRow).where(TranscriptRow.consultation_id == consultation.id))
    if row is None or row.revision != patch.expected_revision:
        raise HTTPException(409, "Версия транскрипции устарела")
    changes = {change.segment_id: change.text for change in patch.changes}
    if not changes.keys() <= {segment["id"] for segment in row.segments}:
        raise HTTPException(422, "Неизвестный фрагмент транскрипции")
    segments = [StoredTranscriptSegment.model_validate({**s, "text": changes.get(s["id"], s["text"])}) for s in row.segments]
    current = "\n".join(s.text for s in segments)
    if len(current) > 500000 or not current.strip():
        raise HTTPException(422, "Некорректный текст транскрипции")
    if all(s.text == previous["text"] for s, previous in zip(segments, row.segments, strict=True)):
        return row
    row.revision += 1
    _project(row, segments)
    _snapshot(session, row, actor_id=actor_id, source="doctor")
    consultation.status = "TRANSCRIBED"
    consultation.error_message = None
    consultation.updated_at = now_utc()
    return row


def require_fresh_document(document: DocumentRow, transcript: TranscriptRow | None) -> None:
    if (transcript is None and document.source_transcript_revision is not None) or (
        transcript is not None and document.source_transcript_revision != transcript.revision
    ):
        raise HTTPException(409, "Документ устарел. Сформируйте его заново.")
