"""retrieve: гибридный поиск статей через search_law (Роль 4) + отбор top-K."""

from agent.config import MIN_LAW_SCORE, TOP_K
from agent.deps import Deps
from agent.state import AgentState


async def retrieve(state: AgentState, deps: Deps) -> dict:
    from agent.tracing import tool_span

    query = state.get("normalized_query") or state["question"]
    # Маршрутизация по кодексу: intent назвал отрасли -> канонические акты.
    # Фильтр СЕРВЕРНЫЙ (search_law(acts), Роль 4): Qdrant режет по `act` ДО top-K,
    # поэтому нужный кодекс не вытесняется соседними. Не уверен (acts пусто) ->
    # None -> ищем по всем кодексам (recall не теряем).
    acts = state.get("candidate_acts") or None
    with tool_span(
        "search_law", {"query": query, "user_id": state.get("user_id"), "acts": acts}
    ) as record:
        chunks = await deps.search_law(query, state.get("user_id"), acts)
        record([f"{c.act or c.source} {c.article or ''}".strip() for c in chunks])

    # top-K статей закона (search_law уже отсортировал по score) + ВСЕ фрагменты
    # пользовательских документов. Их мало (TOP_K_USER_DOCS=3), и срезать их
    # общим [:TOP_K] нельзя: иначе при вопросе «что сказано в документе» чанки
    # файла вытесняются статьями закона и не доходят до compose как контекст.
    law = [c for c in chunks if c.source == "law" and c.score >= MIN_LAW_SCORE]
    user_docs = [c for c in chunks if c.source != "law"]

    return {"chunks": law[:TOP_K] + user_docs}