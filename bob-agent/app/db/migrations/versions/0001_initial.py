"""Initial schema: sites, defects, processed_messages

Revision ID: 0001
Revises:
Create Date: 2026-02-20 00:00:00.000000

Note: agent_memory (LangGraph checkpoint table) is NOT created here.
      LangGraph's PostgresSaver creates its own schema on first connection.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("document_url", sa.Text(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("training_phase", sa.String(64), server_default="", nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id"),
    )
    op.create_index("idx_sites_group_id", "sites", ["group_id"])

    op.create_table(
        "defects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("defect_id", sa.Integer(), nullable=False),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reporter", sa.String(64), nullable=True),
        sa.Column("supplier", sa.String(255), server_default="", nullable=False),
        sa.Column("location", sa.String(255), server_default="", nullable=False),
        sa.Column("image_url", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="פתוח", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "defect_id", name="uq_defects_site_defect"),
    )
    op.create_index("idx_defects_site_id", "defects", ["site_id"])
    op.create_index("idx_defects_status", "defects", ["status"])
    op.create_index("idx_defects_supplier", "defects", ["supplier"])

    op.create_table(
        "processed_messages",
        sa.Column("message_id", sa.String(128), nullable=False),
        sa.Column("group_id", sa.String(64), nullable=False),
        sa.Column(
            "processed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("idx_processed_msgs_at", "processed_messages", ["processed_at"])


def downgrade() -> None:
    op.drop_table("processed_messages")
    op.drop_table("defects")
    op.drop_table("sites")
