import hashlib
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.db.models import Card, LLMCache, LLMUsage, SavedText, User, Word
from app.db.session import get_db
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/content", tags=["content"])


class ComprehensionQuestion(BaseModel):
    q: str
    options: list[str]
    answer: str


class NewWordItem(BaseModel):
    lemma: str
    translation_ru: str


class GenerateContentRequest(BaseModel):
    cefr_level: str | None = None
    topic: str = "Daily Life"
    word_count: int = Field(default=150, ge=50, le=800)
    format: Literal["text", "dialogue", "cloze"] = "text"
    target_words: list[str] | None = None


class GenerateContentResponse(BaseModel):
    id: int
    title: str
    text: str
    format: str
    cefr_level: str
    topic: str
    new_words: list[NewWordItem] = Field(default_factory=list)
    comprehension_questions: list[ComprehensionQuestion] = Field(default_factory=list)
    cached: bool = False


class SavedTextItem(BaseModel):
    id: int
    title: str
    cefr_level: str
    topic: str
    source_type: str
    created_at: str


def _make_content_cache_key(
    cefr: str, topic: str, word_count: int, fmt: str, target_words: list[str]
) -> str:
    raw = json.dumps(
        {
            "task": "reading_generator",
            "cefr": cefr,
            "topic": topic.strip().lower(),
            "word_count": word_count,
            "format": fmt,
            "target_words": sorted([w.strip().lower() for w in target_words]),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_fallback_content(
    cefr: str, topic: str, word_count: int, fmt: str, target_words: list[str]
) -> dict[str, Any]:
    target_str = ", ".join(target_words) if target_words else "vocabulary, practice, improve"
    if fmt == "dialogue":
        text = (
            f"Alex: Hello! Are you ready to discuss {topic} today?\n"
            f"Maria: Yes, absolutely! I was thinking about how essential it is to focus on our {target_str}.\n"
            f"Alex: Exactly. Consistent effort leads to clear progress over time, especially at CEFR {cefr} level.\n"
            f"Maria: I agree. Let us continue exploring this topic together."
        )
    elif fmt == "cloze":
        text = (
            f"Mastering English requires continuous dedication. When exploring {topic}, learners at {cefr} level "
            f"often discover new concepts. One crucial aspect is focusing on [key words] such as {target_str}. "
            f"By practicing daily, confidence and fluency grow significantly."
        )
    else:
        text = (
            f"Exploring the domain of {topic} provides valuable insights for language learners at the {cefr} level. "
            f"Developing strong communication skills involves active engagement with relevant terms like {target_str}. "
            f"Regular reading expands comprehension and helps internalize natural grammatical patterns. "
            f"Whether studying independently or in groups, staying curious about {topic} ensures sustainable improvement."
        )

    new_words = [
        {"lemma": w, "translation_ru": f"слово '{w}'"}
        for w in (target_words[:3] if target_words else ["progress", "fluency", "comprehension"])
    ]
    questions = [
        {
            "q": f"What is the central theme of this {fmt}?",
            "options": [f"Discussion on {topic}", "Cooking a meal", "Fixing a computer", "Booking a flight"],
            "answer": f"Discussion on {topic}",
        },
        {
            "q": "What contributes to long-term success according to the text?",
            "options": ["Consistent daily practice", "Stopping immediately", "Ignoring new words", "Sleeping all day"],
            "answer": "Consistent daily practice",
        },
    ]
    return {
        "title": f"Understanding {topic.capitalize()} ({cefr})",
        "text": text,
        "new_words": new_words,
        "comprehension_questions": questions,
    }


@router.post("/generate", response_model=GenerateContentResponse)
async def generate_reading_content(
    payload: GenerateContentRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> GenerateContentResponse:
    cefr = (payload.cefr_level or user.cefr_level or "B1").upper()
    topic = payload.topic.strip() or "General English"
    fmt = payload.format
    word_count = payload.word_count
    target_words = [w.strip() for w in (payload.target_words or []) if w.strip()]

    # If no target words provided, fetch up to 5 user's words currently in learning
    if not target_words:
        user_words_res = await session.execute(
            select(Word.lemma)
            .join(Card, Card.word_id == Word.id)
            .where(Card.user_id == user.id, Card.status == "learning")
            .limit(5)
        )
        target_words = list(user_words_res.scalars().all())

    cache_key = _make_content_cache_key(cefr, topic, word_count, fmt, target_words)

    # 1. Check Cache
    cached_entry = await session.execute(
        select(LLMCache).where(LLMCache.cache_key == cache_key)
    )
    cache_row = cached_entry.scalar_one_or_none()
    is_cached = False
    result_data = None

    if cache_row:
        result_data = cache_row.response_json
        is_cached = True
    elif llm_service.is_configured():
        # 2. Call LLM with 1 retry on JSON validation failure
        client = llm_service._get_client()
        prompt = (
            f"Generate an engaging English reading text strictly adapted for CEFR {cefr} level.\n"
            f"Topic: {topic}\n"
            f"Format: {fmt} (text: informative article or narrative story, dialogue: natural dialogue between characters, cloze: text with key study brackets)\n"
            f"Target length: approximately {word_count} words.\n"
            f"Target vocabulary to incorporate naturally: {', '.join(target_words) if target_words else 'none required'}.\n\n"
            "Respond ONLY with a JSON object matching this schema:\n"
            "{\n"
            '  "title": "<catchy English title>",\n'
            '  "text": "<the generated English text>",\n'
            '  "new_words": [{"lemma": "<word>", "translation_ru": "<Russian translation>"}],\n'
            '  "comprehension_questions": [\n'
            '    {\n'
            '      "q": "<question in English>",\n'
            '      "options": ["<opt A>", "<opt B>", "<opt C>", "<opt D>"],\n'
            '      "answer": "<exact matching correct option>"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        for attempt in range(2):
            try:
                resp = await client.chat.completions.create(
                    model=llm_service._settings.openai_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert English pedagogue creating level-appropriate reading exercises "
                                "with vocabulary highlights and comprehension checks."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                raw_json = resp.choices[0].message.content or "{}"
                data = json.loads(raw_json)

                # Validate required structure
                if "title" in data and "text" in data:
                    result_data = {
                        "title": str(data["title"]),
                        "text": str(data["text"]),
                        "new_words": list(data.get("new_words", [])),
                        "comprehension_questions": list(data.get("comprehension_questions", [])),
                    }
                    # Save tokens usage
                    if hasattr(resp, "usage") and resp.usage:
                        session.add(
                            LLMUsage(
                                user_id=user.id,
                                model=llm_service._settings.openai_model,
                                tokens_in=resp.usage.prompt_tokens or 0,
                                tokens_out=resp.usage.completion_tokens or 0,
                                task_type="reading_generator",
                            )
                        )
                    break
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM generation attempt %d failed: %s", attempt + 1, exc)

        if result_data:
            session.add(
                LLMCache(
                    cache_key=cache_key,
                    task_type="reading_generator",
                    model=llm_service._settings.openai_model,
                    response_json=result_data,
                )
            )
            await session.flush()

    if not result_data:
        # Fallback generator for tests/unconfigured LLM
        result_data = _get_fallback_content(cefr, topic, word_count, fmt, target_words)

    # 3. Persist to texts table
    saved_text = SavedText(
        user_id=user.id,
        title=result_data["title"],
        body=result_data["text"],
        cefr_level=cefr,
        topic=topic,
        source_type="generated",
        comprehension_questions=result_data.get("comprehension_questions"),
    )
    session.add(saved_text)
    await session.commit()
    await session.refresh(saved_text)

    new_words = [NewWordItem(**w) for w in result_data.get("new_words", [])]
    questions = [
        ComprehensionQuestion(**q) for q in result_data.get("comprehension_questions", [])
    ]

    return GenerateContentResponse(
        id=saved_text.id,
        title=saved_text.title,
        text=saved_text.body,
        format=fmt,
        cefr_level=saved_text.cefr_level,
        topic=saved_text.topic,
        new_words=new_words,
        comprehension_questions=questions,
        cached=is_cached,
    )


@router.get("/texts", response_model=list[SavedTextItem])
async def list_saved_texts(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[SavedTextItem]:
    res = await session.execute(
        select(SavedText)
        .where(SavedText.user_id == user.id)
        .order_by(SavedText.created_at.desc())
        .limit(limit)
    )
    texts = res.scalars().all()
    return [
        SavedTextItem(
            id=t.id,
            title=t.title,
            cefr_level=t.cefr_level,
            topic=t.topic,
            source_type=t.source_type,
            created_at=t.created_at.isoformat(),
        )
        for t in texts
    ]


@router.get("/texts/{text_id}", response_model=GenerateContentResponse)
async def get_saved_text(
    text_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> GenerateContentResponse:
    res = await session.execute(
        select(SavedText).where(SavedText.id == text_id, SavedText.user_id == user.id)
    )
    text = res.scalar_one_or_none()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Текст #{text_id} не найден",
        )

    questions = [
        ComprehensionQuestion(**q) for q in (text.comprehension_questions or [])
    ]

    return GenerateContentResponse(
        id=text.id,
        title=text.title,
        text=text.body,
        format="text",
        cefr_level=text.cefr_level,
        topic=text.topic,
        new_words=[],
        comprehension_questions=questions,
        cached=True,
    )
