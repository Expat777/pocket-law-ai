"""intent_classifier: нормализация вопроса и определение отрасли права (1 LLM-вызов)."""

import json

from agent.config import acts_for_branches
from agent.deps import Deps
from agent.prompts import INTENT_SYSTEM
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
            "branch_of_law": None,
            "candidate_acts": [],
            "is_legal": False,
        }

    raw = await deps.llm.complete(INTENT_SYSTEM, question)
    parsed = _parse(raw)
    # branches: список отраслей (новый формат); "branch" — старый одиночный (совместимость)
    branches = parsed.get("branches")
    if not isinstance(branches, list):
        branches = [parsed["branch"]] if parsed.get("branch") else []
    acts = acts_for_branches([b for b in branches if isinstance(b, str)])
    return {
        "normalized_query": parsed.get("normalized") or question,
        "branch_of_law": branches[0] if branches else None,
        "candidate_acts": acts,
        # при неразборчивом ответе считаем вопрос юридическим — пусть решает retrieve
        "is_legal": bool(parsed.get("is_legal", True)),
    }