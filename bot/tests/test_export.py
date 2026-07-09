"""Экспорт последнего ответа в «памятку» (.md с источниками + дисклеймер)."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.formatter import format_export_pdf, format_export_text
from bot.handlers.content import (
    _clear_last_answer,
    _get_last_answer,
    _set_last_answer,
    on_export,
    on_question,
)
from bot.repository import InMemoryRepository
from shared.contracts import Answer, Citation

_ANSWER = Answer(
    text="Уволить в отпуске нельзя по инициативе работодателя.",
    citations=[
        Citation(
            act="ТК РФ",
            article="81",
            revision_date=date(2024, 11, 1),
            source_url="http://pravo.gov.ru/",
        )
    ],
    refused=False,
    clarifying_question=None,
)


def _fake_message(text, uid):
    m = MagicMock()
    m.text = text
    m.from_user = MagicMock(id=uid, username="u")
    m.chat = MagicMock(id=uid)
    m.bot = MagicMock()
    m.bot.send_chat_action = AsyncMock()
    m.answer = AsyncMock()
    return m


def _fake_state():
    s = MagicMock()
    s.set_state = AsyncMock()
    return s


def _fake_callback(uid, data="export:md"):
    cb = MagicMock()
    cb.from_user = MagicMock(id=uid, username="u")
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer_document = AsyncMock()
    return cb


def test_format_export_text_has_question_sources_and_disclaimer():
    txt = format_export_text("Можно ли уволить в отпуске?", _ANSWER, "09.07.2026 15:00")
    assert "Можно ли уволить в отпуске?" in txt
    assert "ст. 81 ТК РФ (ред. от 01.11.2024)" in txt
    assert "http://pravo.gov.ru/" in txt  # источник
    assert "юридической консультацией" in txt
    assert "официальным документом" in txt.lower()
    # чистый текст: без markdown-разметки, которую увидел бы обычный юзер
    assert "**" not in txt and "# " not in txt


def test_format_export_pdf_renders_cyrillic():
    pytest.importorskip("fitz")  # PyMuPDF — зависимость проекта; локально может не стоять
    data = format_export_pdf("Можно ли уволить в отпуске?", _ANSWER, "09.07.2026 15:00")
    assert data[:5] == b"%PDF-"  # это PDF
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    doc.close()
    # кириллица и источник дошли до PDF (не «квадраты»)
    assert "уволить" in text.lower()
    assert "ст. 81 ТК РФ" in text
    assert "pravo.gov.ru" in text


@pytest.mark.asyncio
async def test_answer_stores_last_and_attaches_export_button():
    uid = 701
    _clear_last_answer(uid)
    agent = MagicMock()
    agent.answer_question = AsyncMock(return_value=_ANSWER)
    msg = _fake_message("уволить в отпуске?", uid)

    await on_question(msg, _fake_state(), InMemoryRepository(), agent)

    # ответ сохранён для экспорта
    stored = _get_last_answer(uid)
    assert stored is not None and stored[1] is _ANSWER
    # под ответом — кнопка экспорта
    assert any(
        c.kwargs.get("reply_markup") is not None for c in msg.answer.await_args_list
    )
    _clear_last_answer(uid)


@pytest.mark.asyncio
async def test_refused_answer_not_exportable():
    uid = 702
    _clear_last_answer(uid)
    refused = Answer(text="Не нашёл норму.", citations=[], refused=True)
    agent = MagicMock()
    agent.answer_question = AsyncMock(return_value=refused)
    msg = _fake_message("погода завтра?", uid)

    await on_question(msg, _fake_state(), InMemoryRepository(), agent)

    assert _get_last_answer(uid) is None  # отказ не сохраняем как памятку
    _clear_last_answer(uid)


@pytest.mark.asyncio
async def test_on_export_sends_document():
    uid = 703
    _set_last_answer(uid, "уволить в отпуске?", _ANSWER)
    cb = _fake_callback(uid)

    await on_export(cb)

    cb.message.answer_document.assert_awaited_once()
    caption = cb.message.answer_document.await_args.kwargs.get("caption", "")
    assert "консультаци" in caption.lower()  # дисклеймер в подписи файла
    _clear_last_answer(uid)


@pytest.mark.asyncio
async def test_on_export_without_answer():
    uid = 704
    _clear_last_answer(uid)
    cb = _fake_callback(uid)
    await on_export(cb)
    cb.message.answer_document.assert_not_awaited()
    assert "нечего" in cb.answer.await_args.args[0].lower()
