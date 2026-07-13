"""Гейт вопросов на время индексации документа (UX): вопрос, посланный до готовности
документа, не уходит в агента — пользователь получает подсказку подождать."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import (
    _WAIT_INGEST,
    _ingest_begin,
    _ingest_end,
    _ingesting,
    _is_ingesting,
    on_file,
    on_question,
)
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository


def _fake_state():
    state = MagicMock()
    state.set_state = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    return state


def _fake_text_message(text: str, uid: int = 555):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=uid, username="u")
    msg.chat = MagicMock(id=uid)
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _fake_document_message(uid: int = 556, size: int = 10):
    msg = MagicMock()
    msg.text = None
    msg.from_user = MagicMock(id=uid, username="u")
    msg.chat = MagicMock(id=uid)
    msg.document = MagicMock(file_id="fid", file_size=size, file_name="doc.pdf")
    msg.photo = None
    msg.media_group_id = None  # одиночный файл (не альбом)
    msg.caption = None
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_question_gated_while_ingesting():
    """Пока юзер в _ingesting — вопрос не зовёт агента, идёт подсказка подождать."""
    msg = _fake_text_message("какой оклад в договоре?", uid=555)
    agent = MagicMock()
    agent.answer_question = AsyncMock()

    _ingest_begin(555)
    try:
        await on_question(msg, _fake_state(), InMemoryRepository(), agent)
    finally:
        _ingest_end(555)

    msg.answer.assert_awaited_once_with(_WAIT_INGEST)
    agent.answer_question.assert_not_awaited()  # вопрос НЕ ушёл в агента


@pytest.mark.asyncio
async def test_question_not_gated_when_idle():
    """Без активной загрузки вопрос обрабатывается как обычно (агент вызывается)."""
    msg = _fake_text_message("сколько дней отпуска?", uid=777)
    assert not _is_ingesting(777)
    await on_question(msg, _fake_state(), InMemoryRepository(), MockAgent())
    assert msg.answer.await_count >= 1
    # подсказки про загрузку быть не должно
    assert all(c.args[0] != _WAIT_INGEST for c in msg.answer.await_args_list)


@pytest.mark.asyncio
async def test_on_file_clears_mark_on_early_return():
    """finally снимает метку даже на раннем возврате (файл больше лимита)."""
    msg = _fake_document_message(uid=556, size=999_999_999)
    assert not _is_ingesting(556)

    await on_file(
        msg, _fake_state(), InMemoryRepository(), MockAgent(),
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )

    assert not _is_ingesting(556)  # метка снята
    assert any("слишком большой" in c.args[0] for c in msg.answer.await_args_list)


def test_ingest_refcount_multi_upload():
    """Счётчик: при нескольких параллельных приёмах метка снимается только после последнего."""
    uid = 558
    assert not _is_ingesting(uid)
    _ingest_begin(uid)          # первый файл
    _ingest_begin(uid)          # второй файл (альбом)
    assert _is_ingesting(uid)
    _ingest_end(uid)            # первый завершился — но второй ещё грузится
    assert _is_ingesting(uid)   # с set здесь метка бы уже слетела — это и есть фикс
    _ingest_end(uid)            # завершился последний
    assert not _is_ingesting(uid)
    assert uid not in _ingesting  # ключ вычищен, без утечки памяти
