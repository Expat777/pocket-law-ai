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
from aiogram.types import BotCommand, ErrorEvent

from agent import Agent
from bot.config import Config, load_config
from bot.handlers import commands_router, content_router
from bot.middlewares import ConsentMiddleware, RateLimitMiddleware
from bot.repository import Repository, create_repository


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать и дать согласие"),
            BotCommand(command="help", description="Справка"),
            BotCommand(command="delete", description="Удалить мои данные"),
        ]
    )


def build_dispatcher(config: Config, repo: Repository) -> Dispatcher:
    """Собирает Dispatcher: DI, middlewares, роутеры. Вынесено для тестируемости.

    `repo` создаётся снаружи (в `main`), т.к. Postgres-пул поднимается асинхронно.
    """
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

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        """Сеть-безопасности: логируем любую необработанную ошибку и не роняем бота."""
        logging.getLogger(__name__).exception(
            "Необработанная ошибка обновления", exc_info=event.exception
        )
        msg = getattr(event.update, "message", None)
        if msg is not None:
            try:
                await msg.answer("Упс, произошла ошибка. Попробуйте ещё раз чуть позже.")
            except Exception:  # noqa: BLE001 — ответ пользователю best-effort
                pass
        return True  # ошибка обработана, продолжаем polling

    dp.include_router(commands_router)
    dp.include_router(content_router)
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    repo = await create_repository(config.storage_backend, config.postgres_dsn)
    logging.getLogger(__name__).info("Хранилище: %s", config.storage_backend)
    dp = build_dispatcher(config, repo)

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
    try:
        await dp.start_polling(bot)
    finally:
        close = getattr(repo, "close", None)
        if close is not None:
            await close()  # закрыть пул asyncpg (для Postgres-бэкенда)


if __name__ == "__main__":
    asyncio.run(main())
