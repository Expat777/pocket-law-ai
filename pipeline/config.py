"""Конфигурация пайплайна из переменных окружения (.env читает docker-compose/Makefile Роли 4)."""

import os

IPS_URL_TEMPLATE = os.getenv(
    "IPS_URL_TEMPLATE",
    "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&page=1&rdk=0&link_id=0",
)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# Песочница Роли 3. Боевая law_articles — только в точке И2, по команде в общем чате.
QDRANT_COLLECTION = os.getenv("PIPELINE_COLLECTION", "law_articles_dev")

# Модель выбрана бенчмарком 2026-07-07 (pipeline/benchmark_embeddings.ipynb):
# на 62 житейских вопросах R@5≈0.97 / MRR≈0.89 против 0.90/0.83 у e5-large и 0.86/0.69 у e5-base.
EMBED_MODEL = os.getenv("EMBED_MODEL", "deepvk/USER-bge-m3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))  # bge-m3 = 1024; e5-base = 768
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))


def model_prefixes(model: str = EMBED_MODEL) -> tuple[str, str]:
    """(query_prefix, passage_prefix) для модели. ВАЖНО: запрос и документ надо
    кодировать ОДИНАКОВЫМ соглашением, иначе качество молча падает.
    - e5 (`multilingual-e5-*`): требует "query: " / "passage: ";
    - bge-m3 (`deepvk/USER-bge-m3`) и bge вообще: без префикса (подтверждено бенчмарком).
    Роль 4 (`shared/embeddings.py`) должна использовать тот же query-префикс.
    """
    m = model.lower()
    if "e5" in m:
        return "query: ", "passage: "
    return "", ""


QUERY_PREFIX, PASSAGE_PREFIX = model_prefixes()

# Необязательно: если задан — версии статей дублируются в Postgres (law_versions, схема 3.4)
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")

# Мягкий предел размера чанка; статьи длиннее режутся по абзацам (см. chunk.py)
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "3000"))
