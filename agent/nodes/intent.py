"""intent_classifier: нормализация вопроса, отрасль права и (опц.) HyDE-текст.

При AGENT_HYDE intent и генерация HyDE идут ПАРАЛЛЕЛЬНО (оба зависят только от
вопроса) — латентность не растёт, а retrieval_query = normalized + HyDE лечит
лексический разрыв dense-поиска (см. agent/config.HYDE_ENABLED).
"""

import asyncio
import json

from agent.config import HYDE_ENABLED, acts_for_branches
from agent.deps import Deps
from agent.prompts import HYDE_SYSTEM, INTENT_SYSTEM
from agent.state import AgentState


def _parse(raw: str) -> dict:
    """Толерантный разбор JSON из ответа LLM (вырезаем первый {...})."""
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


async def intent_classifier(state: AgentState, deps: Deps) -> dict:
    question = state["question"]
    # guard: пустой/пробельный ввод не шлём в LLM (некоторые API отвечают 400) —
    # сразу помечаем неюридическим, роутер уведёт в clarify.
    if not question.strip():
        return {
            "normalized_query": "",
            "retrieval_query": "",
            "branch_of_law": None,
            "candidate_acts": [],
            "is_legal": False,
        }

    # intent обязателен; HyDE — опционально и параллельно (его сбой не должен ронять
    # ответ: тогда просто ищем по обычной переформулировке).
    if HYDE_ENABLED:
        raw, hyde = await asyncio.gather(
            deps.llm.complete(INTENT_SYSTEM, question),
            deps.llm.complete(HYDE_SYSTEM, question),
            return_exceptions=True,
        )
        if isinstance(raw, BaseException):
            raise raw
        hyde_text = hyde if isinstance(hyde, str) else ""
    else:
        raw = await deps.llm.complete(INTENT_SYSTEM, question)
        hyde_text = ""

    parsed = _parse(raw)
    # branches: список отраслей (новый формат); "branch" — старый одиночный (совместимость)
    branches = parsed.get("branches")
    if not isinstance(branches, list):
        branches = [parsed["branch"]] if parsed.get("branch") else []
    acts = acts_for_branches([b for b in branches if isinstance(b, str)])
    normalized = parsed.get("normalized") or question
    return {
        "normalized_query": normalized,
        # вопрос+HyDE вместе (замер: фьюжн бьёт HyDE-only и не роняет рабочие кейсы)
        "retrieval_query": f"{normalized}. {hyde_text}" if hyde_text.strip() else normalized,
        "branch_of_law": branches[0] if branches else None,
        "candidate_acts": acts,
        # при неразборчивом ответе считаем вопрос юридическим — пусть решает retrieve
        "is_legal": bool(parsed.get("is_legal", True)),
    }