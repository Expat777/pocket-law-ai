"""Контейнер зависимостей графа.

Все внешние функции внедряются, а не импортируются жёстко в узлах — так граф
тестируется на фейках без Qdrant/LLM. Боевые зависимости собирает
build_default_deps(): search_law даёт Роль 4 (shared/search.py), verify_citation
и parse_pdf — наши инструменты (agent/tools/), llm — через agent/llm.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from shared.contracts import Citation, CitationStatus, RetrievedChunk

from .llm import LLMClient

SearchLaw = Callable[[str, int | None], Awaitable[list[RetrievedChunk]]]
VerifyCitation = Callable[[Citation], Awaitable[CitationStatus]]


@dataclass
class Deps:
    llm: LLMClient
    search_law: SearchLaw
    verify_citation: VerifyCitation


def build_default_deps() -> Deps:
    """Боевые зависимости. LLM поднимет ошибку, пока провайдер не подключён —
    для прогонов без реального провайдера собирайте Deps вручную с FakeLLMClient.
    """
    from shared.search import search_law

    from .llm import build_llm
    from .tools.verify_citation import verify_citation

    return Deps(llm=build_llm(), search_law=search_law, verify_citation=verify_citation)