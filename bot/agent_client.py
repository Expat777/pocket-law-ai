"""Интерфейс агента, который потребляет бот (контракт 3.1).

Бот зависит только от этого Protocol, а не от конкретной реализации.
В проде подставляется `agent.Agent` (Роль 2, подключён в И1); `bot.mock_agent.MockAgent`
остаётся реализацией того же контракта для юнит-тестов бота без LLM/Qdrant.
"""

from __future__ import annotations

from typing import Protocol

from shared.contracts import Answer, IngestResult


class AgentClient(Protocol):
    async def answer_question(self, user_id: int, text: str) -> Answer: ...

    async def ingest_document(
        self, user_id: int, file_bytes: bytes, mime: str
    ) -> IngestResult: ...

    async def ingest_url(self, user_id: int, url: str) -> IngestResult: ...
