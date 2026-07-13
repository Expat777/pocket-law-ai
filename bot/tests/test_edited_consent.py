"""Тесты фиксов самоаудита: правка сообщения (№2), URL+вопрос (№4), согласие (№3)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.commands import consent_yes
from bot.handlers.content import _looks_like_question, on_edited_question, on_url
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository


def _fake_message(text: str):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=1, username="u")
    msg.chat = MagicMock(id=1)
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _fake_state():
    state = MagicMock()
    state.set_state = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    return state


def test_looks_like_question():
    assert _looks_like_question("какой срок?")
    assert not _looks_like_question("")
    assert not _looks_like_question("  ")
    assert not _looks_like_question("12")       # коротко и без букв
    assert not _looks_like_question("!!!")      # без букв


@pytest.mark.asyncio
async def test_edited_message_answered_as_question():
    msg = _fake_message("какой срок отпуска положен?")
    await on_edited_question(msg, _fake_state(), InMemoryRepository(), MockAgent())
    assert msg.answer.await_count == 1  # правка → обработана как вопрос


@pytest.mark.asyncio
async def test_url_with_trailing_question_ingests_and_answers():
    msg = _fake_message("https://example.com/dogovor.pdf что это?")
    await on_url(msg, _fake_state(), InMemoryRepository(), MockAgent())
    # два ответа: приём документа + ответ на вопрос
    assert msg.answer.await_count == 2
    texts = [c.args[0] for c in msg.answer.await_args_list]
    assert any("принят" in t for t in texts)
    assert any("Основание" in t for t in texts)


@pytest.mark.asyncio
async def test_url_only_no_trailing_answer():
    msg = _fake_message("https://example.com/dogovor.pdf")
    await on_url(msg, _fake_state(), InMemoryRepository(), MockAgent())
    assert msg.answer.await_count == 1  # только приём документа


@pytest.mark.asyncio
async def test_consent_yes_idempotent():
    repo = InMemoryRepository()
    await repo.set_consent(7, True)  # уже согласен
    cb = MagicMock()
    cb.from_user = MagicMock(id=7, username="u")
    cb.message = MagicMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.answer = AsyncMock()

    await consent_yes(cb, _fake_state(), repo)

    cb.message.answer.assert_not_awaited()  # не переигрываем "Спасибо, согласие получено"
    cb.answer.assert_awaited()              # тихое подтверждение
