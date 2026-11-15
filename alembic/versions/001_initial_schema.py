"""initial schema with stage 2 learning core

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-14 23:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("cefr_level", sa.String(length=8), nullable=False),
        sa.Column("daily_goal", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("reminder_hour", sa.Integer(), nullable=True),
        sa.Column("active_card_types", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("url_or_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_user_id"), "sources", ["user_id"], unique=False)

    op.create_table(
        "words",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lemma", sa.String(length=255), nullable=False),
        sa.Column("normalized", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("transcription", sa.String(length=255), nullable=True),
        sa.Column("part_of_speech", sa.String(length=64), nullable=True),
        sa.Column("cefr_level", sa.String(length=8), nullable=True),
        sa.Column("translation_ru", sa.Text(), nullable=False),
        sa.Column("definition_en", sa.Text(), nullable=True),
        sa.Column("collocations", sa.JSON(), nullable=True),
        sa.Column("synonyms", sa.JSON(), nullable=True),
        sa.Column("antonyms", sa.JSON(), nullable=True),
        sa.Column("grammar_note", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.String(length=512), nullable=True),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_words_lemma"), "words", ["lemma"], unique=False)
    op.create_index(op.f("ix_words_normalized"), "words", ["normalized"], unique=True)

    op.create_table(
        "examples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("sentence_en", sa.Text(), nullable=False),
        sa.Column("sentence_ru", sa.Text(), nullable=True),
        sa.Column("cefr_level", sa.String(length=8), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["word_id"], ["words.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_examples_source_id"), "examples", ["source_id"], unique=False)
    op.create_index(op.f("ix_examples_word_id"), "examples", ["word_id"], unique=False)

    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("example_id", sa.Integer(), nullable=True),
        sa.Column("card_type", sa.String(length=16), nullable=False),
        sa.Column("fsrs_state", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=True),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("state", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["example_id"], ["examples.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["word_id"], ["words.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "word_id", "card_type", name="uq_user_word_card_type"),
    )
    op.create_index(op.f("ix_cards_due_at"), "cards", ["due_at"], unique=False)
    op.create_index(op.f("ix_cards_user_id"), "cards", ["user_id"], unique=False)
    op.create_index(op.f("ix_cards_word_id"), "cards", ["word_id"], unique=False)

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_days", sa.Integer(), nullable=False),
        sa.Column("scheduled_days", sa.Integer(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reviews_card_id"), "reviews", ["card_id"], unique=False)
    op.create_index(op.f("ix_reviews_reviewed_at"), "reviews", ["reviewed_at"], unique=False)
    op.create_index(op.f("ix_reviews_user_id"), "reviews", ["user_id"], unique=False)

    op.create_table(
        "llm_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_cache_cache_key"), "llm_cache", ["cache_key"], unique=True)
    op.create_index(op.f("ix_llm_cache_task_type"), "llm_cache", ["task_type"], unique=False)


def downgrade() -> None:
    op.drop_table("llm_cache")
    op.drop_table("reviews")
    op.drop_table("cards")
    op.drop_table("examples")
    op.drop_table("words")
    op.drop_table("sources")
    op.drop_table("users")
