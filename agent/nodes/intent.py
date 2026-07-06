"""intent_classifier: нормализация вопроса и определение отрасли права (1 LLM-вызов)."""

import json

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
    raw = await deps.llm.complete(INTENT_SYSTEM, question)
    parsed = _parse(raw)
    return {
        "normalized_query": parsed.get("normalized") or question,
        "branch_of_law": parsed.get("branch"),
        # при неразборчивом ответе считаем вопрос юридическим — пусть решает retrieve
        "is_legal": bool(parsed.get("is_legal", True)),
    }