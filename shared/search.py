"""Реализация search_law() — задача 9 Роли 4 (TEAM_PLAN, раздел 4).

Гибридный поиск: law_articles всегда + user_documents этого user_id, если задан.
Коллекции создаются заранее через infra/init_qdrant.py (схема 3.3).
"""

import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from .contracts import RetrievedChunk
from .embeddings import embed_query

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# До точки И2 (TEAM_PLAN, раздел 5) боевых данных в law_articles ещё нет —
# переключить на песочницу Роли 3 через .env: QDRANT_LAW_COLLECTION=law_articles_dev
LAW_COLLECTION = os.getenv("QDRANT_LAW_COLLECTION", "law_articles")
USER_DOCS_COLLECTION = "user_documents"

TOP_K_LAW = 10  # Роль 3 (STATUS.md, 2026-07-06): топ-3 не всегда содержит нужную статью
TOP_K_USER_DOCS = 3

_client: AsyncQdrantClient | None = None


def _get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=QDRANT_URL)
    return _client


async def search_law(
    query: str,
    user_id: int | None,
    acts: list[str] | None = None,
    doc_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """acts: сузить поиск до этих значений `act` (мультикодексная база, Роль 2/3).
    doc_ids: сузить user_documents до этих doc_id (скоуп «искать по документу N», Роль 2).

    Оба фильтра серверные (Qdrant), а не пост-фактум в Python: иначе top-K уже вырезан
    по всей базе и до нужного акта/документа могло не хватить места (см. STATUS.md, Роль 2 —
    client-side фильтр в agent/nodes/retrieve.py как временная затычка до этого для acts).
    Пусто/None — не фильтруем (текущее поведение, полная обратная совместимость).
    """
    vector = embed_query(query)
    client = _get_client()

    results: list[RetrievedChunk] = []

    law_filter = (
        Filter(must=[FieldCondition(key="act", match=MatchAny(any=acts))]) if acts else None
    )
    law_hits = await client.query_points(
        collection_name=LAW_COLLECTION,
        query=vector,
        query_filter=law_filter,
        limit=TOP_K_LAW,
    )
    for hit in law_hits.points:
        payload = hit.payload or {}
        results.append(
            RetrievedChunk(
                text=payload["text"],
                source="law",
                act=payload.get("act"),
                article=payload.get("article_no"),
                status=payload.get("status"),
                effective_date=payload.get("effective_date"),
                source_url=payload.get("source_url"),
                score=hit.score,
            )
        )

    if user_id is not None:
        user_must = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
        if doc_ids:
            user_must.append(FieldCondition(key="doc_id", match=MatchAny(any=doc_ids)))
        user_hits = await client.query_points(
            collection_name=USER_DOCS_COLLECTION,
            query=vector,
            query_filter=Filter(must=user_must),
            limit=TOP_K_USER_DOCS,
        )
        for hit in user_hits.points:
            payload = hit.payload or {}
            results.append(
                RetrievedChunk(
                    text=payload["text"],
                    source="user_doc",
                    doc_id=payload.get("doc_id"),
                    score=hit.score,
                )
            )

    results.sort(key=lambda c: c.score, reverse=True)
    return results
