"""create mistakes texts llm_usage and user reminder_channel

Revision ID: 004_mistakes_texts_llm_usage
Revises: 003_make_telegram_id_nullable
Create Date: 2026-11-16 00:45:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_mistakes_texts_llm_usage"
down_revision: str | None = "003_make_telegram_id_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add reminder_channel to users
    with op.batch_alter_table("users") as batch_user:
        batch_user.add_column(
            sa.Column("reminder_channel", sa.String(16), server_default="telegram", nullable=False)
        )

    # 2. Create mistakes table
    op.create_table(
        "mistakes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["word_id"], ["words.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mistakes_user_id", "mistakes", ["user_id"], unique=False)
    op.create_index("ix_mistakes_word_id", "mistakes", ["word_id"], unique=False)
    op.create_index("ix_mistakes_source", "mistakes", ["source"], unique=False)
    op.create_index("ix_mistakes_created_at", "mistakes", ["created_at"], unique=False)

    # 3. Create texts table
    op.create_table(
        "texts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cefr_level", sa.String(length=8), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), server_default="generated", nullable=False),
        sa.Column("url_or_ref", sa.Text(), nullable=True),
        sa.Column("comprehension_questions", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_texts_user_id", "texts", ["user_id"], unique=False)
    op.create_index("ix_texts_created_at", "texts", ["created_at"], unique=False)

    # 4. Create llm_usage table
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("task_type", sa.String(length=32), server_default="chat", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"], unique=False)
    op.create_index("ix_llm_usage_task_type", "llm_usage", ["task_type"], unique=False)
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("llm_usage")
    op.drop_table("texts")
    op.drop_table("mistakes")
    with op.batch_alter_table("users") as batch_user:
        batch_user.drop_column("reminder_channel")
