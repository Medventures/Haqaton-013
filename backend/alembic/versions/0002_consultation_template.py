"""Persist selected consultation template.

Revision ID: 0002_consultation_template
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_consultation_template"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consultations",
        sa.Column("template_id", sa.String(50), nullable=False, server_default="therapist"),
    )
    op.add_column("consultations", sa.Column("approved_by", sa.String(36), nullable=True))
    op.add_column("consultations", sa.Column("approved_by_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("consultations", "approved_by_name")
    op.drop_column("consultations", "approved_by")
    op.drop_column("consultations", "template_id")
