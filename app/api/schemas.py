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
    telegram_id: int | None = None
    email: str | None = None
    cefr_level: str


class GoogleAuthPayload(BaseModel):
    credential: str = Field(min_length=10, description="Google ID Token JWT")


class EmailAuthPayload(BaseModel):
    email: str = Field(min_length=5, max_length=255, description="Gmail or email address")


class EmailSendCodeRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, description="Gmail address")


class EmailVerifyCodeRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, description="Gmail address")
    code: str = Field(min_length=4, max_length=10, description="Verification code")


class AddWordRequest(BaseModel):
    text: str | None = None
    lemma: str | None = None
    translation_ru: str | None = None
    cefr_level: str | None = None
    source_title: str | None = None
    source: str = "web"  # bot / web / reading / sentence / import


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


class ReviewOut(BaseModel):
    id: int
    card_id: int
    rating: int
    reviewed_at: datetime
    scheduled_days: int
    elapsed_days: int
    response_time_ms: int | None = None


class UserWordItemOut(BaseModel):
    id: int
    lemma: str
    translation_ru: str
    transcription: str | None = None
    part_of_speech: str | None = None
    cefr_level: str | None = None
    status: str = "learning"
    source: str = "bot"
    notes: str | None = None
    created_at: datetime
    cards_count: int = 0
    next_due_at: datetime | None = None
    total_reps: int = 0
    total_lapses: int = 0
    collocations: list[str] | None = None
    grammar_note: str | None = None


class UserWordDetailOut(BaseModel):
    id: int
    lemma: str
    normalized: str
    translation_ru: str
    transcription: str | None = None
    part_of_speech: str | None = None
    cefr_level: str | None = None
    definition_en: str | None = None
    collocations: list[str] | None = None
    synonyms: list[str] | None = None
    antonyms: list[str] | None = None
    grammar_note: str | None = None
    status: str = "learning"
    source: str = "bot"
    notes: str | None = None
    created_at: datetime
    examples: list[ExampleOut] = []
    cards: list[CardOut] = []
    reviews: list[ReviewOut] = []


class PaginatedWordsResponse(BaseModel):
    items: list[UserWordItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class UpdateWordRequest(BaseModel):
    status: str | None = None
    notes: str | None = None
    cefr_level: str | None = None


class ImportWordsResponse(BaseModel):
    added: int
    duplicates: int
    errors: list[str] = []


class UserProfileResponse(BaseModel):
    id: int
    telegram_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    email: str | None = None
    cefr_level: str
    daily_goal: int
    timezone: str
    reminder_hour: int | None = None
    active_card_types: list[str]


class UpdateProfileRequest(BaseModel):
    cefr_level: str | None = None
    daily_goal: int | None = None
    timezone: str | None = None
    reminder_hour: int | None = None
    active_card_types: list[str] | None = None
    email: str | None = None


class DailyRetentionItem(BaseModel):
    date: str
    reviews_count: int
    passed_count: int
    retention_pct: float


class CardTypeAnalyticsItem(BaseModel):
    card_type: str
    cards_count: int
    reviews_count: int
    passed_count: int
    accuracy_pct: float


class ProblemWordItem(BaseModel):
    word_id: int
    lemma: str
    translation_ru: str
    lapses: int
    again_count: int
    avg_rating: float


class DailyForecastItem(BaseModel):
    date: str
    due_cards_count: int


class DistributionBucket(BaseModel):
    range_label: str
    count: int


class ValueDistributionStats(BaseModel):
    mean: float
    min: float
    max: float
    median: float
    distribution: list[DistributionBucket] = []


class UserAnalyticsResponse(BaseModel):
    retention_30d: float
    retention_daily: list[DailyRetentionItem]
    card_types_breakdown: list[CardTypeAnalyticsItem]
    problem_words: list[ProblemWordItem]
    workload_forecast_7d: list[DailyForecastItem]
    stability_stats: ValueDistributionStats
    difficulty_stats: ValueDistributionStats
    reviewed_today: int = 0


class RecommendationItem(BaseModel):
    word: WordOut
    score: float
    reasons: list[str]


# === Writing Review & Speaking Practice Schemas ===

class WritingReviewRequest(BaseModel):
    text: str = Field(min_length=5, max_length=4000, description="English text or essay")
    topic: str | None = None


class WritingCorrection(BaseModel):
    original: str
    improved: str
    explanation: str


class WritingReviewResponse(BaseModel):
    score: int
    cefr_estimate: str
    summary_ru: str
    corrections: list[WritingCorrection] = []
    better_phrasings: list[str] = []
    useful_vocab: list[dict[str, str]] = []


class SpeakingRespondRequest(BaseModel):
    scenario: str
    history: list[dict[str, str]] = []
    user_message: str


class SpeakingRespondResponse(BaseModel):
    ai_message: str
    feedback_ru: str | None = None
    suggested_phrasing: str | None = None
