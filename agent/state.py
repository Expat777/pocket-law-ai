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
    # скоуп поиска по документам: если задан — искать только в этих doc_id
    # (кнопка выбора документа у Роли 1); пусто/нет = по всем документам пользователя
    doc_ids: list[str]

    # intent_classifier
    normalized_query: str
    # запрос для ретрива: normalized + HyDE-текст (если включён), иначе = normalized
    retrieval_query: str
    branch_of_law: str | None
    # канонические акты-кандидаты для фильтра retrieve (пусто = искать по всем кодексам)
    candidate_acts: list[str]
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