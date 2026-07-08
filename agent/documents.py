"""Управление загруженными документами пользователя (Роль 2).

Перечисление и удаление документов в коллекции `user_documents` (её наполняет
agent/ingest.py). Изоляция по `user_id` обязательна во всех операциях.

- `list_user_documents` — для UI выбора документа (список/скоуп) у Роли 1.
- `delete_user_documents` — полноценное удаление из Qdrant (закрывает пробел
  152-ФЗ: `/delete` бота чистил только Postgres, а файлы оставались в векторной
  базе). `doc_id=None` — удалить ВСЕ документы пользователя.

Скоуп поиска по конкретному `doc_id` здесь НЕ реализован: он требует фильтра в
`search_law` (Роль 4, `shared/`) и `doc_id` в `RetrievedChunk` — оформлено как
контракт (см. STATUS). Тут — только перечисление и удаление, целиком наша зона.
"""

import os
from dataclasses import dataclass

USER_DOCS_COLLECTION = "user_documents"


@dataclass
class UserDocument:
    """Одна запись для списка документов пользователя (агрегат по doc_id)."""

    doc_id: str
    filename: str | None
    uploaded_at: str | None
    chunks: int


def _default_client():
    from qdrant_client import AsyncQdrantClient

    return AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


def _user_filter(user_id: int, doc_id: str | None = None):
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    if doc_id is not None:
        must.append(FieldCondition(key="doc_id", match=MatchValue(value=doc_id)))
    return Filter(must=must)


async def list_user_documents(user_id: int, *, client=None) -> list[UserDocument]:
    """Документы пользователя (по одному на doc_id), свежие сверху.

    Возвращает пустой список, если документов нет / коллекции ещё нет.
    """
    client = client or _default_client()
    flt = _user_filter(user_id)
    docs: dict[str, UserDocument] = {}
    offset = None
    try:
        while True:
            points, offset = await client.scroll(
                collection_name=USER_DOCS_COLLECTION,
                scroll_filter=flt,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                pl = p.payload or {}
                did = pl.get("doc_id")
                if did is None:
                    continue
                d = docs.get(did)
                if d is None:
                    docs[did] = UserDocument(
                        doc_id=did,
                        filename=pl.get("filename"),
                        uploaded_at=pl.get("uploaded_at"),
                        chunks=1,
                    )
                else:
                    d.chunks += 1
            if offset is None:
                break
    except Exception:  # noqa: BLE001 — нет коллекции/сети: пустой список, не падаем
        return []
    return sorted(docs.values(), key=lambda d: d.uploaded_at or "", reverse=True)


async def delete_user_documents(
    user_id: int, doc_id: str | None = None, *, client=None
) -> None:
    """Удаляет документы пользователя из Qdrant (изоляция по user_id).

    doc_id=None -> ВСЕ документы пользователя (полное удаление для 152-ФЗ);
    иначе — только указанный документ. Идемпотентно (нет точек -> просто no-op).
    """
    client = client or _default_client()
    await client.delete(
        collection_name=USER_DOCS_COLLECTION,
        points_selector=_user_filter(user_id, doc_id),
        wait=True,
    )