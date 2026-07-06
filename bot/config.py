"""Конфигурация бота из окружения (.env владеет Роль 4).

Пока `.env.example` от Роли 4 нет — читаем переменные, что есть, с дефолтами.
Единственная обязательная переменная для живого запуска — BOT_TOKEN.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str

    # File Handler (задача MVP 5)
    max_file_bytes: int = 20 * 1024 * 1024  # ≤ 20 МБ

    # Rate-limit (задача MVP 8)
    rate_limit_per_hour: int = 20

    # Хранилище истории/лимитов: "memory" (по умолчанию) или "postgres".
    # Postgres-бэкенд подключаем после И0, когда Роль 4 даст compose + миграции.
    storage_backend: str = "memory"
    postgres_dsn: str | None = None


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN не задан. Экспортируй токен от @BotFather:\n"
            "    export BOT_TOKEN=123456:ABC...\n"
            "(в проде переменная придёт из .env Роли 4)"
        )

    return Config(
        bot_token=token,
        max_file_bytes=int(os.getenv("MAX_FILE_BYTES", 20 * 1024 * 1024)),
        rate_limit_per_hour=int(os.getenv("RATE_LIMIT_PER_HOUR", 20)),
        storage_backend=os.getenv("STORAGE_BACKEND", "memory").strip().lower(),
        postgres_dsn=os.getenv("POSTGRES_DSN") or None,
    )
