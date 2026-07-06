"""Точка входа бота (задача MVP 1): long polling для разработки (webhook — фаза 2).

Запуск:
    export BOT_TOKEN=...          # токен от @BotFather
    python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import Config, load_config
from bot.handlers import commands_router, content_router
from bot.middlewares import ConsentMiddleware, RateLimitMiddleware
from bot.mock_agent import MockAgent
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
    agent = MockAgent()  # ← в точке И1 заменяется реальным клиентом из agent/

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

    bot = Bot(token=config.bot_token)
    await _set_commands(bot)
    logging.getLogger(__name__).info("Bot started (long polling, mock agent)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
