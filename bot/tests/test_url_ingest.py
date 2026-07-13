"""Тесты детекта ссылки и загрузки документа по URL (задача Роли 2 — ingest_url)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import _URL_RE, _clear_scope, _scope_ids, _toggle_scope, on_url
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository
from shared.contracts import Answer, IngestResult


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
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()

    await on_url(msg, state, InMemoryRepository(), MockAgent())

    # бот ответил результатом приёма документа
    assert msg.answer.await_count == 1
    assert "принят" in msg.answer.await_args.args[0]
    # состояние вернулось в обычный режим
    assert state.set_state.await_count >= 1


@pytest.mark.asyncio
async def test_on_url_question_scoped_to_new_doc_and_clears_sticky_scope():
    """Ссылка+вопрос: отвечаем по ТОЛЬКО ЧТО загруженному документу, а не по старому скоупу."""
    uid = 1
    _clear_scope(uid)
    _toggle_scope(uid, "OLD", "старый.pdf")  # был липкий скоуп на другой файл
    agent = MagicMock()
    agent.ingest_url = AsyncMock(
        return_value=IngestResult(doc_id="NEW", chunks=3, ok=True, error=None)
    )
    agent.answer_question = AsyncMock(
        return_value=Answer(text="28 дней", citations=[], refused=False)
    )
    msg = _fake_message("https://example.com/tk.html сколько дней отпуска?")
    state = MagicMock()
    state.set_state = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()

    await on_url(msg, state, InMemoryRepository(), agent)

    # вопрос ушёл в агента со скоупом на НОВЫЙ документ, не на старый «OLD»
    agent.answer_question.assert_awaited_once()
    assert agent.answer_question.await_args.kwargs["doc_ids"] == ["NEW"]
    # прежний скоуп заменён авто-скоупом на новый документ (для follow-up вопросов)
    assert _scope_ids(uid) == ["NEW"]
    _clear_scope(uid)
