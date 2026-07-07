"""Тесты детекта ссылки и загрузки документа по URL (задача Роли 2 — ingest_url)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import _URL_RE, on_url
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository


def test_url_regex_extracts_first_url():
    assert _URL_RE.search("https://pravo.gov.ru/doc.pdf").group(0) == "https://pravo.gov.ru/doc.pdf"
    assert _URL_RE.search("http://a.b/c?x=1 хвост").group(0) == "http://a.b/c?x=1"
    assert _URL_RE.search("нет ссылки") is None


@pytest.mark.asyncio
async def test_mock_ingest_url():
    ok = await MockAgent().ingest_url(1, "https://example.com/dogovor.pdf")
    assert ok.ok and ok.chunks >= 1
    bad = await MockAgent().ingest_url(1, "ftp://nope")
    assert not bad.ok


def _fake_message(text: str):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=1, username="u")
    msg.chat = MagicMock(id=1)
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_on_url_ingests_and_replies():
    msg = _fake_message("https://example.com/dogovor.pdf")
    state = MagicMock()
    state.set_state = AsyncMock()

    await on_url(msg, state, InMemoryRepository(), MockAgent())

    # бот ответил результатом приёма документа
    assert msg.answer.await_count == 1
    assert "принят" in msg.answer.await_args.args[0]
    # состояние вернулось в обычный режим
    assert state.set_state.await_count >= 1
