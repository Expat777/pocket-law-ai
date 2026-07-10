"""compose_answer + терминальные узлы clarify/refuse — сборка Answer (контракт 3.1)."""

import re

from agent.deps import Deps
from agent.prompts import COMPOSE_DOC_SYSTEM, COMPOSE_SYSTEM, build_compose_prompt
from agent.state import AgentState
from shared.contracts import Answer, RetrievedChunk

# Маркер: модель вернула его, когда переданных статей не хватает для ответа.
INSUFFICIENT_MARKER = "INSUFFICIENT"
# Ловим маркер как ОТДЕЛЬНОЕ СЛОВО где угодно, а не только в начале: вопреки промпту
# «верни РОВНО одно слово» модель иногда пишет пояснение, а потом INSUFFICIENT (живой
# баг: «...статьи не по теме. INSUFFICIENT» утекал юзеру с нерелевантными цитатами).
# Латинский маркер в русском ответе естественно не встречается — ложных срабатываний нет.
_INSUFFICIENT_RE = re.compile(rf"\b{INSUFFICIENT_MARKER}\b", re.IGNORECASE)


def _is_insufficient(text: str) -> bool:
    return bool(_INSUFFICIENT_RE.search(text))

REFUSE_TEXT = (
    "Не нашёл в доступной базе законов норм, чтобы ответить на это точно. "
    "Чтобы не вводить в заблуждение, не буду отвечать наугад — уточните "
    "вопрос или обратитесь к юристу."
)

# Вопрос явно вне права (погода, рецепты, болтовня): мягко обозначаем область
# работы, а не переспрашиваем «какая сфера права» (это сбивало — заметка Роли 1).
OFFTOPIC_TEXT = (
    "Я — помощник по правовым вопросам и отвечаю только по законодательству РФ "
    "(трудовые, семейные, гражданские и другие правовые отношения). "
    "Задайте, пожалуйста, вопрос юридического характера."
)

# Doc-режим: модель вопреки промпту вернула INSUFFICIENT — литерал пользователю не
# показываем, отвечаем честно (и без цитат: чипы под «не смог разобрать» — противоречие).
DOC_UNCLEAR_TEXT = (
    "Не смог уверенно разобрать этот документ по моей базе законов. "
    "Уточните, что именно вас интересует в нём, или покажите документ юристу."
)


def _confidence(chunks: list[RetrievedChunk]) -> float:
    """Грубая оценка уверенности: средний score найденных статей закона.
    MVP-заглушка; точная «доля ответа, покрытая фрагментами» — фаза 2.
    """
    law = [c for c in chunks if c.source == "law"]
    if not law:
        return 0.0
    return round(sum(c.score for c in law) / len(law), 3)


async def _log_confidence(deps: Deps, question: str, confidence: float) -> None:
    """Телеметрия качества (схема 3.4); ошибки глушатся в impl, ответ не ломаем."""
    if deps.log_confidence is not None:
        await deps.log_confidence(question, confidence)


async def compose_answer(state: AgentState, deps: Deps) -> dict:
    chunks = state.get("verified_chunks", [])
    citations = state["citations"]

    # Консультация по присланному документу: своя структура (что это / что хотят / по
    # закону / что делать / осторожно об антифроде). Закон = основание (цитаты
    # сохраняем), но даже при скудном законе документ всё равно разбираем —
    # INSUFFICIENT-терминала тут нет (пользователь ждёт разбор письма, не отказ).
    # В промпт идёт упорядоченная голова документа (state.doc_text), а не top-K
    # похожих чанков — иначе многочанковое письмо разбиралось бы частично.
    if state.get("doc_context"):
        prompt = build_compose_prompt(
            state["question"], chunks, doc_text=state.get("doc_text", "")
        )
        text = await deps.llm.complete(COMPOSE_DOC_SYSTEM, prompt)
        stripped = text.strip()
        confidence = _confidence(chunks)
        await _log_confidence(deps, state["question"], confidence)
        # Страховка: doc-промпт маркер не просит, но если модель его вернула —
        # литерал «INSUFFICIENT» пользователю не отдаём (в т.ч. в конце пояснения).
        if _is_insufficient(stripped):
            return {
                "answer": Answer(text=DOC_UNCLEAR_TEXT, citations=[], refused=False),
                "draft_text": text,
                "confidence": 0.0,
            }
        return {
            "answer": Answer(text=stripped, citations=citations, refused=False),
            "draft_text": text,
            "confidence": confidence,
        }

    prompt = build_compose_prompt(state["question"], chunks)
    text = await deps.llm.complete(COMPOSE_SYSTEM, prompt)
    stripped = text.strip()
    confidence = _confidence(chunks)

    # Модель сама признала, что переданных статей не хватает — честный отказ БЕЗ
    # цитат (иначе бот показал бы «Основание: ст. N…» под ответом «данных
    # недостаточно» — противоречие). Ловим маркер ГДЕ УГОДНО (модель порой пишет
    # пояснение, а потом INSUFFICIENT). Ретрив-уверенность логируем: честный отказ
    # при высоком score — важный сигнал качества.
    if _is_insufficient(stripped):
        await _log_confidence(deps, state["question"], confidence)
        return {
            "answer": Answer(text=REFUSE_TEXT, citations=[], refused=True),
            "draft_text": text,
            "confidence": 0.0,
        }

    await _log_confidence(deps, state["question"], confidence)
    return {
        "answer": Answer(text=stripped, citations=citations, refused=False),
        "draft_text": text,
        "confidence": confidence,
    }


async def make_clarify(state: AgentState) -> dict:
    question = (
        "Уточните, пожалуйста, вопрос: о какой ситуации идёт речь и какая сфера "
        "права (например, трудовые отношения, договор, семейное право)?"
    )
    return {"answer": Answer(text="", citations=[], clarifying_question=question)}


async def make_refuse(state: AgentState, deps: Deps) -> dict:
    # Юр-вопрос, но проверяемых цитат нет. Логируем ретрив-уверенность сырых
    # фрагментов: отличает «ничего не нашли» от «нашли, но не подтвердилось».
    await _log_confidence(deps, state.get("question", ""), _confidence(state.get("chunks", [])))
    return {"answer": Answer(text=REFUSE_TEXT, citations=[], refused=True)}


async def make_offtopic(state: AgentState) -> dict:
    """Не-юридический вопрос: мягкий отказ по области (refused=True, без цитат)."""
    return {"answer": Answer(text=OFFTOPIC_TEXT, citations=[], refused=True)}