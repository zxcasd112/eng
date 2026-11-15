from unittest.mock import AsyncMock, patch

import pytest

from app.api.main import create_app
from app.config import get_settings


@pytest.mark.asyncio
async def test_integrated_bot_lifecycle_started_and_stopped(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_valid_token_structure")
    monkeypatch.setenv("RUN_BOT_IN_API", "true")
    monkeypatch.setenv("FORCE_INTEGRATED_BOT_TEST", "1")
    get_settings.cache_clear()

    mock_polling = AsyncMock()
    mock_stop_polling = AsyncMock()
    mock_close = AsyncMock()

    with (
        patch("aiogram.Dispatcher.start_polling", mock_polling),
        patch("aiogram.Dispatcher.stop_polling", mock_stop_polling),
        patch("aiogram.client.session.aiohttp.AiohttpSession.close", mock_close),
    ):
        app = create_app()
        async with app.router.lifespan_context(app):
            pass

        # After exiting lifespan context, lifespan startup and shutdown were executed
        mock_polling.assert_called_once()
        mock_stop_polling.assert_called_once()


@pytest.mark.asyncio
async def test_integrated_bot_disabled_when_flag_false(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_valid_token_structure")
    monkeypatch.setenv("RUN_BOT_IN_API", "false")
    monkeypatch.setenv("FORCE_INTEGRATED_BOT_TEST", "1")
    get_settings.cache_clear()

    mock_polling = AsyncMock()
    with patch("aiogram.Dispatcher.start_polling", mock_polling):
        app = create_app()
        async with app.router.lifespan_context(app):
            pass

        mock_polling.assert_not_called()
