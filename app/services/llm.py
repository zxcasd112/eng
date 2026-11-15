import hashlib
import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import LLMCache


class LLMNotConfiguredError(RuntimeError):
    """Raised when OPENAI_API_KEY is missing or unconfigured."""


class WordEnrichment(BaseModel):
    lemma: str = Field(description="Base dictionary form (lemma) in English")
    transcription: str = Field(default="", description="IPA transcription, e.g. /ˈsɪm.pəl/")
    part_of_speech: str = Field(
        default="", description="Part of speech, e.g. noun, verb, phrasal verb"
    )
    cefr_level: str = Field(default="B1", description="CEFR level: A1, A2, B1, B2, C1, or C2")
    translation_ru: str = Field(
        description="Accurate concise Russian translation (1-3 main meanings)"
    )
    definition_en: str = Field(default="", description="Simple English definition")
    collocations: list[str] = Field(
        default_factory=list, description="2-4 common collocations or idioms with this word"
    )
    synonyms: list[str] = Field(default_factory=list, description="2-4 common synonyms")
    antonyms: list[str] = Field(
        default_factory=list, description="1-3 common antonyms, if applicable"
    )
    grammar_note: str = Field(
        default="", description="Key grammatical pattern, preposition, or common pitfall"
    )
    example_en: str = Field(description="Natural English example sentence using the word")
    example_ru: str = Field(description="Natural Russian translation of the example sentence")


class SentenceExtractionResult(BaseModel):
    words: list[WordEnrichment] = Field(default_factory=list)


class WordExplanation(BaseModel):
    lemma: str = Field(description="Target lemma")
    cefr_level: str = Field(default="B1", description="CEFR level")
    translation_ru: str = Field(default="", description="Russian translation")
    grammar_rules: list[str] = Field(
        default_factory=list, description="Grammar rules and usage patterns"
    )
    prepositions_and_patterns: list[str] = Field(
        default_factory=list, description="Prepositions and dependent patterns"
    )
    collocations: list[str] = Field(
        default_factory=list, description="Key collocations and phraseological combinations"
    )
    synonyms_with_nuances: list[str] = Field(
        default_factory=list,
        description="Synonyms and explanation of differences in shades of meaning",
    )
    common_mistakes: list[str] = Field(
        default_factory=list, description="Common mistakes made by Russian-speaking learners"
    )
    examples: list[str] = Field(
        default_factory=list, description="Example sentences tailored to learner's level"
    )


