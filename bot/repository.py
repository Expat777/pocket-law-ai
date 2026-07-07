"""Репозиторий: пользователи, согласие ПДн, история диалога, rate-limit.

Пишется поверх схемы 3.4 (владелец схемы и миграций — Роль 4):
  users(user_id PK, tg_username, consent_at, created_at)
  dialog_history(id PK, user_id FK, role, text, citations JSONB, created_at)

Две реализации одного `Repository`-протокола:
  - `InMemoryRepository` — дефолт, автономный запуск/юнит-тесты (без БД);
  - `PostgresRepository` (asyncpg) — прод: согласие/история/rate-limit переживают
    рестарт контейнера. Включается `STORAGE_BACKEND=postgres`.

Согласие 152-ФЗ: `users.consent_at TIMESTAMPTZ` (NULL = согласия нет).
Rate-limit считаем поверх `dialog_history` (запросы `role='user'` за час) —
отдельной таблицы в схеме 3.4 нет, новую не заводим.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from typing import Any, Protocol

from shared.contracts import Citation


class Repository(Protocol):
    async def ensure_user(self, user_id: int, tg_username: str | None) -> None: ...
    async def has_consent(self, user_id: int) -> bool: ...
    async def set_consent(self, user_id: int, granted: bool) -> None: ...
    async def delete_user_data(self, user_id: int) -> None: ...
    async def save_dialog(
        self, user_id: int, role: str, text: str, citations: list[Citation]
    ) -> None: ...
    async def check_rate_limit(
        self, user_id: int, limit_per_hour: int
    ) -> "RateDecision": ...


class RateDecision:
    """Результат проверки лимита. `allowed=False` → бот вежливо отказывает."""

    __slots__ = ("allowed", "remaining", "retry_after_sec")

    def __init__(self, allowed: bool, remaining: int, retry_after_sec: int) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_sec = retry_after_sec


_WINDOW_SEC = 3600


class InMemoryRepository:
    """Хранилище в памяти процесса. Данные теряются при рестарте — это ок для MVP-демо.

    Реализует тот же интерфейс, что будущий PostgresRepository.
    """

    def __init__(self) -> None:
        self._usernames: dict[int, str | None] = {}
        self._consent: set[int] = set()
        self._dialog: dict[int, list[dict]] = defaultdict(list)
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    async def ensure_user(self, user_id: int, tg_username: str | None) -> None:
        self._usernames[user_id] = tg_username

    async def has_consent(self, user_id: int) -> bool:
        return user_id in self._consent

    async def set_consent(self, user_id: int, granted: bool) -> None:
        if granted:
            self._consent.add(user_id)
        else:
            self._consent.discard(user_id)

    async def delete_user_data(self, user_id: int) -> None:
        """/delete — удалить всё о пользователе (152-ФЗ)."""
        self._consent.discard(user_id)
        self._usernames.pop(user_id, None)
        self._dialog.pop(user_id, None)
        self._hits.pop(user_id, None)

    async def save_dialog(
        self, user_id: int, role: str, text: str, citations: list[Citation]
    ) -> None:
        self._dialog[user_id].append(
            {
                "role": role,
                "text": text,
                "citations": [c.model_dump(mode="json") for c in citations],
                "created_at": time.time(),
            }
        )

    async def check_rate_limit(
        self, user_id: int, limit_per_hour: int
    ) -> RateDecision:
        now = time.monotonic()
        hits = self._hits[user_id]
        # выкинуть отметки старше окна
        while hits and now - hits[0] >= _WINDOW_SEC:
            hits.popleft()

        if len(hits) >= limit_per_hour:
            retry = int(_WINDOW_SEC - (now - hits[0])) + 1
            return RateDecision(False, 0, max(retry, 1))

        hits.append(now)
        return RateDecision(True, limit_per_hour - len(hits), 0)


class PostgresRepository:
    """Постоянное хранилище на asyncpg поверх схемы 3.4 (таблицы — Роли 4).

    Тот же интерфейс, что у InMemoryRepository, но состояние переживает рестарт.
    Пул соединений создаётся фабрикой `create_repository` и передаётся сюда.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ensure_user(self, user_id: int, tg_username: str | None) -> None:
        await self._pool.execute(
            """
            INSERT INTO users (user_id, tg_username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET tg_username = EXCLUDED.tg_username
            """,
            user_id,
            tg_username,
        )

    async def has_consent(self, user_id: int) -> bool:
        row = await self._pool.fetchval(
            "SELECT consent_at IS NOT NULL FROM users WHERE user_id = $1", user_id
        )
        return bool(row)

    async def set_consent(self, user_id: int, granted: bool) -> None:
        # upsert: пользователь может ещё не существовать
        await self._pool.execute(
            """
            INSERT INTO users (user_id, consent_at) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET consent_at = EXCLUDED.consent_at
            """,
            user_id,
            _now_utc() if granted else None,
        )

    async def delete_user_data(self, user_id: int) -> None:
        """/delete — полное удаление данных пользователя (152-ФЗ). FK: сначала диалог."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM dialog_history WHERE user_id = $1", user_id
                )
                await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)

    async def save_dialog(
        self, user_id: int, role: str, text: str, citations: list[Citation]
    ) -> None:
        payload = json.dumps([c.model_dump(mode="json") for c in citations])
        await self._pool.execute(
            """
            INSERT INTO dialog_history (user_id, role, text, citations)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            user_id,
            role,
            text,
            payload,
        )

    async def check_rate_limit(
        self, user_id: int, limit_per_hour: int
    ) -> RateDecision:
        # счётчик поверх dialog_history: сколько вопросов (role='user') за последний час
        row = await self._pool.fetchrow(
            """
            SELECT count(*) AS c, min(created_at) AS oldest
            FROM dialog_history
            WHERE user_id = $1 AND role = 'user'
              AND created_at > now() - interval '1 hour'
            """,
            user_id,
        )
        count = row["c"] or 0
        if count >= limit_per_hour and row["oldest"] is not None:
            elapsed = (_now_utc() - row["oldest"]).total_seconds()
            retry = int(_WINDOW_SEC - elapsed) + 1
            return RateDecision(False, 0, max(retry, 1))
        # текущий запрос будет записан хендлером через save_dialog
        return RateDecision(True, max(limit_per_hour - count - 1, 0), 0)

    async def close(self) -> None:
        await self._pool.close()


def _now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def create_repository(backend: str, dsn: str | None) -> Repository:
    """Фабрика по config.storage_backend. Пул asyncpg создаётся здесь (async)."""
    if backend == "postgres":
        if not dsn:
            raise RuntimeError("STORAGE_BACKEND=postgres, но POSTGRES-DSN пуст")
        import asyncpg

        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        return PostgresRepository(pool)
    return InMemoryRepository()
