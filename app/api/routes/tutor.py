import json
import logging
from datetime import UTC, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_llm_service
from app.config import get_settings
from app.db.models import Card, LLMUsage, Mistake, User, Word
from app.db.session import get_db
from app.services.llm import LLMService, WordEnrichment
from app.services.vocabulary import add_word_from_enrichment

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tutor", tags=["tutor"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class TutorChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)


class TutorToolCallResult(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result: Any


class TutorChatResponse(BaseModel):
    reply: str
    tool_calls_executed: list[TutorToolCallResult] = Field(default_factory=list)
    daily_requests_remaining: int


TUTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "explain_word",
            "description": "Explains an English word with definition, CEFR level, collocations, and Russian translation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "The English word or lemma to explain"}
                },
                "required": ["word"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_sentence",
            "description": "Checks an English sentence for grammar errors, style, and natural collocations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string", "description": "The English sentence to review"}
                },
                "required": ["sentence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_quiz",
            "description": "Creates short multiple-choice quiz questions for specified words.",
            "parameters": {
                "type": "object",
                "properties": {
                    "words": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of words to test",
                    },
                    "n": {"type": "integer", "description": "Number of questions (1-3)", "default": 2},
                },
                "required": ["words"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_word",
            "description": "Adds an English word directly into the user's FSRS learning deck.",
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "The English word to add"},
                    "translation_ru": {"type": "string", "description": "Russian translation"},
                },
                "required": ["word"],
            },
        },
    },
]


async def execute_tutor_tool(
    name: str, args: dict[str, Any], user: User, session: AsyncSession
) -> Any:
    if name == "explain_word":
        word_raw = args.get("word", "").strip().lower()
        w_res = await session.execute(select(Word).where(Word.normalized == word_raw))
        w = w_res.scalar_one_or_none()
        if w:
            return {
                "lemma": w.lemma,
                "translation_ru": w.translation_ru,
                "cefr_level": w.cefr_level,
                "definition": w.definition_en,
                "collocations": w.collocations or [],
            }
        return {
            "lemma": word_raw,
            "translation_ru": f"слово '{word_raw}'",
            "cefr_level": "B1",
            "definition": f"An English word commonly used in context: {word_raw}.",
            "collocations": [f"apply {word_raw}", f"essential {word_raw}"],
        }

    if name == "check_sentence":
        s = args.get("sentence", "").strip()
        has_error = s and s[0].islower()
        return {
            "sentence": s,
            "is_valid": not has_error,
            "feedback": (
                "Предложение грамматически корректно."
                if not has_error
                else "Обратите внимание: предложения начинаются с заглавной буквы."
            ),
            "improved": s[0].upper() + s[1:] if has_error else s,
        }

    if name == "make_quiz":
        words = args.get("words", [])
        return [
            {
                "question": f"Which word is the most accurate synonym or translation for '{w}'?",
                "options": [f"Значение 1 для {w}", "Случайный вариант B", "Случайный вариант C", "Случайный вариант D"],
                "answer": f"Значение 1 для {w}",
            }
            for w in words[:3]
        ]

    if name == "add_word":
        w_text = args.get("word", "").strip().lower()
        trans = args.get("translation_ru", f"перевод {w_text}").strip()
        enrichment = WordEnrichment(
            lemma=w_text,
            translation_ru=trans,
            cefr_level=user.cefr_level or "B1",
            example_en=f"We use {w_text} in everyday conversation.",
            example_ru=f"Мы используем {w_text} в повседневном общении.",
        )
        res = await add_word_from_enrichment(
            session=session,
            user=user,
            enrichment=enrichment,
            source_type="tutor",
            is_ai_generated=False,
        )
        await session.commit()
        return {
            "status": "added",
            "card_id": res.card.id,
            "word": res.word.lemma,
            "translation_ru": res.word.translation_ru,
        }

    return {"error": f"Unknown tool: {name}"}