class DistractorsResult(BaseModel):
    distractors: list[str] = Field(default_factory=list)


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _make_cache_key(task_type: str, model: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"task": task_type, "model": model, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMService:
    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self._settings = get_settings()
        self._client = client

    def is_configured(self) -> bool:
        key = self._settings.openai_api_key.strip()
        return bool(key) and not key.startswith("your_")

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        key = self._settings.openai_api_key.strip()
        if not key or key.startswith("your_"):
            raise LLMNotConfiguredError("OPENAI_API_KEY не настроен. Укажите ключ в файле .env.")
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=self._settings.openai_base_url,
        )
        return self._client

    async def _get_cached(self, session: AsyncSession, cache_key: str) -> dict[str, Any] | None:
        stmt = select(LLMCache).where(LLMCache.cache_key == cache_key)
        res = await session.execute(stmt)
        entry = res.scalar_one_or_none()
        return entry.response_json if entry else None

    async def _save_cache(
        self,
        session: AsyncSession,
        cache_key: str,
        task_type: str,
        model: str,
        response_json: dict[str, Any],
    ) -> None:
        existing = await session.execute(select(LLMCache).where(LLMCache.cache_key == cache_key))
        if existing.scalar_one_or_none() is not None:
            return
        session.add(
            LLMCache(
                cache_key=cache_key,
                task_type=task_type,
                model=model,
                response_json=response_json,
            )
        )
        await session.flush()

    async def enrich_word(
        self,
        session: AsyncSession,
        text: str,
        user_level: str = "B1",
    ) -> WordEnrichment:
        normalized = normalize_text(text)
        model = self._settings.openai_model
        cache_key = _make_cache_key(
            "enrich_word_v2",
            model,
            {"text": normalized, "level": user_level},
        )
        cached = await self._get_cached(session, cache_key)
        if cached is not None:
            return WordEnrichment.model_validate(cached)

        client = self._get_client()
        system_prompt = (
            "You are a precise English-Russian lexicographer and language tutor. "
            "Given an English word or short phrase, return strictly valid JSON matching the schema:\n"
            "{\n"
            '  "lemma": "...",\n'
            '  "transcription": "/.../",\n'
            '  "part_of_speech": "...",\n'
            '  "cefr_level": "A1|A2|B1|B2|C1|C2",\n'
            '  "translation_ru": "...",\n'
            '  "definition_en": "...",\n'
            '  "collocations": ["...", "..."],\n'
            '  "synonyms": ["...", "..."],\n'
            '  "antonyms": ["..."],\n'
            '  "grammar_note": "brief note on preposition or pattern",\n'
            '  "example_en": "...",\n'
            '  "example_ru": "..."\n'
            "}\n"
            f"Tailor the example sentence to CEFR level {user_level}. Keep translations concise and natural."
        )
        completion = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Word or phrase: {text.strip()}"},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        parsed = WordEnrichment.model_validate_json(content)
        await self._save_cache(
            session,
            cache_key,
            "enrich_word_v2",
            model,
            parsed.model_dump(),
        )
        return parsed

    async def extract_words_from_sentence(
        self,
        session: AsyncSession,
        sentence: str,
        user_level: str = "B1",
        max_words: int = 6,
    ) -> SentenceExtractionResult:
        normalized = normalize_text(sentence)
        model = self._settings.openai_model
        cache_key = _make_cache_key(
            "extract_sentence_v2",
            model,
            {"sentence": normalized, "level": user_level, "max_words": max_words},
        )
        cached = await self._get_cached(session, cache_key)
        if cached is not None:
            return SentenceExtractionResult.model_validate(cached)

        client = self._get_client()
        system_prompt = (
            "You are an English teacher helping a Russian-speaking learner extract useful vocabulary "
            "from a sentence taken from a book or article. "
            f"Select up to {max_words} meaningful words, phrasal verbs, or idioms worthy of study "
            f"for a learner at CEFR {user_level} (skip trivial words like 'the', 'is', 'and'). "
            "Return strictly valid JSON:\n"
            '{"words": [{\n'
            '  "lemma": "...",\n'
            '  "transcription": "/.../",\n'
            '  "part_of_speech": "...",\n'
            '  "cefr_level": "A1|A2|B1|B2|C1|C2",\n'
            '  "translation_ru": "...",\n'
            '  "definition_en": "...",\n'
            '  "collocations": ["..."],\n'
            '  "synonyms": ["..."],\n'
            '  "antonyms": ["..."],\n'
            '  "grammar_note": "...",\n'
            '  "example_en": "...",\n'
            '  "example_ru": "..."\n'
            "}]}\n"
            "Use the original sentence (or a clean slightly trimmed version of it) as example_en and translate it into Russian as example_ru."
        )
        completion = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Sentence: {sentence.strip()}"},
            ],
        )
        content = completion.choices[0].message.content or '{"words": []}'
        parsed = SentenceExtractionResult.model_validate_json(content)
        await self._save_cache(
            session,
            cache_key,
            "extract_sentence_v2",
            model,
            parsed.model_dump(),
        )
        return parsed

    async def explain_word(
        self,
        session: AsyncSession,
        text: str,
        user_level: str = "B1",
    ) -> WordExplanation:
        normalized = normalize_text(text)
        model = self._settings.openai_model
        cache_key = _make_cache_key(
            "explain_word",
            model,
            {"text": normalized, "level": user_level},
        )
        cached = await self._get_cached(session, cache_key)
        if cached is not None:
            return WordExplanation.model_validate(cached)

        client = self._get_client()
        system_prompt = (
            "You are an expert English linguist and tutor for Russian speakers. "
            "Analyze the given word or phrase in depth and return strictly valid JSON matching this schema:\n"
            "{\n"
            '  "lemma": "...",\n'
            f'  "cefr_level": "{user_level}",\n'
            '  "translation_ru": "...",\n'
            '  "grammar_rules": ["rule 1: e.g. transitive verb, countability", "rule 2"],\n'
            '  "prepositions_and_patterns": ["verb + preposition / gerund / to-inf", "..."],\n'
            '  "collocations": ["common expression 1", "common expression 2", "..."],\n'
            '  "synonyms_with_nuances": ["synonym A (more formal)", "synonym B (used in everyday speech)"],\n'
            '  "common_mistakes": ["Russian learners often confuse X with Y", "Do not say ..."],\n'
            '  "examples": ["Example sentence 1 with Russian translation", "Example 2"]\n'
            "}\n"
            f"Tailor explanations specifically to CEFR level {user_level}."
        )
        completion = await client.chat.completions.create(
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Explain this English word in detail: {text.strip()}"},
            ],
        )
        content = completion.choices[0].message.content or "{}"
        parsed = WordExplanation.model_validate_json(content)
        await self._save_cache(
            session,
            cache_key,
            "explain_word",
            model,
            parsed.model_dump(),
        )
        return parsed

    async def generate_distractors(
        self,
        session: AsyncSession,
        lemma: str,
        correct_translation: str,
        user_level: str = "B1",
        count: int = 3,
    ) -> list[str]:
        model = self._settings.openai_model
        cache_key = _make_cache_key(
            "distractors",
            model,
            {"lemma": lemma, "correct": correct_translation, "level": user_level, "count": count},
        )
        cached = await self._get_cached(session, cache_key)
        if cached is not None:
            return cached.get("distractors", [])

        client = self._get_client()
        system_prompt = (
            "You are designing a multiple-choice English vocabulary test for Russian learners. "
            f"Given an English word and its correct Russian translation, generate {count} plausible, "
            f"distinct, incorrect Russian translations (distractors) of the same part of speech and CEFR level {user_level}. "
            "The distractors must NOT be synonyms of the correct answer.\n"
            'Return strictly valid JSON: {"distractors": ["...", "...", "..."]}'
        )
        completion = await client.chat.completions.create(
            model=model,
            temperature=0.4,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"English lemma: {lemma}\nCorrect Russian translation: {correct_translation}",
                },
            ],
        )
        content = completion.choices[0].message.content or '{"distractors": []}'
        parsed = DistractorsResult.model_validate_json(content)
        await self._save_cache(
            session,
            cache_key,
            "distractors",
            model,
            parsed.model_dump(),
        )
        return parsed.distractors[:count]
