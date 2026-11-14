from datetime import datetime

from pydantic import BaseModel, Field


class TelegramAuthPayload(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    telegram_id: int
    cefr_level: str


class AddWordRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    source_title: str | None = None


class WordOut(BaseModel):
    id: int
    lemma: str
    transcription: str | None = None
    part_of_speech: str | None = None
    cefr_level: str | None = None
    translation_ru: str
    definition_en: str | None = None
    collocations: list[str] | None = None
    synonyms: list[str] | None = None
    antonyms: list[str] | None = None
    grammar_note: str | None = None


class ExampleOut(BaseModel):
    id: int
    sentence_en: str
    sentence_ru: str | None = None


class CardOut(BaseModel):
    id: int
    card_type: str
    due_at: datetime
    state: int
    reps: int
    lapses: int
    word: WordOut
    example: ExampleOut | None = None


class AddWordResponse(BaseModel):
    created_new_card: bool
    card: CardOut


class SentenceAnalyzeRequest(BaseModel):
    sentence: str = Field(min_length=3, max_length=2000)


class ExtractedWordOut(BaseModel):
    lemma: str
    transcription: str
    part_of_speech: str
    cefr_level: str
    translation_ru: str
    definition_en: str
    collocations: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    grammar_note: str = ""
    example_en: str
    example_ru: str


class SentenceAnalyzeResponse(BaseModel):
    words: list[ExtractedWordOut]


class ReviewSubmitRequest(BaseModel):
    rating: int = Field(ge=1, le=4)
    response_time_ms: int | None = Field(default=None, ge=0)


class ReviewSubmitResponse(BaseModel):
    card_id: int
    next_due_at: datetime
    state: int
    reps: int
    lapses: int


class UserStatsResponse(BaseModel):
    total_cards: int
    due_cards: int
    reviewed_today: int
    total_reviews: int
    retention_percent: float
    streak_days: int
    card_types_breakdown: dict[str, int] = Field(default_factory=dict)


class CardTypesResponse(BaseModel):
    active_card_types: list[str]
    available_types: list[str]


class UpdateCardTypesRequest(BaseModel):
    card_types: list[str] = Field(min_length=1)


class WordExplainResponse(BaseModel):
    lemma: str
    cefr_level: str
    translation_ru: str
    grammar_rules: list[str]
    prepositions_and_patterns: list[str]
    collocations: list[str]
    synonyms_with_nuances: list[str]
    common_mistakes: list[str]
    examples: list[str]


class MultipleChoiceQuizOut(BaseModel):
    quiz_id: str
    word_id: int
    lemma: str
    context_sentence: str | None = None
    options: list[str]
    cefr_level: str | None = None


class MultipleChoiceAnswerRequest(BaseModel):
    quiz_id: str
    chosen_option: str


class MultipleChoiceAnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    lemma: str


class SentenceScrambleQuizOut(BaseModel):
    quiz_id: str
    word_id: int
    original_sentence: str
    translation_ru: str | None = None
    shuffled_tokens: list[str]


class SentenceScrambleAnswerRequest(BaseModel):
    quiz_id: str
    submitted_sentence: str


class SentenceScrambleAnswerResponse(BaseModel):
    is_correct: bool
    original_sentence: str
    translation_ru: str | None = None


class MatchingQuizOut(BaseModel):
    quiz_id: str
    shuffled_en: list[str]
    shuffled_ru: list[str]


class MatchingAnswerRequest(BaseModel):
    quiz_id: str
    en_word: str
    ru_translation: str


class MatchingAnswerResponse(BaseModel):
    is_match: bool
    en_word: str
    ru_translation: str
