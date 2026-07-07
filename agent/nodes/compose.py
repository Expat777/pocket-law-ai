"""compose_answer + терминальные узлы clarify/refuse — сборка Answer (контракт 3.1)."""

from agent.deps import Deps
from agent.prompts import COMPOSE_SYSTEM, build_compose_prompt
from agent.state import AgentState
from shared.contracts import Answer, RetrievedChunk

# Маркер: модель вернула его, когда переданных статей не хватает для ответа.
INSUFFICIENT_MARKER = "INSUFFICIENT"

REFUSE_TEXT = (
    "Не нашёл в доступной базе законов норм, чтобы ответить на это точно. "
    "Чтобы не вводить в заблуждение, не буду отвечать наугад — уточните "
    "вопрос или обратитесь к юристу."
)


def _confidence(chunks: list[RetrievedChunk]) -> float:
    """Грубая оценка уверенности: средний score найденных статей закона.
    MVP-заглушка; точная «доля ответа, покрытая фрагментами» — фаза 2.
    """
    law = [c for c in chunks if c.source == "law"]
    if not law:
        return 0.0
    return round(sum(c.score for c in law) / len(law), 3)


async def compose_answer(state: AgentState, deps: Deps) -> dict:
    chunks = state.get("verified_chunks", [])
    citations = state["citations"]
    prompt = build_compose_prompt(state["question"], chunks)
    text = await deps.llm.complete(COMPOSE_SYSTEM, prompt)
    stripped = text.strip()

    # Фикс B: модель сама признала, что переданных статей не хватает —
    # честный отказ БЕЗ цитат (иначе бот показал бы «Основание: ст. N…» под
    # ответом «данных недостаточно» — противоречие).
    if stripped.upper().startswith(INSUFFICIENT_MARKER):
        return {
            "answer": Answer(text=REFUSE_TEXT, citations=[], refused=True),
            "draft_text": text,
            "confidence": 0.0,
        }

    return {
        "answer": Answer(text=stripped, citations=citations, refused=False),
        "draft_text": text,
        "confidence": _confidence(chunks),
    }


async def make_clarify(state: AgentState) -> dict:
    question = (
        "Уточните, пожалуйста, вопрос: о какой ситуации идёт речь и какая сфера "
        "права (например, трудовые отношения, договор, семейное право)?"
    )
    return {"answer": Answer(text="", citations=[], clarifying_question=question)}


async def make_refuse(state: AgentState) -> dict:
    return {"answer": Answer(text=REFUSE_TEXT, citations=[], refused=True)}