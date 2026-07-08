"""Agent — реализация AgentClient (контракт 3.1) для бота.

Точка интеграции И1: Роль 1 заменяет `MockAgent()` на `Agent()` без правок
хендлеров (bot/agent_client.py ждёт объект с методами answer_question/
ingest_document). Граф компилируется один раз в конструкторе.
"""

from shared.contracts import Answer, IngestResult

from .deps import Deps, build_default_deps
from .documents import UserDocument
from .graph import INVOKE_CONFIG, build_graph, initial_state


class Agent:
    def __init__(self, deps: Deps | None = None) -> None:
        self._deps = deps or build_default_deps()
        self._graph = build_graph(self._deps)

    async def answer_question(
        self, user_id: int, text: str, doc_ids: list[str] | None = None
    ) -> Answer:
        """doc_ids — скоуп по выбранным документам (кнопка выбора у Роли 1);
        None/пусто = ответ по всем документам пользователя (контракт 3.1)."""
        final = await self._graph.ainvoke(
            initial_state(user_id, text, doc_ids), config=INVOKE_CONFIG
        )
        return final["answer"]

    async def ingest_document(
        self, user_id: int, file_bytes: bytes, mime: str, filename: str | None = None
    ) -> IngestResult:
        from .ingest import ingest_document as _ingest

        return await _ingest(user_id, file_bytes, mime, filename=filename)

    async def ingest_url(
        self, user_id: int, url: str, filename: str | None = None
    ) -> IngestResult:
        from .ingest import ingest_url as _ingest_url

        return await _ingest_url(user_id, url, filename=filename)

    async def list_user_documents(self, user_id: int) -> list[UserDocument]:
        """Список загруженных документов пользователя (для выбора/скоупа в боте)."""
        from .documents import list_user_documents as _list

        return await _list(user_id)

    async def delete_user_documents(
        self, user_id: int, doc_id: str | None = None
    ) -> None:
        """Удалить документы пользователя из Qdrant (doc_id=None -> все; 152-ФЗ)."""
        from .documents import delete_user_documents as _delete

        return await _delete(user_id, doc_id)