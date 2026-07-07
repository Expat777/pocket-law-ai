"""Локальные эмбеддинги для search_law().

Модель и префикс запроса должны совпадать с тем, как pipeline/embed.py (Роль 3)
кодирует документы — иначе качество поиска молча падает. Логика префикса
продублирована из pipeline/config.py::model_prefixes() (бенчмарк 2026-07-07):
e5-модели требуют "query: "/"passage: ", bge-m3 — без префикса.
"""

import os

EMBED_MODEL = os.getenv("EMBED_MODEL", "deepvk/USER-bge-m3")


def _query_prefix(model: str) -> str:
    return "query: " if "e5" in model.lower() else ""


_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # ленивый импорт: тяжёлый

        _model = SentenceTransformer(EMBED_MODEL, device="cpu")
    return _model


def embed_query(text: str) -> list[float]:
    vector = _get_model().encode(_query_prefix(EMBED_MODEL) + text, normalize_embeddings=True)
    return vector.tolist()
