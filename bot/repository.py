"""Репозиторий: пользователи, согласие ПДн, история диалога, rate-limit.

Пишется поверх схемы 3.4 (владелец схемы и миграций — Роль 4):
  users(user_id PK, tg_username, created_at)
  dialog_history(id PK, user_id FK, role, text, citations JSONB, created_at)

Сейчас реализация — `InMemoryRepository` (бот обязан жить автономно по DoD,
пока Postgres/миграции Роли 4 не подняты). `Repository` — Protocol, по которому
позже добавим `PostgresRepository` (asyncpg) без правок хендлеров.

Согласие 152-ФЗ Роль 4 уже заложила: `users.consent_at TIMESTAMPTZ` (NULL = согласия
ещё нет). `has_consent` → `consent_at IS NOT NULL`, `set_consent(True)` → `consent_at=now()`.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol

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
        """/delete_my_data — удалить всё о пользователе (152-ФЗ)."""
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


def build_repository(backend: str, dsn: str | None) -> Repository:
    """Фабрика по config.storage_backend. Postgres-бэкенд добавим после И0."""
    if backend == "postgres":
        raise NotImplementedError(
            "PostgresRepository подключим после И0 (миграции Роли 4). "
            "Пока запускай со STORAGE_BACKEND=memory."
        )
    return InMemoryRepository()
