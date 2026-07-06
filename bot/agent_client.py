"""Интерфейс агента, который потребляет бот (контракт 3.1).

Бот зависит только от этого Protocol, а не от конкретной реализации.
На старте в него подставляется `MockAgent` (bot/mock_agent.py).
В точке И1 сюда же подставляется реальный клиент из `agent/` без правок хендлеров.
"""

from __future__ import annotations

from typing import Protocol

from bot.contracts import Answer, IngestResult


class AgentClient(Protocol):
    async def answer_question(self, user_id: int, text: str) -> Answer: ...

    async def ingest_document(
        self, user_id: int, file_bytes: bytes, mime: str
    ) -> IngestResult: ...
