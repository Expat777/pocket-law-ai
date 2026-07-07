"""Точка входа бота (задача MVP 1): long polling для разработки (webhook — фаза 2).

Собирает реального агента Роли 2 (`Agent()`), поэтому для запуска нужен полный
стек: зависимости из корневого pyproject (langgraph, qdrant-client, httpx …),
доступный Qdrant и LLM-ключ Polza.ai.

Запуск:
    pip install -e ".[dev]"
    export BOT_TOKEN=...                              # токен от @BotFather
    export LLM_BASE_URL=https://api.polza.ai/api/v1
    export LLM_MODEL=anthropic/claude-sonnet-5
    export LLM_API_KEY=...                            # в проде — из .env
    python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from agent import Agent
from bot.config import Config, load_config
from bot.handlers import commands_router, content_router
from bot.middlewares import ConsentMiddleware, RateLimitMiddleware
from bot.repository import build_repository


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать и дать согласие"),
            BotCommand(command="help", description="Справка"),
            BotCommand(command="delete", description="Удалить мои данные"),
        ]
    )


def build_dispatcher(config: Config) -> Dispatcher:
    """Собирает Dispatcher: DI, middlewares, роутеры. Вынесено для тестируемости."""
    repo = build_repository(config.storage_backend, config.postgres_dsn)
    agent = Agent()  # реальный оркестратор Роли 2 (И1); граф компилируется здесь

    dp = Dispatcher(storage=MemoryStorage())

    # DI: прокидываем зависимости в хендлеры через workflow data.
    dp["repo"] = repo
    dp["agent"] = agent
    dp["config"] = config
    dp["max_file_bytes"] = config.max_file_bytes

    # Контент-роутер закрываем согласием и лимитом; команды остаются открытыми.
    content_router.message.middleware(ConsentMiddleware(repo))
    content_router.message.middleware(
        RateLimitMiddleware(repo, config.rate_limit_per_hour)
    )

    dp.include_router(commands_router)
    dp.include_router(content_router)
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    dp = build_dispatcher(config)

    # Прокси до api.telegram.org — нужен там, где хостинг режет Telegram (напр. РФ-VPS).
    # Без прокси используется прямое соединение.
    session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
    if config.telegram_proxy:
        logging.getLogger(__name__).info("Telegram через прокси: %s", config.telegram_proxy)

    # link_preview_is_disabled: не показывать карточку-превью для ссылок в цитатах
    # (source_url в блоке «Основание»), иначе Telegram цепляет крупный блок под ответ.
    bot = Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(link_preview_is_disabled=True),
    )
    await _set_commands(bot)
    logging.getLogger(__name__).info("Bot started (long polling, real agent)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
