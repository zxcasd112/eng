"""add source, status, notes to cards and email to users

Revision ID: 002_user_cards_fields
Revises: 001_initial_schema
Create Date: 2026-11-15 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_user_cards_fields"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_user:
        batch_user.add_column(sa.Column("email", sa.String(length=255), nullable=True))
        batch_user.create_index("ix_users_email", ["email"], unique=True)

    with op.batch_alter_table("cards") as batch_card:
        batch_card.add_column(
            sa.Column("source", sa.String(length=32), server_default="bot", nullable=False)
        )
        batch_card.add_column(
            sa.Column("status", sa.String(length=32), server_default="learning", nullable=False)
        )
        batch_card.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_card.create_index("ix_cards_status", ["status"], unique=False)
        batch_card.create_index("ix_cards_source", ["source"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("cards") as batch_card:
        batch_card.drop_index("ix_cards_source")
        batch_card.drop_index("ix_cards_status")
        batch_card.drop_column("notes")
        batch_card.drop_column("status")
        batch_card.drop_column("source")

    with op.batch_alter_table("users") as batch_user:
        batch_user.drop_index("ix_users_email")
        batch_user.drop_column("email")
