"""Store immutable issued PDFs without changing historical approved data."""
from alembic import op
import sqlalchemy as sa

revision = "0004_export_artifacts"
down_revision = "0003_trust_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("export_artifacts",
        sa.Column("public_id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("consultation_documents.id"), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("document_id", "document_version"))


def downgrade():
    op.drop_table("export_artifacts")
