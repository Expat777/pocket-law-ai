"""Интеграционный тест PostgresRepository против реального Postgres (схема 3.4).

Пропускается, если нет `asyncpg` или Postgres недоступен (напр. в оффлайн-CI):
тогда работает InMemory-путь, а этот тест — только там, где поднята БД.
Использует выделенный тестовый user_id и подчищает за собой (152-ФЗ delete).
"""

from datetime import date

import pytest

pytest.importorskip("asyncpg")

from bot.config import _postgres_dsn  # noqa: E402
from bot.repository import create_repository  # noqa: E402
from shared.contracts import Citation  # noqa: E402

TEST_UID = 999_000_777  # не пересекается с реальными пользователями


async def _repo_or_skip():
    try:
        return await create_repository("postgres", _postgres_dsn())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres недоступен: {exc}")


@pytest.mark.asyncio
async def test_postgres_repo_end_to_end():
    repo = await _repo_or_skip()
    try:
        await repo.delete_user_data(TEST_UID)  # чистый старт

        # согласие
        await repo.ensure_user(TEST_UID, "tester")
        assert await repo.has_consent(TEST_UID) is False
        await repo.set_consent(TEST_UID, True)
        assert await repo.has_consent(TEST_UID) is True

        # история диалога (в т.ч. цитата в JSONB)
        await repo.save_dialog(TEST_UID, "user", "вопрос 1", [])
        await repo.save_dialog(
            TEST_UID,
            "assistant",
            "ответ",
            [Citation(act="ТК РФ", article="81", revision_date=date(2024, 11, 1))],
        )
        await repo.save_dialog(TEST_UID, "user", "вопрос 2", [])

        # rate-limit поверх dialog_history: 2 вопроса за час
        blocked = await repo.check_rate_limit(TEST_UID, 2)
        assert blocked.allowed is False and blocked.retry_after_sec > 0
        allowed = await repo.check_rate_limit(TEST_UID, 10)
        assert allowed.allowed is True

        # полное удаление данных (152-ФЗ)
        await repo.delete_user_data(TEST_UID)
        assert await repo.has_consent(TEST_UID) is False
    finally:
        await repo.delete_user_data(TEST_UID)
        await repo.close()
