from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cefr_level: Mapped[str] = mapped_column(String(8), default="B1", nullable=False)
    daily_goal: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    reminder_hour: Mapped[int | None] = mapped_column(Integer, default=19, nullable=True)
    active_card_types: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["en_ru", "ru_en", "cloze", "audio"], nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    cards: Mapped[list["Card"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sources: Mapped[list["Source"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    url_or_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="sources")
    examples: Mapped[list["Example"]] = relationship(back_populates="source")


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lemma: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    transcription: Mapped[str | None] = mapped_column(String(255), nullable=True)
    part_of_speech: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cefr_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    translation_ru: Mapped[str] = mapped_column(Text, nullable=False)
    definition_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    collocations: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    synonyms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    antonyms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    grammar_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    examples: Mapped[list["Example"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )
    cards: Mapped[list["Card"]] = relationship(back_populates="word")


class Example(Base):
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sentence_en: Mapped[str] = mapped_column(Text, nullable=False)
    sentence_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    cefr_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    word: Mapped["Word"] = relationship(back_populates="examples")
    source: Mapped["Source | None"] = relationship(back_populates="examples")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("user_id", "word_id", "card_type", name="uq_user_word_card_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), index=True)
    example_id: Mapped[int | None] = mapped_column(
        ForeignKey("examples.id", ondelete="SET NULL"), nullable=True
    )
    card_type: Mapped[str] = mapped_column(String(16), default="en_ru", nullable=False)

    # FSRS state fields
    fsrs_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1=Learning,2=Review,3=Relearning
    reps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="cards")
    word: Mapped["Word"] = relationship(back_populates="cards")
    example: Mapped["Example | None"] = relationship()
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Again, 2=Hard, 3=Good, 4=Easy
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )
    elapsed_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scheduled_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    card: Mapped["Card"] = relationship(back_populates="reviews")
    user: Mapped["User"] = relationship(back_populates="reviews")


class LLMCache(Base):
    __tablename__ = "llm_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
