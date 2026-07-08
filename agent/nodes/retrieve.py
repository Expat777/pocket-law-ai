"""retrieve: поиск статей через search_law (Роль 4) + отбор top-K.

Два усиления поверх семантики (обе в нашей зоне, search_law не трогаем):
- быстрый путь по номеру: «ст. 158 УК» → точный lookup мимо dense-поиска;
- квота на кодекс: при union нескольких актов — отдельный запрос на акт, чтобы
  сильный кодекс не вытеснял процессуальный из общего top-K.
"""

import asyncio
import re

from agent.config import ACT_ALIASES, MIN_LAW_SCORE, PER_CODE_QUOTA, TOP_K
from agent.deps import Deps
from agent.state import AgentState
from shared.contracts import RetrievedChunk

# Номер статьи после «ст»/«статья»: 158, 20.20, 158.1. Требуем триггер «ст…», чтобы
# не хватать любые числа («перевёл 200 тысяч»). Границы слова отсекают «стоимость».
_ART_RE = re.compile(r"\bст(?:ать[ияею]|\.)?\s*№?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)


def _parse_article_refs(text: str) -> tuple[list[str], list[str]]:
    """Пары «номер статьи + узнаваемый акт» из вопроса; иначе ([], []).

    Без акта номер неоднозначен (статья 20 есть в куче кодексов) — тогда fast-path
    не включаем, работает обычная семантика.
    """
    low = (text or "").lower()
    nos = _ART_RE.findall(low)
    if not nos:
        return [], []
    acts: list[str] = []
    for alias, act in ACT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and act not in acts:
            acts.append(act)
    if not acts:
        return [], []
    seen: dict[str, None] = {}
    for n in nos:
        seen.setdefault(n, None)
    return acts, list(seen)[:8]


def _dedup_law(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Схлопывает повторы статьи (точный lookup + семантика), оставляя макс. score."""
    best: dict[tuple, RetrievedChunk] = {}
    order: list[tuple] = []
    for c in chunks:
        k = (c.act, c.article, c.text)
        if k not in best:
            best[k] = c
            order.append(k)
        elif c.score > best[k].score:
            best[k] = c
    return [best[k] for k in order]


async def _search_with_quota(
    deps: Deps, query: str, user_id, acts, doc_ids
) -> list[RetrievedChunk]:
    """Один search_law, если акт один/нет; иначе — по запросу на акт с квотой.

    user_documents берём только на первом запросе (иначе дублировались бы N раз).
    """
    if not acts or len(acts) < 2 or PER_CODE_QUOTA <= 0:
        return await deps.search_law(query, user_id, acts or None, doc_ids)

    async def one(i: int, act: str) -> list[RetrievedChunk]:
        uid = user_id if i == 0 else None
        dids = doc_ids if i == 0 else None
        res = await deps.search_law(query, uid, [act], dids)
        law = [c for c in res if c.source == "law"][:PER_CODE_QUOTA]
        docs = [c for c in res if c.source != "law"]
        return law + docs

    parts = await asyncio.gather(*(one(i, a) for i, a in enumerate(acts)))
    return [c for part in parts for c in part]


async def retrieve(state: AgentState, deps: Deps) -> dict:
    from agent.tracing import tool_span

    query = state.get("normalized_query") or state["question"]
    # Маршрутизация по кодексу: intent назвал акты -> серверный фильтр search_law.
    # Не уверен (acts пусто) -> None -> ищем по всем кодексам (recall не теряем).
    acts = state.get("candidate_acts") or None
    doc_ids = state.get("doc_ids") or None

    # Быстрый путь: явный номер статьи в вопросе -> точный lookup (по сырому вопросу,
    # т.к. переформулировка могла убрать номер). Только пара номер+акт, иначе пропуск.
    exact: list[RetrievedChunk] = []
    if deps.lookup_articles is not None:
        ref_acts, ref_nos = _parse_article_refs(state.get("question", ""))
        if ref_acts and ref_nos:
            exact = await deps.lookup_articles(ref_acts, ref_nos)

    with tool_span(
        "search_law",
        {"query": query, "user_id": state.get("user_id"), "acts": acts, "doc_ids": doc_ids},
    ) as record:
        chunks = await _search_with_quota(deps, query, state.get("user_id"), acts, doc_ids)
        record([f"{c.act or c.source} {c.article or ''}".strip() for c in chunks])

    # top-K статей + ВСЕ фрагменты пользовательских документов (их мало, срезать
    # общим [:TOP_K] нельзя — вытеснятся статьями закона и не дойдут до compose).
    law = [c for c in chunks if c.source == "law" and c.score >= MIN_LAW_SCORE]
    user_docs = [c for c in chunks if c.source != "law"]

    # Точные попадания (fast-path) впереди семантики; дедуп повторов статьи.
    law = _dedup_law(exact + law)
    law.sort(key=lambda c: c.score, reverse=True)

    return {"chunks": law[:TOP_K] + user_docs}