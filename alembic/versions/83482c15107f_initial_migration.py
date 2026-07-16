"""Initial migration

Revision ID: 83482c15107f
Revises:
Create Date: 2026-06-25 12:12:44.798365

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "83482c15107f"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "user_links",
        sa.Column("user_uuid", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("telegram_id", sa.BigInteger(), unique=True, nullable=False, index=True),
    )

    op.create_table(
        "user_habits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_uuid",
            UUID(as_uuid=True),
            sa.ForeignKey("user_links.user_uuid", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="pre_destruction"),
        sa.Column("category", sa.String(100), nullable=False, server_default="custom"),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("meta_kod", JSONB(), nullable=False, server_default="{}"),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("logs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "user_vector_memory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_uuid",
            UUID(as_uuid=True),
            sa.ForeignKey("user_links.user_uuid", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("embedding_vector", Vector(768), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index(
        "ix_user_vector_memory_embedding",
        "user_vector_memory",
        ["embedding_vector"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding_vector": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_user_vector_memory_embedding", table_name="user_vector_memory")
    op.drop_table("user_vector_memory")
    op.drop_table("user_habits")
    op.drop_table("user_links")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS vector")
