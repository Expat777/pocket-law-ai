"""Граф LangGraph Роли 2 и публичный API для бота (контракт 3.1).

Граф: intent_classifier -> retrieve -> verify -> {compose | clarify | refuse}.
answer_question / ingest_document — ровно то, что зовёт Роль 1.
"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from shared.contracts import Answer, IngestResult

from .config import GRAPH_RECURSION_LIMIT, MAX_QUESTION_CHARS
from .deps import Deps, build_default_deps
from .nodes import (
    compose_answer,
    intent_classifier,
    make_clarify,
    make_refuse,
    retrieve,
    route_after_verify,
    verify,
)
from .state import AgentState

# Страховка бюджета: жёсткий потолок шагов графа за один вызов.
INVOKE_CONFIG = {"recursion_limit": GRAPH_RECURSION_LIMIT}


def initial_state(user_id: int, text: str) -> dict:
    """Стартовое состояние с обрезкой длины вопроса (защита input-токенов)."""
    return {"user_id": user_id, "question": (text or "")[:MAX_QUESTION_CHARS]}


def build_graph(deps: Deps):
    """Собирает и компилирует граф с внедрёнными зависимостями."""
    g = StateGraph(AgentState)

    g.add_node("intent", partial(intent_classifier, deps=deps))
    g.add_node("retrieve", partial(retrieve, deps=deps))
    g.add_node("verify", partial(verify, deps=deps))
    g.add_node("compose", partial(compose_answer, deps=deps))
    g.add_node("clarify", make_clarify)
    g.add_node("refuse", make_refuse)

    g.add_edge(START, "intent")
    g.add_edge("intent", "retrieve")
    g.add_edge("retrieve", "verify")
    g.add_conditional_edges(
        "verify",
        route_after_verify,
        {"compose": "compose", "clarify": "clarify", "refuse": "refuse"},
    )
    g.add_edge("compose", END)
    g.add_edge("clarify", END)
    g.add_edge("refuse", END)

    return g.compile()


async def answer_question(
    user_id: int, text: str, deps: Deps | None = None
) -> Answer:
    """Контракт 3.1: вопрос пользователя -> Answer с цитатами/уточнением/отказом."""
    deps = deps or build_default_deps()
    graph = build_graph(deps)
    final = await graph.ainvoke(initial_state(user_id, text), config=INVOKE_CONFIG)
    return final["answer"]


async def ingest_document(
    user_id: int, file_bytes: bytes, mime: str
) -> IngestResult:
    """Контракт 3.1: разбор загруженного документа в user_documents."""
    from .ingest import ingest_document as _ingest

    return await _ingest(user_id, file_bytes, mime)