"""retrieve: гибридный поиск статей через search_law (Роль 4) + отбор top-K."""

from agent.config import MIN_LAW_SCORE, TOP_K
from agent.deps import Deps
from agent.state import AgentState


async def retrieve(state: AgentState, deps: Deps) -> dict:
    from agent.tracing import tool_span

    query = state.get("normalized_query") or state["question"]
    with tool_span("search_law", {"query": query, "user_id": state.get("user_id")}) as record:
        chunks = await deps.search_law(query, state.get("user_id"))
        record([f"{c.act or c.source} {c.article or ''}".strip() for c in chunks])

    # отсев совсем слабых совпадений закона; документы пользователя не режем
    filtered = [
        c for c in chunks if c.source != "law" or c.score >= MIN_LAW_SCORE
    ]
    # search_law уже отсортировал по score; берём запас (см. config.TOP_K)
    return {"chunks": filtered[:TOP_K]}