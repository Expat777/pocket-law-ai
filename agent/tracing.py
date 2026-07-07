"""Дев-трейсинг вложенных спанов (LangSmith).

LangGraph трейсит только узлы графа; наш LLM-клиент и инструменты (search_law,
verify_citation) — обычные функции, поэтому не всплывают отдельными спанами.
Эти хелперы добавляют их как вложенные LLM/tool-спаны.

Безопасно: если LANGSMITH_TRACING не включён — ПОЛНЫЙ no-op (ничего не создаётся,
ничего не уходит в облако). В inputs кладём только то, что передали (без self,
без API-ключа).
"""

from contextlib import contextmanager


def _enabled() -> bool:
    try:
        from langsmith.utils import tracing_is_enabled

        return bool(tracing_is_enabled())
    except Exception:  # noqa: BLE001 — нет langsmith / любая ошибка => не трейсим
        return False


@contextmanager
def span(name: str, run_type: str, inputs: dict):
    """Вложенный спан. yield-ит record(output) для записи результата."""
    if not _enabled():
        yield lambda *a, **k: None
        return
    from langsmith import trace

    with trace(name=name, run_type=run_type, inputs=inputs) as rt:
        def record(output=None):
            try:
                rt.end(outputs={"output": output})
            except Exception:  # noqa: BLE001 — телеметрия не должна ронять запрос
                pass

        yield record


def llm_span(model: str, messages: list):
    return span(model, "llm", {"messages": messages})


def tool_span(name: str, inputs: dict):
    return span(name, "tool", inputs)