"""Конфигурация пайплайна из переменных окружения (.env читает docker-compose/Makefile Роли 4)."""

import os

IPS_URL_TEMPLATE = os.getenv(
    "IPS_URL_TEMPLATE",
    "http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&page=1&rdk=0&link_id=0",
)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# Песочница Роли 3. Боевая law_articles — только в точке И2, по команде в общем чате.
QDRANT_COLLECTION = os.getenv("PIPELINE_COLLECTION", "law_articles_dev")

EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))

# Необязательно: если задан — версии статей дублируются в Postgres (law_versions, схема 3.4)
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")

# Мягкий предел размера чанка; статьи длиннее режутся по абзацам (см. chunk.py)
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "3000"))
