"""Add transcript revisions, document provenance, and processing runs.

Revision ID: 0003_trust_workflow
Revises: 0002_consultation_template
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0003_trust_workflow"
down_revision = "0002_consultation_template"
branch_labels = None
depends_on = None

JSONValue = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("transcripts", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("consultation_documents", sa.Column("source_transcript_revision", sa.Integer(), nullable=True))
    op.add_column("consultation_documents", sa.Column("evidence", JSONValue, nullable=False, server_default="[]"))
    op.add_column("consultation_documents", sa.Column("source_masked_text", sa.Text(), nullable=True))
    op.create_table(
        "transcript_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transcript_id", sa.String(36), sa.ForeignKey("transcripts.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("segments", JSONValue, nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("masked_text", sa.Text(), nullable=False),
        sa.Column("pii_entities", JSONValue, nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("transcript_id", "revision"),
    )
    op.create_index("ix_transcript_revisions_transcript_id", "transcript_revisions", ["transcript_id"])
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id"), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stages", JSONValue, nullable=False, server_default="[]"),
    )
    op.create_index("ix_processing_runs_consultation_id", "processing_runs", ["consultation_id"])

    transcripts = sa.table(
        "transcripts",
        sa.column("id", sa.String(36)),
        sa.column("stt_model", sa.String(120)),
        sa.column("segments", JSONValue),
        sa.column("normalized_text", sa.Text()),
        sa.column("masked_text", sa.Text()),
        sa.column("pii_entities", JSONValue),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    snapshots = sa.table(
        "transcript_revisions",
        sa.column("id", sa.String(36)),
        sa.column("transcript_id", sa.String(36)),
        sa.column("revision", sa.Integer()),
        sa.column("segments", JSONValue),
        sa.column("normalized_text", sa.Text()),
        sa.column("masked_text", sa.Text()),
        sa.column("pii_entities", JSONValue),
        sa.column("actor_id", sa.String(36)),
        sa.column("source", sa.String(20)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    for transcript in connection.execute(sa.select(transcripts)).mappings():
        segments = [dict(segment, id=f"seg-{index:06d}") for index, segment in enumerate(transcript["segments"], 1)]
        connection.execute(sa.update(transcripts).where(transcripts.c.id == transcript["id"]).values(segments=segments))
        connection.execute(sa.insert(snapshots).values(
            id=str(uuid5(NAMESPACE_URL, f"medhub/transcript-revision/{transcript['id']}/1")),
            transcript_id=transcript["id"],
            revision=1,
            segments=segments,
            normalized_text=transcript["normalized_text"],
            masked_text=transcript["masked_text"],
            pii_entities=transcript["pii_entities"],
            actor_id=None,
            source="demo" if transcript["stt_model"] == "demo-fixture" else "stt",
            created_at=transcript["created_at"],
        ))

    connection.execute(sa.text("""UPDATE consultation_documents
        SET source_transcript_revision = 1
        WHERE EXISTS (SELECT 1 FROM transcripts
                      WHERE transcripts.consultation_id = consultation_documents.consultation_id)"""))


def downgrade() -> None:
    op.drop_index("ix_processing_runs_consultation_id", table_name="processing_runs")
    op.drop_table("processing_runs")
    op.drop_index("ix_transcript_revisions_transcript_id", table_name="transcript_revisions")
    op.drop_table("transcript_revisions")
    op.drop_column("consultation_documents", "source_masked_text")
    op.drop_column("consultation_documents", "evidence")
    op.drop_column("consultation_documents", "source_transcript_revision")
    op.drop_column("transcripts", "revision")
