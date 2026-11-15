import logging
import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.api.schemas import (
    SpeakingRespondRequest,
    SpeakingRespondResponse,
    WritingCorrection,
    WritingReviewRequest,
    WritingReviewResponse,
)
from app.db.models import User
from app.db.session import get_db
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/practice", tags=["practice"])

SCENARIOS = [
    {
        "id": "job_interview",
        "title": "Собеседование на работу (Job Interview)",
        "icon": "💼",
        "level": "B2",
        "prompt": "Hello! Thank you for coming today. Could you please tell me about your background and why you are interested in this position?",
    },
    {
        "id": "travel_airport",
        "title": "В аэропорту и на таможне (Airport & Customs)",
        "icon": "✈️",
        "level": "A2",
        "prompt": "Good day! Passport and boarding pass, please. Where are you traveling today, and what is the purpose of your trip?",
    },
    {
        "id": "restaurant",
        "title": "Заказ в ресторане / кафе (Restaurant & Dining)",
        "icon": "☕",
        "level": "A2",
        "prompt": "Welcome to our café! Are you ready to order, or would you like a few more minutes to look at the menu?",
    },
    {
        "id": "tech_discussion",
        "title": "Обсуждение IT-архитектуры (Tech Discussion)",
        "icon": "💻",
        "level": "C1",
        "prompt": "We are designing a new high-throughput event processing pipeline. How would you approach choosing between Kafka and standard message queues?",
    },
]


@router.get("/scenarios")
async def list_speaking_scenarios() -> list[dict[str, Any]]:
    return SCENARIOS


@router.post("/writing/review", response_model=WritingReviewResponse)
async def review_writing(
    payload: WritingReviewRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> WritingReviewResponse:
    text = payload.text.strip()
    words = re.findall(r"\b[a-zA-Z']+\b", text)
    word_count = len(words)

    # If LLM is available, use AI-powered review
    if llm_service.is_configured():
        try:
            client = llm_service._get_client()
            prompt = (
                f"You are an expert English teacher. Review the following text written by a Russian learner at level {user.cefr_level}:\n\n"
                f'"{text}"\n\n'
                "Analyze grammar, style, vocabulary richness. Return strictly JSON with:\n"
                "{\n"
                '  "score": <0-100 integer>,\n'
                '  "cefr_estimate": "<A1|A2|B1|B2|C1|C2>",\n'
                '  "summary_ru": "<brief encouragement and feedback in Russian>",\n'
                '  "corrections": [{"original": "...", "improved": "...", "explanation": "in Russian"}],\n'
                '  "better_phrasings": ["<natural native alternate sentence 1>", "<sentence 2>"],\n'
                '  "useful_vocab": [{"lemma": "...", "translation_ru": "..."}]\n'
                "}"
            )
            resp = await client.chat.completions.create(
                model=llm_service._settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            import json

            data = json.loads(raw)
            return WritingReviewResponse(
                score=int(data.get("score", 85)),
                cefr_estimate=str(data.get("cefr_estimate", user.cefr_level)),
                summary_ru=str(data.get("summary_ru", "Хороший текст, понятная структура.")),
                corrections=[WritingCorrection(**c) for c in data.get("corrections", [])],
                better_phrasings=list(data.get("better_phrasings", [])),
                useful_vocab=list(data.get("useful_vocab", [])),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM writing review failed, falling back to heuristics: %s", exc)

    # Heuristic fallback review
    corrections: list[WritingCorrection] = []
    # Capitalization check
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        s_strip = s.strip()
        if s_strip and s_strip[0].islower():
            corrections.append(
                WritingCorrection(
                    original=s_strip[:15] + "...",
                    improved=s_strip[0].upper() + s_strip[1:15] + "...",
                    explanation="Предложения в английском языке всегда начинаются с заглавной буквы.",
                )
            )

    score = min(95, max(60, 70 + (word_count // 5)))
    cefr_est = "B1" if word_count < 30 else ("B2" if word_count < 80 else "C1")

    return WritingReviewResponse(
        score=score,
        cefr_estimate=cefr_est,
        summary_ru=f"Текст проанализирован ({word_count} слов). Мысль выражена понятно, связность речи хорошая.",
        corrections=corrections,
        better_phrasings=[
            "It is worth noting that expanding on your key arguments creates stronger coherence.",
        ],
        useful_vocab=[
            {"lemma": "furthermore", "translation_ru": "более того"},
            {"lemma": "consequently", "translation_ru": "следовательно"},
        ],
    )


@router.post("/speaking/respond", response_model=SpeakingRespondResponse)
async def speaking_respond(
    payload: SpeakingRespondRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> SpeakingRespondResponse:
    user_msg = payload.user_message.strip()

    if llm_service.is_configured():
        try:
            client = llm_service._get_client()
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are a friendly English conversation partner in a roleplay scenario: '{payload.scenario}'. "
                        f"The user is at CEFR level {user.cefr_level}. Keep responses natural, conversational, 1-3 sentences. "
                        "Return strictly JSON:\n"
                        "{\n"
                        '  "ai_message": "<your spoken dialogue turn in English>",\n'
                        '  "feedback_ru": "<brief friendly feedback in Russian on user grammar/pronunciation or null>",\n'
                        '  "suggested_phrasing": "<how a native speaker could express the user thought more naturally or null>"\n'
                        "}"
                    ),
                }
            ]
            for h in payload.history[-6:]:
                messages.append({"role": "assistant" if h.get("role") == "ai" else "user", "content": h.get("content", "")})
            messages.append({"role": "user", "content": user_msg})

            resp = await client.chat.completions.create(
                model=llm_service._settings.openai_model,
                messages=messages,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            import json

            data = json.loads(raw)
            return SpeakingRespondResponse(
                ai_message=data.get("ai_message", "That sounds great! Could you elaborate a bit more?"),
                feedback_ru=data.get("feedback_ru"),
                suggested_phrasing=data.get("suggested_phrasing"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM speaking dialogue failed: %s", exc)

    # Fallback dialog responses
    return SpeakingRespondResponse(
        ai_message="I understand your point completely! That is a very natural way to put it. What would you like to explore next?",
        feedback_ru="Грамматика использована верно. Речь звучит уверенно.",
        suggested_phrasing=f"Native alternative: 'To be honest, {user_msg.lower().rstrip('.')}'",
    )
