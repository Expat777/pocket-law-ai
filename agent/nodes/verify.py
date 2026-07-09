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
    from agent.tracing import tool_span

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
        with tool_span("verify_citation", {"act": c.act, "article": c.article}) as record:
            status = await deps.verify_citation(candidate)
            record({"exists": status.exists, "active": status.active})
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
                    source_url=c.source_url,
                )
            )

    return {"verified_chunks": verified, "citations": citations[:MAX_CITATIONS]}


def route_after_verify(state: AgentState) -> str:
    """Маршрутизация терминальных веток.

    Порядок важен (фикс A): сперва отсекаем неюридические вопросы — даже если
    search_law по инерции вернул ближайшие статьи, отвечать на «погоду»
    юридическим текстом с цитатами нельзя. Здесь же разводим два случая не-юр:
    пустой/невнятный ввод -> clarify («сформулируйте вопрос»); явно не-юр вопрос
    (погода, болтовня) -> offtopic (мягкий отказ по области, заметка Роли 1), а не
    переспрос про сферу права. Затем: есть проверенные цитаты -> compose; нет ->
    честный отказ.
    """
    if not state.get("is_legal", True):
        # есть ввод (вопрос или документ) но он не про право -> offtopic; совсем пусто -> clarify
        has_input = state.get("question", "").strip() or state.get("doc_context")
        return "offtopic" if has_input else "clarify"
    # Консультация по присланному документу: разбираем его, даже если проверенных
    # law-цитат нет (пользователь ждёт разбор письма, а не отказ «нет норм»).
    if state.get("doc_context") and state.get("verified_chunks"):
        return "compose"
    if state.get("citations"):
        return "compose"
    return "refuse"