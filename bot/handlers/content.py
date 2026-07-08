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

# Пользователи, у кого прямо сейчас индексируется загруженный документ (файл/ссылка).
# aiogram обрабатывает апдейты конкурентно (задача на апдейт), поэтому вопрос, посланный
# сразу за файлом, может уйти в агента РАНЬШЕ, чем документ проиндексирован, — и ответ
# построится без нового контекста. Пока идёт приём, такой вопрос гейтим с подсказкой.
#
# Это СЧЁТЧИК приёмов на пользователя (ref-count), а не множество: при загрузке нескольких
# файлов разом (Telegram шлёт альбом отдельными апдейтами → несколько параллельных on_file)
# метка «занят» должна сниматься только когда завершится ПОСЛЕДНИЙ приём. С множеством первый
# же finally снял бы её, пока остальные ещё грузятся. Счётчик в памяти процесса; inc/dec
# синхронные, без гонки: приём приходит раньше вопроса (меньший update_id).
_ingesting: dict[int, int] = {}


def _ingest_begin(user_id: int) -> None:
    _ingesting[user_id] = _ingesting.get(user_id, 0) + 1


def _ingest_end(user_id: int) -> None:
    remaining = _ingesting.get(user_id, 0) - 1
    if remaining > 0:
        _ingesting[user_id] = remaining
    else:
        _ingesting.pop(user_id, None)


def _is_ingesting(user_id: int) -> bool:
    return _ingesting.get(user_id, 0) > 0

_WAIT_INGEST = (
    "⏳ Секунду, обрабатываю ваш документ. "
    "Задайте вопрос, когда я подтвержу, что он принят."
)


def _split_md(text: str, limit: int = _TG_LIMIT) -> list[str]:
    """Режет длинный MarkdownV2 на части ≤limit по границам абзацев (`\\n\\n`).

    Так ничего не теряется — в т.ч. обязательный дисклеймер (152-ФЗ), который
    иначе мог бы отвалиться при простом усечении на 4096.
    """
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        candidate = block if not cur else f"{cur}\n\n{block}"
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
            cur = ""
        if len(block) <= limit:
            cur = block
        else:  # один блок длиннее лимита — режем жёстко (редкий случай)
            for i in range(0, len(block), limit):
                parts.append(block[i : i + limit])
    if cur:
        parts.append(cur)
    return parts


async def _send_md(message: Message, md_text: str) -> None:
    """Отправка MarkdownV2 с мягкой деградацией и разбивкой длинных сообщений.

    Длинный ответ дробится на части ≤4096 (дисклеймер не теряется). Если часть
    ломает разметку — шлём её обычным текстом (снимая экранирование), не теряя ответ.
    """
    for part in _split_md(md_text):
        try:
            await message.answer(part, parse_mode="MarkdownV2")
        except TelegramBadRequest:
            log.warning("MarkdownV2 отклонён Telegram — отправляю как обычный текст")
            await message.answer(part.replace("\\", ""))

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
    _ingest_begin(user_id)  # пока грузим — вопросы к этому юзеру ждут (см. on_question)
    try:
        await repo.ensure_user(user_id, message.from_user.username)
        await state.set_state(Dialog.uploading_file)

        match = _URL_RE.search(message.text)
        if match is None:  # подстраховка, фильтр уже гарантирует наличие URL
            await state.set_state(Dialog.normal_question)
            return
        url = match.group(0)

        # фиксируем в истории — заодно учитывается в rate-limit (счётчик по dialog_history)
        await repo.save_dialog(user_id, "user", f"[ссылка] {url}", [])

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

        # №4: если рядом со ссылкой есть вопрос — ответить на него (по загруженному документу)
        remainder = _URL_RE.sub(" ", message.text).strip()
        if result.ok and _looks_like_question(remainder):
            await _answer_question(message, state, repo, agent, remainder)
    finally:
        _ingest_end(user_id)


def _looks_like_question(text: str) -> bool:
    """Есть ли рядом со ссылкой осмысленный вопрос (буквы + минимальная длина)."""
    return len(text) >= 3 and any(ch.isalpha() for ch in text)


async def _answer_question(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
    text: str,
) -> None:
    """Ядро обработки вопроса: сохранить → спросить агента → ответить (формат 3.5).

    Общее для обычного сообщения, отредактированного и вопроса рядом со ссылкой.
    """
    user_id = message.from_user.id
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


@router.message(F.text & ~F.text.startswith("/"))
async def on_question(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
) -> None:
    if _is_ingesting(message.from_user.id):  # документ ещё грузится — ответить рано
        await message.answer(_WAIT_INGEST)
        return
    await repo.ensure_user(message.from_user.id, message.from_user.username)
    await _answer_question(message, state, repo, agent, message.text.strip())


@router.edited_message(F.text & ~F.text.startswith("/"))
async def on_edited_question(
    message: Message,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
) -> None:
    """Правка текста сообщения (задача №2): обрабатываем как новый вопрос."""
    if _is_ingesting(message.from_user.id):  # документ ещё грузится — ответить рано
        await message.answer(_WAIT_INGEST)
        return
    await repo.ensure_user(message.from_user.id, message.from_user.username)
    await _answer_question(message, state, repo, agent, message.text.strip())


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
    _ingest_begin(user_id)  # пока грузим — вопросы к этому юзеру ждут (см. on_question)
    try:
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

        # фиксируем в истории — заодно учитывается в rate-limit (счётчик по dialog_history)
        doc_name = message.document.file_name if message.document is not None else "фото"
        await repo.save_dialog(user_id, "user", f"[документ] {doc_name}", [])

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
    finally:
        _ingest_end(user_id)


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
