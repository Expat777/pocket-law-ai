"""Эмбеддинги пользовательских документов.

Модель и префиксы ОБЯЗАНЫ совпадать с корпусом законов (Роль 3), иначе поиск по
user_documents молча ломается: другая размерность вектора -> upsert падает, а при
совпадающей размерности, но разном префиксе -> тихо просаженное качество.

Поэтому единый источник правды — shared.embeddings: берём оттуда И модель
(тот же кэшированный инстанс, без второй загрузки bge-m3 в память), И имя
EMBED_MODEL. Префикс для passage выводим той же логикой, что query-префикс там:
e5-модели требуют "passage: ", bge-m3 — без префикса.
"""

from shared import embeddings as _shared_emb


def _passage_prefix(model: str) -> str:
    return "passage: " if "e5" in model.lower() else ""


def embed_passages(texts: list[str]) -> list[list[float]]:
    prefix = _passage_prefix(_shared_emb.EMBED_MODEL)
    vectors = _shared_emb._get_model().encode(
        [f"{prefix}{t}" for t in texts], normalize_embeddings=True
    )
    return [v.tolist() for v in vectors]