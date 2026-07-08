"""Агрегация альбома: несколько файлов разом → одно сводное подтверждение."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.formatter import format_album_result
from bot.handlers import content as content_mod
from bot.handlers.content import _album_add, _album_buffers, on_file
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository


def test_format_album_ok_and_failed():
    out = format_album_result(
        [("a.pdf", 3), ("b.pdf", 2)], [("c.pdf", "слишком большой")]
    )
    assert "Принято документов: 2" in out
    assert "фрагментов: 5" in out
    assert "a.pdf" in out and "b.pdf" in out
    assert "Не приняты: 1" in out and "c.pdf" in out


def test_format_album_empty():
    assert "Не удалось" in format_album_result([], [])


@pytest.mark.asyncio
async def test_album_aggregates_into_one_summary(monkeypatch):
    monkeypatch.setattr(content_mod, "_ALBUM_DEBOUNCE_SEC", 0.05)
    msg = MagicMock()
    msg.answer = AsyncMock()
    mgid = "grp-1"
    _album_buffers.pop(mgid, None)

    _album_add(mgid, msg, ok=True, name="a.pdf", chunks=3)
    _album_add(mgid, msg, ok=True, name="b.pdf", chunks=2)
    assert msg.answer.await_count == 0  # до debounce — ни одного ответа

    await asyncio.sleep(0.15)

    assert msg.answer.await_count == 1  # одно сводное сообщение на весь альбом
    out = msg.answer.await_args.args[0]
    assert "a.pdf" in out and "b.pdf" in out and "Принято документов: 2" in out
    assert mgid not in _album_buffers  # буфер вычищен


@pytest.mark.asyncio
async def test_on_file_album_buffers_not_immediate(monkeypatch):
    """Файл из альбома не отвечает сразу — уходит в буфер, сводка позже."""
    monkeypatch.setattr(content_mod, "_ALBUM_DEBOUNCE_SEC", 0.05)
    msg = MagicMock()
    msg.from_user = MagicMock(id=800, username="u")
    msg.chat = MagicMock(id=800)
    msg.document = MagicMock(file_id="f", file_size=999_999_999, file_name="big.pdf")
    msg.photo = None
    msg.media_group_id = "alb-9"
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    state = MagicMock()
    state.set_state = AsyncMock()
    _album_buffers.pop("alb-9", None)

    await on_file(
        msg, state, InMemoryRepository(), MockAgent(),
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )
    assert msg.answer.await_count == 0        # немедленного ответа нет
    assert "alb-9" in _album_buffers          # результат ушёл в буфер

    await asyncio.sleep(0.15)
    assert msg.answer.await_count == 1        # пришла сводка
    assert "big.pdf" in msg.answer.await_args.args[0]
