"""Agent — реализация AgentClient (контракт 3.1) для бота.

Точка интеграции И1: Роль 1 заменяет `MockAgent()` на `Agent()` без правок
хендлеров (bot/agent_client.py ждёт объект с методами answer_question/
ingest_document). Граф компилируется один раз в конструкторе.
"""

from shared.contracts import Answer, IngestResult

from .deps import Deps, build_default_deps
from .graph import INVOKE_CONFIG, build_graph, initial_state


class Agent:
    def __init__(self, deps: Deps | None = None) -> None:
        self._deps = deps or build_default_deps()
        self._graph = build_graph(self._deps)

    async def answer_question(self, user_id: int, text: str) -> Answer:
        final = await self._graph.ainvoke(
            initial_state(user_id, text), config=INVOKE_CONFIG
        )
        return final["answer"]

    async def ingest_document(
        self, user_id: int, file_bytes: bytes, mime: str
    ) -> IngestResult:
        from .ingest import ingest_document as _ingest

        return await _ingest(user_id, file_bytes, mime)