"""retrieve: гибридный поиск статей через search_law (Роль 4) + отбор top-K."""

from agent.config import MIN_LAW_SCORE, TOP_K
from agent.deps import Deps
from agent.state import AgentState


async def retrieve(state: AgentState, deps: Deps) -> dict:
    from agent.tracing import tool_span

    query = state.get("normalized_query") or state["question"]
    acts = state.get("candidate_acts") or []
    with tool_span(
        "search_law", {"query": query, "user_id": state.get("user_id"), "acts": acts}
    ) as record:
        chunks = await deps.search_law(query, state.get("user_id"))
        record([f"{c.act or c.source} {c.article or ''}".strip() for c in chunks])

    # top-K статей закона (search_law уже отсортировал по score) + ВСЕ фрагменты
    # пользовательских документов. Их мало (TOP_K_USER_DOCS=3), и срезать их
    # общим [:TOP_K] нельзя: иначе при вопросе «что сказано в документе» чанки
    # файла вытесняются статьями закона и не доходят до compose как контекст.
    law = [c for c in chunks if c.source == "law" and c.score >= MIN_LAW_SCORE]
    user_docs = [c for c in chunks if c.source != "law"]

    # Мягкая маршрутизация по кодексу (мультикодексная база): intent назвал
    # отрасль(и) -> оставляем только статьи этих актов, срезая «перетекание» между
    # кодексами. Если по нужным актам в выдаче пусто (intent мог ошибиться с
    # отраслью, либо search_law ещё без серверного фильтра) — НЕ режем, чтобы не
    # терять recall (тот же принцип мягкого фолбэка, что и у переформулировки).
    if acts:
        in_acts = [c for c in law if c.act in acts]
        if in_acts:
            law = in_acts

    return {"chunks": law[:TOP_K] + user_docs}