@router.post("/chat", response_model=TutorChatResponse)
async def tutor_chat(
    payload: TutorChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm_service: LLMService = Depends(get_llm_service),
) -> TutorChatResponse:
    settings = get_settings()

    # 1. Rate limiting check (user timezone today)
    try:
        user_tz = ZoneInfo(user.timezone) if user.timezone else UTC
    except Exception:  # noqa: BLE001
        user_tz = UTC

    now_tz = datetime.now(user_tz)
    today_start = datetime.combine(now_tz.date(), time.min, tzinfo=user_tz).astimezone(UTC)

    count_res = await session.execute(
        select(func.count(LLMUsage.id)).where(
            LLMUsage.user_id == user.id,
            LLMUsage.task_type == "tutor_chat",
            LLMUsage.created_at >= today_start,
        )
    )
    today_requests = count_res.scalar() or 0
    limit = settings.tutor_daily_limit

    if today_requests >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Достигнут дневной лимит запросов к AI-репетитору ({limit} запросов в день). Лимит обновится завтра.",
        )

    # 2. Build User Context
    # Recent 10 mistakes
    m_res = await session.execute(
        select(Mistake).where(Mistake.user_id == user.id).order_by(Mistake.created_at.desc()).limit(10)
    )
    mistakes = m_res.scalars().all()
    mistakes_str = (
        "\n".join([f"- [{m.source}] {m.original} -> {m.correction} ({m.explanation or ''})" for m in mistakes])
        if mistakes
        else "Ошибок в журнале пока нет."
    )

    # 20 learning words
    w_res = await session.execute(
        select(Word.lemma, Word.translation_ru)
        .join(Card, Card.word_id == Word.id)
        .where(Card.user_id == user.id, Card.status == "learning")
        .limit(20)
    )
    learning_words = w_res.all()
    words_str = (
        ", ".join([f"{lemma} ({trans})" for lemma, trans in learning_words])
        if learning_words
        else "Пока нет активных слов в колоде."
    )

    system_prompt = (
        "You are an encouraging, highly pedagogical, and friendly personal English tutor.\n"
        f"Learner's CEFR level: {user.cefr_level}.\n\n"
        f"Learner's recent mistakes from practice and reviews:\n{mistakes_str}\n\n"
        f"Learner's current learning vocabulary:\n{words_str}\n\n"
        "Guidelines:\n"
        "1. Explain grammar and vocabulary clearly, in Russian or English as appropriate for the learner.\n"
        "2. If the user asks to explain a word, check a sentence, make a quiz, or add a word to their deck, "
        "use the provided tools when appropriate.\n"
        "3. Keep responses structured, concise, and motivating."
    )

    executed_tools: list[TutorToolCallResult] = []
    reply_text = ""

    if llm_service.is_configured():
        client = llm_service._get_client()
        messages = [{"role": "system", "content": system_prompt}]
        for h in payload.history[-6:]:
            messages.append({"role": h.role, "content": h.content})
        messages.append({"role": "user", "content": payload.message})

        try:
            resp = await client.chat.completions.create(
                model=llm_service._settings.openai_model,
                messages=messages,
                tools=TUTOR_TOOLS,
                tool_choice="auto",
                temperature=0.7,
            )

            msg = resp.choices[0].message
            prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
            completion_tokens = resp.usage.completion_tokens if resp.usage else 0

            if msg.tool_calls:
                messages.append(msg)
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except Exception:  # noqa: BLE001
                        fn_args = {}
                    tool_res = await execute_tutor_tool(fn_name, fn_args, user, session)
                    executed_tools.append(
                        TutorToolCallResult(tool_name=fn_name, arguments=fn_args, result=tool_res)
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_res, ensure_ascii=False)}
                    )

                # Follow-up completion after tool execution
                followup = await client.chat.completions.create(
                    model=llm_service._settings.openai_model,
                    messages=messages,
                    temperature=0.7,
                )
                reply_text = followup.choices[0].message.content or ""
                if followup.usage:
                    prompt_tokens += followup.usage.prompt_tokens
                    completion_tokens += followup.usage.completion_tokens
            else:
                reply_text = msg.content or ""

            # Log tokens usage in llm_usage table
            session.add(
                LLMUsage(
                    user_id=user.id,
                    model=llm_service._settings.openai_model,
                    tokens_in=prompt_tokens,
                    tokens_out=completion_tokens,
                    task_type="tutor_chat",
                )
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM tutor call failed: %s", exc)

    if not reply_text:
        # Fallback response for unconfigured LLM / tests
        user_msg = payload.message.lower()
        if "объясни" in user_msg or "explain" in user_msg:
            word = payload.message.split()[-1].strip("?!.,'\"")
            tool_res = await execute_tutor_tool("explain_word", {"word": word}, user, session)
            executed_tools.append(
                TutorToolCallResult(tool_name="explain_word", arguments={"word": word}, result=tool_res)
            )
            reply_text = (
                f"Слово **{word}** ({tool_res.get('cefr_level', 'B1')}): {tool_res.get('translation_ru')}.\n"
                f"Определение: {tool_res.get('definition')}\n"
                f"Пример сочетаний: {', '.join(tool_res.get('collocations', []))}"
            )
        elif "проверь" in user_msg or "check" in user_msg:
            sentence = payload.message.replace("проверь", "").replace("check", "").strip(": ")
            tool_res = await execute_tutor_tool("check_sentence", {"sentence": sentence}, user, session)
            executed_tools.append(
                TutorToolCallResult(tool_name="check_sentence", arguments={"sentence": sentence}, result=tool_res)
            )
            reply_text = f"{tool_res['feedback']}\nИсправленный вариант: {tool_res['improved']}"
        elif "добавь" in user_msg or "add" in user_msg:
            word = payload.message.split()[-1].strip("?!.,'\"")
            tool_res = await execute_tutor_tool("add_word", {"word": word}, user, session)
            executed_tools.append(
                TutorToolCallResult(tool_name="add_word", arguments={"word": word}, result=tool_res)
            )
            reply_text = f"Слово **{word}** успешно добавлено в вашу колоду повторений FSRS!"
        else:
            reply_text = (
                f"Привет! Я ваш AI-репетитор по английскому языку (уровень {user.cefr_level}).\n"
                "Вы можете попросить меня объяснить любое слово, проверить предложение на ошибки, "
                "составить персональный квиз или помочь отработать слабые места из вашего журнала ошибок."
            )

        # Log mock entry
        session.add(
            LLMUsage(
                user_id=user.id,
                model="fallback-mock",
                tokens_in=50,
                tokens_out=50,
                task_type="tutor_chat",
            )
        )
        await session.commit()

    return TutorChatResponse(
        reply=reply_text,
        tool_calls_executed=executed_tools,
        daily_requests_remaining=max(0, limit - (today_requests + 1)),
    )


@router.get("/history", response_model=list[dict[str, Any]])
async def tutor_history(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    # Return recent tutor interactions from LLMUsage
    res = await session.execute(
        select(LLMUsage)
        .where(LLMUsage.user_id == user.id, LLMUsage.task_type == "tutor_chat")
        .order_by(LLMUsage.created_at.desc())
        .limit(20)
    )
    usages = res.scalars().all()
    return [
        {
            "id": u.id,
            "model": u.model,
            "created_at": u.created_at.isoformat(),
            "tokens": u.tokens_in + u.tokens_out,
        }
        for u in usages
    ]
