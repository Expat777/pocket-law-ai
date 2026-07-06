"""upsert: запись чанков в Qdrant (по умолчанию — песочница law_articles_dev)."""

import logging

from .chunk import Chunk
from .config import QDRANT_COLLECTION, QDRANT_URL

log = logging.getLogger(__name__)


def _client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(dim: int, collection: str = QDRANT_COLLECTION) -> None:
    """Создаём только свою dev-песочницу; боевые коллекции создаёт infra/init_qdrant.py (Роль 4)."""
    from qdrant_client.models import Distance, VectorParams

    client = _client()
    if not client.collection_exists(collection):
        if not collection.endswith("_dev"):
            raise RuntimeError(
                f"Коллекции {collection} нет. Боевые коллекции создаёт Роль 4 (infra/init_qdrant.py) — "
                "пайплайн сам создаёт только *_dev."
            )
        client.create_collection(collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        log.info("Создал коллекцию %s (dim=%d, cosine)", collection, dim)


def upsert_chunks(chunks: list[Chunk], vectors: list[list[float]], collection: str = QDRANT_COLLECTION) -> None:
    from qdrant_client.models import PointStruct

    assert len(chunks) == len(vectors)
    client = _client()
    batch = 256
    for i in range(0, len(chunks), batch):
        points = [
            PointStruct(id=c.id, vector=v, payload=c.payload)
            for c, v in zip(chunks[i:i + batch], vectors[i:i + batch])
        ]
        client.upsert(collection_name=collection, points=points, wait=True)
    log.info("upsert: %d точек в %s (%s)", len(chunks), collection, QDRANT_URL)
