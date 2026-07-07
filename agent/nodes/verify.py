"""verify: сверка статей-кандидатов (существование + действующая редакция) и
маршрутизация insufficient_context.

Цитаты формируются ТОЛЬКО из реально найденных и проверенных статей закона —
это и есть anti-hallucination: бот не сможет сослаться на выдуманную норму.
"""

from datetime import date

from agent.config import MAX_CITATIONS
from agent.deps import Deps
from agent.state import AgentState
from shared.contracts import Citation, RetrievedChunk


async def verify(state: AgentState, deps: Deps) -> dict:
    chunks: list[RetrievedChunk] = state.get("chunks", [])
    verified: list[RetrievedChunk] = []
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for c in chunks:
        # фрагменты пользовательских документов оставляем как контекст, но не цитируем
        if c.source != "law" or not c.act or not c.article:
            verified.append(c)
            continue

        candidate = Citation(
            act=c.act,
            article=c.article,
            revision_date=c.effective_date or date.today(),
        )
        status = await deps.verify_citation(candidate)
        if not (status.exists and status.active):
            continue  # несуществующую/недействующую статью выбрасываем

        verified.append(c)
        key = (c.act, c.article)
        if key not in seen:
            seen.add(key)
            citations.append(
                Citation(
                    act=c.act,
                    article=c.article,
                    revision_date=status.current_revision or candidate.revision_date,
                )
            )

    return {"verified_chunks": verified, "citations": citations[:MAX_CITATIONS]}


def route_after_verify(state: AgentState) -> str:
    """insufficient_context?

    Порядок важен (фикс A): сперва отсекаем неюридические вопросы в clarify —
    даже если search_law по инерции вернул ближайшие статьи, отвечать на «погоду»
    юридическим текстом с цитатами нельзя. Затем: есть проверенные цитаты ->
    compose; нет -> честный отказ.
    """
    if not state.get("is_legal", True):
        return "clarify"
    if state.get("citations"):
        return "compose"
    return "refuse"