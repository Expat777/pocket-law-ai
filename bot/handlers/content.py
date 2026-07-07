"""Контент-роутер: текстовые вопросы (задачи 3–4) и файлы (задача 5).

Закрыт ConsentMiddleware + RateLimitMiddleware (вешаются в main.py).
Ответы форматируются через bot.formatter и отправляются в MarkdownV2;
служебные строки — обычным текстом (parse_mode по умолчанию).
"""

from __future__ import annotations

import io
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.agent_client import AgentClient
from bot.formatter import format_answer_message, format_ingest_result
from bot.repository import Repository
from bot.states import Dialog

router = Router(name="content")
log = logging.getLogger(__name__)

_TG_LIMIT = 4096  # максимум символов в одном сообщении Telegram


async def _send_md(message: Message, md_text: str) -> None:
    """Отправка MarkdownV2 с мягкой деградацией.

    Если реальный агент вернёт текст, ломающий разметку — не теряем ответ,
    а шлём его как обычный текст (снимая экранирование). Длинный ответ
    обрезаем до лимита Telegram, чтобы отправка не падала.
    """
    text = md_text if len(md_text) <= _TG_LIMIT else md_text[: _TG_LIMIT - 1] + "…"
    try:
        await message.answer(text, parse_mode="MarkdownV2")
    except TelegramBadRequest:
        log.warning("MarkdownV2 отклонён Telegram — отправляю как обычный текст")
        await message.answer(text.replace("\\", ""))

# Валидация файлов ДО обработки (задача MVP 5): размер проверяем по метаданным,
# тип — по magic bytes скачанного заголовка, а не по расширению/заявленному mime.
_MAGIC = {
    b"%PDF": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


def _sniff_mime(head: bytes) -> str | None:
    for magic, mime in _MAGIC.items():
        if head.startswith(magic):
            return mime
    return None


# Детект ссылки на документ: сообщение, начинающееся с http(s):// (задача Роли 2 —
# ingest_url). SSRF-защита — на стороне агента; бот только извлекает URL и передаёт.
_URL_RE = re.compile(r"https?://\S+")


@router.message(F.text.regexp(r"^\s*https?://"))
async def on_url(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
) -> None:
    user_id = message.from_user.id
    await repo.ensure_user(user_id, message.from_user.username)
    await state.set_state(Dialog.uploading_file)

    match = _URL_RE.search(message.text)
    if match is None:  # подстраховка, фильтр уже гарантирует наличие URL
        await state.set_state(Dialog.normal_question)
        return
    url = match.group(0)

    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    try:
        result = await agent.ingest_url(user_id, url)
    except Exception:  # noqa: BLE001
        log.exception("ingest_url failed for user %s", user_id)
        await message.answer(
            "Не получилось загрузить документ по ссылке. Проверьте ссылку и попробуйте позже."
        )
        await state.set_state(Dialog.normal_question)
        return

    await _send_md(message, format_ingest_result(result))
    await state.set_state(Dialog.normal_question)


@router.message(F.text & ~F.text.startswith("/"))
async def on_question(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
) -> None:
    user_id = message.from_user.id
    text = message.text.strip()

    await repo.ensure_user(user_id, message.from_user.username)
    await repo.save_dialog(user_id, "user", text, [])

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        answer = await agent.answer_question(user_id, text)
    except Exception:  # noqa: BLE001 — деградируем мягко, не роняем апдейт
        log.exception("answer_question failed for user %s", user_id)
        await message.answer(
            "Что-то пошло не так при обработке вопроса. Попробуйте ещё раз чуть позже."
        )
        return

    # FSM: агент переспросил → ждём уточнение, иначе обычный режим (задача 4).
    if answer.clarifying_question:
        await state.set_state(Dialog.awaiting_clarification)
    else:
        await state.set_state(Dialog.normal_question)

    await repo.save_dialog(user_id, "assistant", answer.text, answer.citations)
    await _send_md(message, format_answer_message(answer))


@router.message(F.document | F.photo)
async def on_file(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
    bot: Bot,
    max_file_bytes: int,
) -> None:
    user_id = message.from_user.id
    await repo.ensure_user(user_id, message.from_user.username)
    await state.set_state(Dialog.uploading_file)

    # 1) выбрать объект файла и его размер
    if message.document is not None:
        file_id = message.document.file_id
        size = message.document.file_size or 0
    else:  # photo — берём самое большое превью
        photo = message.photo[-1]
        file_id = photo.file_id
        size = photo.file_size or 0

    # 2) размер — ДО скачивания
    if size > max_file_bytes:
        limit_mb = max_file_bytes // (1024 * 1024)
        await message.answer(
            f"Файл слишком большой ({size // (1024 * 1024)} МБ). "
            f"Максимум — {limit_mb} МБ."
        )
        await state.set_state(Dialog.normal_question)
        return

    # 3) скачать и проверить magic bytes ДО вызова агента
    buffer = io.BytesIO()
    try:
        await bot.download(file_id, destination=buffer)
    except Exception:  # noqa: BLE001
        log.exception("download failed for user %s", user_id)
        await message.answer("Не удалось скачать файл. Попробуйте прислать ещё раз.")
        await state.set_state(Dialog.normal_question)
        return

    file_bytes = buffer.getvalue()
    mime = _sniff_mime(file_bytes[:16])
    if mime is None:
        await message.answer(
            "Поддерживаются только PDF, JPG и PNG. "
            "Пришлите документ в одном из этих форматов."
        )
        await state.set_state(Dialog.normal_question)
        return

    # 4) обработка через контракт 3.1
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    try:
        result = await agent.ingest_document(user_id, file_bytes, mime)
    except Exception:  # noqa: BLE001
        log.exception("ingest_document failed for user %s", user_id)
        await message.answer("Не получилось обработать документ. Попробуйте позже.")
        await state.set_state(Dialog.normal_question)
        return

    await _send_md(message, format_ingest_result(result))
    await state.set_state(Dialog.normal_question)


@router.message()
async def on_unsupported(message: Message) -> None:
    """Всё, что не текст и не файл (голос, видео, стикер, гео и т.п.).

    Стоит последним в роутере — срабатывает, только если не подошли
    on_question / on_file. Молчать нельзя: пользователь должен понять, что делать.
    """
    await message.answer(
        "Я понимаю только текстовые вопросы и документы (PDF, JPG, PNG). "
        "Напишите вопрос текстом или пришлите файл."
    )
