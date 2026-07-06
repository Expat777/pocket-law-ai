"""Эмбеддинги пользовательских документов.

Та же модель и префиксы, что у корпуса законов (Роль 3): документы кодируются
как "passage: <текст>" с normalize_embeddings=True — иначе несовместимо с
law-векторами и поиск по user_documents просядет. Модель из EMBED_MODEL.
"""

import os

EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # ленивый: тяжёлый

        _model = SentenceTransformer(EMBED_MODEL, device="cpu")
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    vectors = _get_model().encode(
        [f"passage: {t}" for t in texts], normalize_embeddings=True
    )
    return [v.tolist() for v in vectors]