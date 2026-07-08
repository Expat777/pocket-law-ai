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

# acts: сузить поиск до значений `act` (мультикодексная база); None — по всем.
# doc_ids: сузить user_documents до этих doc_id (скоуп «искать по документу N»); None — все.
SearchLaw = Callable[
    [str, int | None, list[str] | None, list[str] | None],
    Awaitable[list[RetrievedChunk]],
]
VerifyCitation = Callable[[Citation], Awaitable[CitationStatus]]
LogConfidence = Callable[[str, float], Awaitable[None]]


@dataclass
class Deps:
    llm: LLMClient
    search_law: SearchLaw
    verify_citation: VerifyCitation
    # необязательная телеметрия: запись confidence в Postgres (None = не пишем)
    log_confidence: LogConfidence | None = None


def build_default_deps() -> Deps:
    """Боевые зависимости. LLM поднимет ошибку, пока провайдер не подключён —
    для прогонов без реального провайдера собирайте Deps вручную с FakeLLMClient.
    """
    from shared.search import search_law

    from .confidence_log import log_confidence
    from .llm import build_llm
    from .tools.verify_citation import verify_citation

    return Deps(
        llm=build_llm(),
        search_law=search_law,
        verify_citation=verify_citation,
        log_confidence=log_confidence,
    )