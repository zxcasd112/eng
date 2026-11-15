"""make telegram_id nullable for email/google users

Revision ID: 003_make_telegram_id_nullable
Revises: 002_user_cards_fields
Create Date: 2026-11-15 21:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_make_telegram_id_nullable"
down_revision: str | None = "002_user_cards_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_user:
        batch_user.alter_column("telegram_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_user:
        batch_user.alter_column("telegram_id", existing_type=sa.BigInteger(), nullable=False)
