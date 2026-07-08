"""Создание коллекций Qdrant по схеме 3.3 из TEAM_PLAN.md."""

import os

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))  # intfloat/multilingual-e5-base

COLLECTIONS = ["law_articles", "user_documents", "law_articles_dev"]
# Мультикодексная база (Роль 2/3): search_law(acts=[...]) фильтрует по этому полю —
# без индекса Qdrant делает полный скан payload при каждом фильтрованном запросе.
LAW_COLLECTIONS = {"law_articles", "law_articles_dev"}


def main() -> None:
    client = QdrantClient(url=QDRANT_URL)
    for name in COLLECTIONS:
        if client.collection_exists(name):
            existing_dim = client.get_collection(name).config.params.vectors.size
            if existing_dim == EMBED_DIM:
                print(f"уже существует: {name}")
            else:
                # Смена модели эмбеддингов (иная размерность вектора) — старые точки
                # несовместимы, пересоздаём. Данные нужно перезалить заново (Роль 3).
                print(f"пересоздаю {name}: размерность {existing_dim} -> {EMBED_DIM}")
                client.delete_collection(name)
                client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
                )
                print(f"создана коллекция: {name}")
        else:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
            )
            print(f"создана коллекция: {name}")

        if name in LAW_COLLECTIONS:
            # idempotent: повторный вызов на уже проиндексированном поле не ломает и не дублирует.
            client.create_payload_index(
                collection_name=name, field_name="act", field_schema=PayloadSchemaType.KEYWORD
            )
            print(f"payload-индекс act: {name}")

        if name == "user_documents":
            # search_law(user_id) фильтрует всегда, doc_ids — при скоупе на документ (Роль 2);
            # без индекса Qdrant делает полный скан payload на каждый запрос.
            # user_id хранится как int (agent/ingest.py), doc_id — как str(uuid4()).
            client.create_payload_index(
                collection_name=name, field_name="user_id", field_schema=PayloadSchemaType.INTEGER
            )
            client.create_payload_index(
                collection_name=name, field_name="doc_id", field_schema=PayloadSchemaType.KEYWORD
            )
            print(f"payload-индекс user_id/doc_id: {name}")


if __name__ == "__main__":
    main()
