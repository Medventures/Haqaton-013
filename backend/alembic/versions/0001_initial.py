"""Initial medical scribe tables.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


JSONValue = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False))
    op.create_table("consultations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("external_patient_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.String(250)))
    op.create_index("ix_consultations_created_by", "consultations", ["created_by"])
    op.create_table("transcripts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False, unique=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("masked_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("stt_model", sa.String(120), nullable=False),
        sa.Column("segments", JSONValue, nullable=False),
        sa.Column("pii_entities", JSONValue, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index("ix_transcripts_consultation_id", "transcripts", ["consultation_id"])
    op.create_table("consultation_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False, unique=True),
        sa.Column("ai_generated_data", JSONValue, nullable=False),
        sa.Column("doctor_approved_data", JSONValue),
        sa.Column("working_data", JSONValue, nullable=False),
        sa.Column("llm_provider", sa.String(100), nullable=False),
        sa.Column("llm_model", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_index("ix_consultation_documents_consultation_id", "consultation_documents", ["consultation_id"])
    op.create_table("consultation_edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False),
        sa.Column("field", sa.String(100), nullable=False),
        sa.Column("ai_value", JSONValue),
        sa.Column("doctor_value", JSONValue),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index("ix_consultation_edits_consultation_id", "consultation_edits", ["consultation_id"])
    op.create_table("audio_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index("ix_audio_files_consultation_id", "audio_files", ["consultation_id"])
    op.create_table("mis_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False, unique=True),
        sa.Column("document_id", sa.String(255)),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index("ix_mis_exports_consultation_id", "mis_exports", ["consultation_id"])


def downgrade() -> None:
    for table in ("mis_exports", "audio_files", "consultation_edits", "consultation_documents", "transcripts", "consultations", "users"):
        op.drop_table(table)
