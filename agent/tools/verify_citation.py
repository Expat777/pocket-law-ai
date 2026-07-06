"""Инструмент verify_citation (Роль 2): существует ли статья и действует ли редакция.

Проверяем по коллекции законов в Qdrant (метаданные act/article_no/status/
effective_date, схема 3.3). Коллекция та же, что читает search_law — задаётся
QDRANT_LAW_COLLECTION (до И2 — law_articles_dev).
"""

import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from shared.contracts import Citation, CitationStatus

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
LAW_COLLECTION = os.getenv("QDRANT_LAW_COLLECTION", "law_articles")

_client: AsyncQdrantClient | None = None


def _get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=QDRANT_URL)
    return _client


async def verify_citation(citation: Citation) -> CitationStatus:
    client = _get_client()
    points, _ = await client.scroll(
        collection_name=LAW_COLLECTION,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="act", match=MatchValue(value=citation.act)),
                FieldCondition(key="article_no", match=MatchValue(value=citation.article)),
            ]
        ),
        limit=1,
        with_payload=True,
    )
    if not points:
        return CitationStatus(exists=False, active=False)

    payload = points[0].payload or {}
    status = payload.get("status")
    active = status in (None, "active")  # действующей считаем active или без метки
    return CitationStatus(
        exists=True, active=active, current_revision=payload.get("effective_date")
    )