"""Оффлайн-тесты мока агента и in-memory репозитория (без Telegram/сети)."""

import pytest

from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_mock_answer_branch_with_citation():
    ans = await MockAgent().answer_question(1, "могут ли уволить в отпуске?")
    assert not ans.refused and ans.clarifying_question is None
    assert ans.citations and ans.citations[0].article == "81"


@pytest.mark.asyncio
async def test_mock_clarify_branch():
    ans = await MockAgent().answer_question(1, "про отпуск")
    assert ans.clarifying_question is not None


@pytest.mark.asyncio
async def test_mock_refuse_branch():
    ans = await MockAgent().answer_question(1, "какая сегодня погода?")
    assert ans.refused is True and not ans.citations


@pytest.mark.asyncio
async def test_mock_ingest():
    res = await MockAgent().ingest_document(1, b"x" * 5000, "application/pdf")
    assert res.ok and res.chunks >= 1
    empty = await MockAgent().ingest_document(1, b"", "application/pdf")
    assert not empty.ok


@pytest.mark.asyncio
async def test_repo_consent_and_delete():
    repo = InMemoryRepository()
    await repo.ensure_user(7, "user")
    assert not await repo.has_consent(7)
    await repo.set_consent(7, True)
    assert await repo.has_consent(7)
    await repo.delete_user_data(7)
    assert not await repo.has_consent(7)


@pytest.mark.asyncio
async def test_repo_rate_limit_blocks_after_limit():
    repo = InMemoryRepository()
    for _ in range(3):
        d = await repo.check_rate_limit(9, limit_per_hour=3)
        assert d.allowed
    blocked = await repo.check_rate_limit(9, limit_per_hour=3)
    assert not blocked.allowed and blocked.retry_after_sec > 0
