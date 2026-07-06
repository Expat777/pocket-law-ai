"""Состояние графа LangGraph (Роль 2).

Один проход графа: вопрос пользователя -> intent -> retrieve -> verify ->
(compose | clarify | refuse). Узлы возвращают частичные обновления этого dict.
"""

from typing import TypedDict

from shared.contracts import Answer, Citation, RetrievedChunk


class AgentState(TypedDict, total=False):
    # вход
    user_id: int | None
    question: str

    # intent_classifier
    normalized_query: str
    branch_of_law: str | None
    is_legal: bool

    # retrieve
    chunks: list[RetrievedChunk]

    # verify
    verified_chunks: list[RetrievedChunk]
    citations: list[Citation]

    # compose
    draft_text: str
    confidence: float

    # выход (контракт 3.1)
    answer: Answer