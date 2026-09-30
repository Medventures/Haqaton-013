from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


JSONValue = JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_patient_id: Mapped[str] = mapped_column(String(200), nullable=False)
    template_id: Mapped[str] = mapped_column(String(50), nullable=False, default="therapist", server_default="therapist")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="CREATED")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(250), nullable=True)


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
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    segments: Mapped[list] = mapped_column(JSONValue, nullable=False)
    pii_entities: Mapped[list] = mapped_column(JSONValue, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TranscriptRevisionRow(Base):
    __tablename__ = "transcript_revisions"
    __table_args__ = (UniqueConstraint("transcript_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    segments: Mapped[list] = mapped_column(JSONValue, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    masked_text: Mapped[str] = mapped_column(Text, nullable=False)
    pii_entities: Mapped[list] = mapped_column(JSONValue, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=True)


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
    source_transcript_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[list] = mapped_column(JSONValue, nullable=False, default=list, server_default="[]")
    source_masked_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProcessingRunRow(Base):
    __tablename__ = "processing_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stages: Mapped[list] = mapped_column(JSONValue, nullable=False, default=list, server_default="[]")


class ConsultationEdit(Base):
    __tablename__ = "consultation_edits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_value: Mapped[object] = mapped_column(JSONValue, nullable=True)
    doctor_value: Mapped[object] = mapped_column(JSONValue, nullable=True)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AudioFile(Base):
    __tablename__ = "audio_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), unique=True, index=True)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MISExport(Base):
    __tablename__ = "mis_exports"
    __table_args__ = (UniqueConstraint("consultation_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    consultation_id: Mapped[str] = mapped_column(ForeignKey("consultations.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
