"""Скоуп поиска по документу: выбор/сброс через пикер + проброс doc_ids в агента."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import (
    _clear_scope,
    _scope_ids,
    _toggle_scope,
    on_file,
    on_question,
    on_scope_select,
)
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository
from shared.contracts import Answer, IngestResult


def _fake_upload(uid: int, data: bytes = b"%PDF-1.4\n" + b"x" * 4000):
    m = MagicMock()
    m.text = None
    m.from_user = MagicMock(id=uid, username="u")
    m.chat = MagicMock(id=uid)
    m.document = MagicMock(file_id="fid", file_size=len(data), file_name="new.pdf")
    m.photo = None
    m.media_group_id = None
    m.caption = None
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
    cb.message.edit_text = AsyncMock()  # перерисовка сообщения /documents (текст+кнопки)
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
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_scope_select_sets_and_all_clears():
    uid = 601
    _clear_scope(uid)
    agent = MockAgent()
    await agent.ingest_document(uid, b"x" * 4000, "application/pdf", filename="дог.pdf")
    doc = (await agent.list_user_documents(uid))[0]

    await on_scope_select(_fake_callback(uid, f"scope:{doc.doc_id}"), agent)
    assert _scope_ids(uid) == [doc.doc_id]

    await on_scope_select(_fake_callback(uid, "scope:all"), agent)
    assert _scope_ids(uid) == []


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

    cb.message.edit_text.assert_awaited_once()
    text = cb.message.edit_text.await_args.args[0]
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    marked = _active_marked(markup)
    assert any("B.pdf" in t for t in marked)  # ✓ на выбранном
    assert not any("A.pdf" in t for t in marked)  # не на другом
    assert not any("по всем" in t for t in marked)  # и не на «искать по всем»
    # заголовок сообщения совпадает с ✓ (не расходится) — регресс из скрина
    assert "Сейчас ищу только по документу: B.pdf" in text

    # сброс на «искать по всем» → ✓ переезжает туда, заголовок-скоуп исчезает
    cb2 = _fake_callback(uid, "scope:all")
    await on_scope_select(cb2, agent)
    text2 = cb2.message.edit_text.await_args.args[0]
    markup2 = cb2.message.edit_text.await_args.kwargs["reply_markup"]
    marked2 = _active_marked(markup2)
    assert any("по всем" in t for t in marked2)
    assert not any(".pdf" in t for t in marked2)
    assert "Сейчас ищу только по" not in text2
    _clear_scope(uid)


@pytest.mark.asyncio
async def test_scope_tap_deleted_doc_drops_it():
    uid = 602
    _clear_scope(uid)
    _toggle_scope(uid, "gone-id", "удалённый.pdf")  # был отмечен, потом удалён
    cb = _fake_callback(uid, "scope:gone-id")
    await on_scope_select(cb, MockAgent())  # у мока документов нет
    assert _scope_ids(uid) == []  # отсутствующий убран из выборки
    assert "не найден" in cb.answer.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_scope_multiselect_marks_and_passes_all_doc_ids():
    """Можно отметить НЕСКОЛЬКО документов — ✓ на всех, поиск по всем doc_ids."""
    uid = 610
    _clear_scope(uid)
    agent = MockAgent()
    await agent.ingest_document(uid, b"x" * 4000, "application/pdf", filename="A.pdf")
    await agent.ingest_document(uid, b"y" * 4000, "application/pdf", filename="B.pdf")
    docs = await agent.list_user_documents(uid)
    a = next(d for d in docs if d.filename == "A.pdf")
    b = next(d for d in docs if d.filename == "B.pdf")

    await on_scope_select(_fake_callback(uid, f"scope:{a.doc_id}"), agent)
    cb = _fake_callback(uid, f"scope:{b.doc_id}")
    await on_scope_select(cb, agent)  # второй тап НЕ снимает первый

    assert set(_scope_ids(uid)) == {a.doc_id, b.doc_id}
    marked = _active_marked(cb.message.edit_text.await_args.kwargs["reply_markup"])
    assert any("A.pdf" in t for t in marked) and any("B.pdf" in t for t in marked)
    assert "по 2 документам" in cb.message.edit_text.await_args.args[0]

    # повторный тап по A — снимает только A
    await on_scope_select(_fake_callback(uid, f"scope:{a.doc_id}"), agent)
    assert _scope_ids(uid) == [b.doc_id]
    _clear_scope(uid)


@pytest.mark.asyncio
async def test_mark_all_selects_every_doc():
    """Кнопка «Отметить все» отмечает все документы разом (симметрично сбросу)."""
    uid = 611
    _clear_scope(uid)
    agent = MockAgent()
    await agent.ingest_document(uid, b"x" * 4000, "application/pdf", filename="A.pdf")
    await agent.ingest_document(uid, b"y" * 4000, "application/pdf", filename="B.pdf")
    docs = await agent.list_user_documents(uid)

    cb = _fake_callback(uid, "scope:mark_all")
    await on_scope_select(cb, agent)

    assert set(_scope_ids(uid)) == {d.doc_id for d in docs}
    # все отмечены → кнопки «Отметить все» больше нет, есть «Сбросить отметки»
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert not any("Отметить все" in t for t in texts)
    assert any("Сбросить отметки" in t for t in texts)
    _clear_scope(uid)


@pytest.mark.asyncio
async def test_answer_passes_doc_ids_when_scoped():
    uid = 603
    _clear_scope(uid)
    _toggle_scope(uid, "doc-42", "дог.pdf")
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
async def test_new_upload_autoscopes_to_it():
    """Загрузка файла АВТО-выбирает его (замена старого скоупа) — координация с Ролью 2:
    без авто-скоупа следующий вопрос шёл бы без doc_ids и doc-разбор не включался бы."""
    uid = 608
    _clear_scope(uid)
    _toggle_scope(uid, "old-doc", "старый.pdf")
    agent = MockAgent()
    msg = _fake_upload(uid)
    await on_file(
        msg, _fake_state(), InMemoryRepository(), agent,
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )
    docs = await agent.list_user_documents(uid)  # только что загруженный
    assert _scope_ids(uid) == [docs[0].doc_id]  # авто-скоуп на новый
    assert "old-doc" not in _scope_ids(uid)  # старый снят
    _clear_scope(uid)


@pytest.mark.asyncio
async def test_file_caption_question_answered_scoped_to_new_doc():
    """Файл с вопросом в подписи → сразу ответ по этому документу (#7)."""
    uid = 609
    _clear_scope(uid)
    agent = MagicMock()
    agent.ingest_document = AsyncMock(
        return_value=IngestResult(doc_id="DOCX", chunks=2, ok=True, error=None)
    )
    agent.answer_question = AsyncMock(
        return_value=Answer(text="оклад 120000", citations=[], refused=False)
    )
    msg = _fake_upload(uid)
    msg.caption = "какой оклад в договоре?"

    await on_file(
        msg, _fake_state(), InMemoryRepository(), agent,
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )

    # вопрос из подписи ушёл в агента со скоупом на только что загруженный документ
    agent.answer_question.assert_awaited_once()
    assert agent.answer_question.await_args.args[1] == "какой оклад в договоре?"
    assert agent.answer_question.await_args.kwargs["doc_ids"] == ["DOCX"]
    _clear_scope(uid)
