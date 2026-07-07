"""Создание коллекций Qdrant по схеме 3.3 из TEAM_PLAN.md."""

import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))  # intfloat/multilingual-e5-base

COLLECTIONS = ["law_articles", "user_documents", "law_articles_dev"]


def main() -> None:
    client = QdrantClient(url=QDRANT_URL)
    for name in COLLECTIONS:
        if client.collection_exists(name):
            existing_dim = client.get_collection(name).config.params.vectors.size
            if existing_dim == EMBED_DIM:
                print(f"уже существует: {name}")
                continue
            # Смена модели эмбеддингов (иная размерность вектора) — старые точки
            # несовместимы, пересоздаём. Данные нужно перезалить заново (Роль 3).
            print(f"пересоздаю {name}: размерность {existing_dim} -> {EMBED_DIM}")
            client.delete_collection(name)
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        print(f"создана коллекция: {name}")


if __name__ == "__main__":
    main()
