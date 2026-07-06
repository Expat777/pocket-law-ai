"""Middlewares контент-роутера: согласие ПДн (152-ФЗ) и rate-limit.

Вешаются только на роутер с «контентом» (вопросы и файлы), поэтому команды
`/start`, `/help`, `/delete_my_data` и кнопка согласия проходят мимо них.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot.repository import Repository


class ConsentMiddleware(BaseMiddleware):
    """Без согласия на обработку ПДн бот не отвечает (задача MVP 1, 152-ФЗ)."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is not None and not await self._repo.has_consent(user.id):
            await event.answer(
                "Чтобы я мог обрабатывать ваши сообщения, нужно согласие на "
                "обработку персональных данных (152-ФЗ). Отправьте /start и "
                "нажмите «Согласен»."
            )
            return None
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """N запросов/час на пользователя, вежливый отказ при превышении (задача MVP 8)."""

    def __init__(self, repo: Repository, limit_per_hour: int) -> None:
        self._repo = repo
        self._limit = limit_per_hour

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is not None:
            decision = await self._repo.check_rate_limit(user.id, self._limit)
            if not decision.allowed:
                minutes = max(1, decision.retry_after_sec // 60)
                await event.answer(
                    f"Слишком много запросов. Лимит — {self._limit} в час. "
                    f"Попробуйте снова примерно через {minutes} мин."
                )
                return None
        return await handler(event, data)
