"""Скоуп поиска по документу: выбор/сброс через пикер + проброс doc_ids в агента."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import (
    _clear_scope,
    _get_scope,
    _set_scope,
    on_question,
    on_scope_select,
)
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository
from shared.contracts import Answer


def _fake_callback(uid: int, data: str):
    cb = MagicMock()
    cb.from_user = MagicMock(id=uid, username="u")
    cb.data = data
    cb.answer = AsyncMock()
    return cb


def _fake_message(text: str, uid: int):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=uid, username="u")
    msg.chat = MagicMock(id=uid)
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _fake_state():
    state = MagicMock()
    state.set_state = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_scope_select_sets_and_all_clears():
    uid = 601
    _clear_scope(uid)
    agent = MockAgent()
    await agent.ingest_document(uid, b"x" * 4000, "application/pdf", filename="дог.pdf")
    doc = (await agent.list_user_documents(uid))[0]

    await on_scope_select(_fake_callback(uid, f"scope:{doc.doc_id}"), agent)
    assert _get_scope(uid) == (doc.doc_id, "дог.pdf")

    await on_scope_select(_fake_callback(uid, "scope:all"), agent)
    assert _get_scope(uid) is None


@pytest.mark.asyncio
async def test_scope_unknown_doc_clears():
    uid = 602
    _set_scope(uid, "stale-id", "старый.pdf")
    cb = _fake_callback(uid, "scope:does-not-exist")
    await on_scope_select(cb, MockAgent())
    assert _get_scope(uid) is None  # неизвестный doc_id → сброс на «по всем»
    assert "не найден" in cb.answer.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_answer_passes_doc_ids_when_scoped():
    uid = 603
    _set_scope(uid, "doc-42", "дог.pdf")
    agent = MagicMock()
    agent.answer_question = AsyncMock(
        return_value=Answer(text="ответ", citations=[], refused=False)
    )
    msg = _fake_message("сколько дней отпуска?", uid)

    await on_question(msg, _fake_state(), InMemoryRepository(), agent)

    agent.answer_question.assert_awaited_once_with(
        uid, "сколько дней отпуска?", doc_ids=["doc-42"]
    )
    # под ответом — подпись активного скоупа
    assert any("по документу: дог.pdf" in c.args[0] for c in msg.answer.await_args_list)
    _clear_scope(uid)


@pytest.mark.asyncio
async def test_answer_passes_none_without_scope():
    uid = 604
    _clear_scope(uid)
    agent = MagicMock()
    agent.answer_question = AsyncMock(
        return_value=Answer(text="ответ", citations=[], refused=False)
    )
    msg = _fake_message("вопрос?", uid)

    await on_question(msg, _fake_state(), InMemoryRepository(), agent)

    agent.answer_question.assert_awaited_once_with(uid, "вопрос?", doc_ids=None)
    # без скоупа подписи быть не должно
    assert all("по документу:" not in c.args[0] for c in msg.answer.await_args_list)
