"""Локальные эмбеддинги для search_law().

Модель и префиксы должны совпадать с pipeline/embed.py (Роль 3): документы
кодируются как "passage: <текст>", поэтому запросы кодируются как
"query: <текст>" + normalize_embeddings=True — иначе качество поиска
заметно падает (см. STATUS.md, запись Роли 3 от 2026-07-06).
"""

import os

EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # ленивый импорт: тяжёлый

        _model = SentenceTransformer(EMBED_MODEL, device="cpu")
    return _model


def embed_query(text: str) -> list[float]:
    vector = _get_model().encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()
