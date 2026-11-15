# ENG Tutor — Cognitive English Learning Platform (FSRS + NestJS Design)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/zxcasd112/eng)

Общий бэкенд на **FastAPI** + веб-приложение в стиле NestJS + Telegram-бот на **aiogram 3** для изучения английских слов и устойчивых выражений с алгоритмом интервального повторения **FSRS** (`fsrs`), 7 уроками зависимых предлогов, кэшированием ответов LLM и озвучкой TTS.

## Что уже реализовано (Этап 0 + Этап 1)

- **База данных (SQLAlchemy Async + Alembic):** `users`, `sources`, `words`, `examples`, `cards` (состояние FSRS), `reviews`, `llm_cache`. Поддержка PostgreSQL (`asyncpg`) и локального SQLite (`aiosqlite`) для быстрого старта.
- **Кэширование LLM и TTS:** ответы OpenAI-совместимой LLM кэшируются в таблице `llm_cache`, аудиофайлы кэшируются в `data/audio/` и по `telegram_file_id`.
- **FSRS (`py-fsrs`):** расчёт интервалов для оценок «Не знаю / Сложно / Знаю / Легко» и превью интервалов на кнопках.
- **Общий API (`FastAPI`):**
  - `GET /health`
  - `POST /api/v1/auth/telegram` (проверка подписи Telegram Login Widget + выдача JWT)
  - `POST /api/v1/words` (добавление слова/фразы)
  - `POST /api/v1/sentences` (выделение новых слов из предложения)
  - `GET /api/v1/cards/due` (карточки к повторению)
  - `POST /api/v1/cards/{card_id}/review` (оценка карточки)
  - `GET /api/v1/stats` (статистика и streak)
- **Telegram-бот (`aiogram 3` + `APScheduler`):**
  - Приём слова/фразы → перевод, транскрипция IPA, уровень CEFR, пример и аудиопроизношение.
  - Приём предложения из книги/статьи → выделение новых для пользователя слов с кнопками добавления.
  - `/review` и почасовые напоминания → активное воспоминание (сначала вопрос, затем «Показать ответ» и 4 кнопки FSRS).
  - `/stats`, `/level`, `/reminder`.

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните `TELEGRAM_BOT_TOKEN` и `OPENAI_API_KEY`:
   ```bash
   cp .env.example .env
   ```

2. (Опционально) Поднимите PostgreSQL через Docker Compose и укажите в `.env` `DATABASE_URL=postgresql+asyncpg://eng_user:eng_password@localhost:5432/eng_tutor`:
   ```bash
   docker compose up -d
   ```
   *(Без Docker по умолчанию используется локальный SQLite `./data/eng.db`.)*

3. Установите зависимости через `uv`:
   ```bash
   uv sync
   ```

4. Запустите API-сервер:
   ```bash
   uv run uvicorn app.api.main:app --reload
   ```

5. Запустите Telegram-бота (в отдельном терминале):
   ```bash
   uv run python -m app.bot
   ```

## Тесты и линтер

```bash
uv run pytest
uv run ruff check app tests
```
