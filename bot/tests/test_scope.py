"""Скоуп поиска по документу: выбор/сброс через пикер + проброс doc_ids в агента."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.commands import cmd_all
from bot.handlers.content import (
    _clear_scope,
    _get_scope,
    _set_scope,
    on_file,
    on_question,
    on_scope_select,
)
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository
from shared.contracts import Answer


def _fake_upload(uid: int, data: bytes = b"%PDF-1.4\n" + b"x" * 4000):
    m = MagicMock()
    m.text = None
    m.from_user = MagicMock(id=uid, username="u")
    m.chat = MagicMock(id=uid)
    m.document = MagicMock(file_id="fid", file_size=len(data), file_name="new.pdf")
    m.photo = None
    m.media_group_id = None
    m.bot = MagicMock()
    m.bot.send_chat_action = AsyncMock()

    async def _dl(file_id, destination):
        destination.write(data)

    m.bot.download = AsyncMock(side_effect=_dl)
    m.answer = AsyncMock()
    return m


def _fake_callback(uid: int, data: str):
    cb = MagicMock()
    cb.from_user = MagicMock(id=uid, username="u")
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()  # перерисовка ✓ в пикере
    return cb


def _active_marked(markup) -> set[str]:
    """Тексты кнопок с галочкой ✓ в перерисованной клавиатуре пикера."""
    return {
        btn.text
        for row in markup.inline_keyboard
        for btn in row
        if btn.text.startswith("✓")
    }


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
async def test_scope_select_moves_checkmark_in_keyboard():
    """Тап по документу → ✓ в клавиатуре переезжает на него (Н2: не залипает)."""
    uid = 605
    _clear_scope(uid)
    agent = MockAgent()
    await agent.ingest_document(uid, b"x" * 4000, "application/pdf", filename="A.pdf")
    await agent.ingest_document(uid, b"y" * 4000, "application/pdf", filename="B.pdf")
    docs = await agent.list_user_documents(uid)  # свежие сверху: [B, A]
    b_doc = next(d for d in docs if d.filename == "B.pdf")

    cb = _fake_callback(uid, f"scope:{b_doc.doc_id}")
    await on_scope_select(cb, agent)

    cb.message.edit_reply_markup.assert_awaited_once()
    markup = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    marked = _active_marked(markup)
    assert any("B.pdf" in t for t in marked)  # ✓ на выбранном
    assert not any("A.pdf" in t for t in marked)  # не на другом
    assert not any("по всем" in t for t in marked)  # и не на «искать по всем»

    # сброс на «искать по всем» → ✓ переезжает туда
    cb2 = _fake_callback(uid, "scope:all")
    await on_scope_select(cb2, agent)
    markup2 = cb2.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    marked2 = _active_marked(markup2)
    assert any("по всем" in t for t in marked2)
    assert not any(".pdf" in t for t in marked2)
    _clear_scope(uid)


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


@pytest.mark.asyncio
async def test_cmd_all_clears_scope():
    """/all снимает выбор документа без удаления данных (ответ на жалобу: как сбросить)."""
    uid = 607
    _set_scope(uid, "d1", "дог.pdf")
    m = _fake_message("/all", uid)
    await cmd_all(m)
    assert _get_scope(uid) is None
    assert "дог.pdf" in m.answer.await_args.args[0]  # сказал, что снял именно этот


@pytest.mark.asyncio
async def test_new_upload_clears_sticky_scope():
    """Загрузка нового документа сбрасывает прежний скоуп — он не залипает на старом файле."""
    uid = 608
    _set_scope(uid, "old-doc", "старый.pdf")
    msg = _fake_upload(uid)
    await on_file(
        msg, _fake_state(), InMemoryRepository(), MockAgent(),
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )
    assert _get_scope(uid) is None
    _clear_scope(uid)
