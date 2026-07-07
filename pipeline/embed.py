"""embed: локальные эмбеддинги sentence-transformers (без внешних API).

Префиксы зависят от модели (см. config.model_prefixes): у e5 — "passage:"/"query:",
у текущей bge-m3 — без префикса. Кто пишет search_law (Роль 4/shared) должен
кодировать запрос ТЕМ ЖЕ префиксом (config.QUERY_PREFIX), иначе качество молча падает.
"""

import logging

from .config import EMBED_BATCH_SIZE, EMBED_MODEL, PASSAGE_PREFIX

log = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # ленивый импорт: тяжёлый
        log.info("Загружаю модель эмбеддингов %s (первый раз скачает веса ~1 ГБ)", EMBED_MODEL)
        _model = SentenceTransformer(EMBED_MODEL, device="cpu")
    return _model


def embedding_dim() -> int:
    return _get_model().get_sentence_embedding_dimension()


def embed_passages(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    prefixed = [f"{PASSAGE_PREFIX}{t}" for t in texts]
    vectors = model.encode(
        prefixed,
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return [v.tolist() for v in vectors]
