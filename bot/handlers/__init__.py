"""Роутеры бота. `commands` — команды и согласие; `content` — вопросы и файлы."""

from bot.handlers.commands import router as commands_router
from bot.handlers.content import router as content_router

__all__ = ["commands_router", "content_router"]
