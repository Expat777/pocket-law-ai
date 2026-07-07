"""Запись confidence в Postgres (схема 3.4, таблица confidence_log).

Наблюдательность НЕ должна ломать ответ пользователю: при недоступной/не
настроенной БД пишем предупреждение и тихо пропускаем (после первой ошибки
отключаемся до перезапуска процесса, чтобы не добавлять задержку каждому ответу).

Конфиг из окружения: POSTGRES_DSN целиком, либо POSTGRES_{USER,PASSWORD,HOST,PORT,DB}.
"""

import asyncio
import logging
import os

log = logging.getLogger(__name__)

_pool = None
_disabled = False
_CONNECT_TIMEOUT = 3.0  # сек: не виснем на ответе, если БД недоступна


def _dsn() -> str:
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return dsn
    user = os.getenv("POSTGRES_USER", "pocketlaw")
    pwd = os.getenv("POSTGRES_PASSWORD", "pocketlaw")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "pocketlaw")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


async def _get_pool():
    global _pool
    if _pool is None:
        import asyncpg  # ленивый импорт

        _pool = await asyncio.wait_for(
            asyncpg.create_pool(dsn=_dsn(), min_size=1, max_size=4),
            timeout=_CONNECT_TIMEOUT,
        )
    return _pool


async def log_confidence(
    question: str, confidence: float, answer_id: int | None = None
) -> None:
    global _disabled
    if _disabled:
        return
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO confidence_log (question, answer_id, confidence) "
                "VALUES ($1, $2, $3)",
                question,
                answer_id,
                confidence,
            )
    except Exception as e:  # noqa: BLE001 — телеметрия не должна ронять ответ
        _disabled = True
        log.warning("confidence_log отключён (БД недоступна): %s", e)