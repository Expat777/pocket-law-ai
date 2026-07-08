"""Быстрый путь по номеру статьи (Роль 2).

Когда пользователь явно называет статью («ст. 158 УК», «статья 20.20 КоАП»),
семантика не нужна — берём фрагменты статьи прямым фильтром по (act, article_no)
из `law_articles`. Точность 100%, не зависит от лексического разрыва dense-поиска.

Только чтение чужой (Роль 3/4) коллекции закона — как в agent/documents.py для
user_documents. `search_law` (Роль 4) не трогаем: это отдельный, опциональный путь.
"""

import os

from shared.contracts import RetrievedChunk

# Та же коллекция и дефолт, что у shared/search.py (на сервере — law_articles_dev).
LAW_COLLECTION = os.getenv("QDRANT_LAW_COLLECTION", "law_articles")
# score-«маяк»: у точного попадания по номеру приоритет над семантикой.
EXACT_MATCH_SCORE = 1.0


def _default_client():
    from qdrant_client import AsyncQdrantClient

    return AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


async def lookup_articles(
    acts: list[str], article_nos: list[str], *, client=None
) -> list[RetrievedChunk]:
    """Фрагменты статей с точными (act, article_no). Пусто/ошибка -> [] (не падаем)."""
    if not acts or not article_nos:
        return []
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    client = client or _default_client()
    flt = Filter(
        must=[
            FieldCondition(key="act", match=MatchAny(any=list(acts))),
            FieldCondition(key="article_no", match=MatchAny(any=list(article_nos))),
        ]
    )
    out: list[RetrievedChunk] = []
    offset = None
    try:
        while True:
            points, offset = await client.scroll(
                collection_name=LAW_COLLECTION,
                scroll_filter=flt,
                limit=64,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                pl = p.payload or {}
                out.append(
                    RetrievedChunk(
                        text=pl["text"],
                        source="law",
                        act=pl.get("act"),
                        article=pl.get("article_no"),
                        status=pl.get("status"),
                        effective_date=pl.get("effective_date"),
                        source_url=pl.get("source_url"),
                        score=EXACT_MATCH_SCORE,
                    )
                )
            if offset is None:
                break
    except Exception:  # noqa: BLE001 — нет коллекции/сети: тихо пропускаем fast-path
        return []
    return out