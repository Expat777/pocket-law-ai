"""Контент-роутер: текстовые вопросы (задачи 3–4) и файлы (задача 5).

Закрыт ConsentMiddleware + RateLimitMiddleware (вешаются в main.py).
Ответы форматируются через bot.formatter и отправляются в MarkdownV2;
служебные строки — обычным текстом (parse_mode по умолчанию).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.agent_client import AgentClient
from bot.formatter import (
    format_album_result,
    format_answer_message,
    format_ingest_result,
)
from bot.repository import Repository
from bot.states import Dialog

router = Router(name="content")
log = logging.getLogger(__name__)

# --- Скоуп поиска по конкретному документу ----------------------------------
# Пользователь может в /documents выбрать «искать по документу N» (кнопкой). Скоуп
# ЛИПКИЙ: держится, пока не сменит/сбросит. Храним в памяти процесса (user_id →
# (doc_id, имя)); при рестарте сбрасывается на «по всем» — это ок для UI-настройки.
# Префикс callback_data кнопок пикера (общий с commands.cmd_documents).
SCOPE_PREFIX = "scope:"
_doc_scope: dict[int, tuple[str, str]] = {}


def _set_scope(user_id: int, doc_id: str, name: str) -> None:
    _doc_scope[user_id] = (doc_id, name)


def _clear_scope(user_id: int) -> None:
    _doc_scope.pop(user_id, None)


def _get_scope(user_id: int) -> tuple[str, str] | None:
    return _doc_scope.get(user_id)

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
            result = await agent.ingest_url(user_id, url, filename=url)
        except Exception:  # noqa: BLE001
            log.exception("ingest_url failed for user %s", user_id)
            await message.answer(
                "Не получилось загрузить документ по ссылке. Проверьте ссылку и попробуйте позже."
            )
            await state.set_state(Dialog.normal_question)
            return

        await _send_md(message, format_ingest_result(result))
        await state.set_state(Dialog.normal_question)

        if result.ok:
            # Новый документ → прежний «липкий» скоуп больше не актуален (не липнем
            # к старому файлу). См. также on_file.
            _clear_scope(user_id)
            # №4: вопрос рядом со ссылкой → отвечаем строго по ТОЛЬКО ЧТО загруженному
            # документу (override), а не по всей базе и не по старому скоупу.
            remainder = _URL_RE.sub(" ", message.text).strip()
            if _looks_like_question(remainder):
                await _answer_question(
                    message, state, repo, agent, remainder,
                    scope_override=(result.doc_id, url),
                )
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
    scope_override: tuple[str, str] | None = None,
) -> None:
    """Ядро обработки вопроса: сохранить → спросить агента → ответить (формат 3.5).

    Общее для обычного сообщения, отредактированного и вопроса рядом со ссылкой.
    `scope_override` (doc_id, имя) имеет приоритет над «липким» скоупом — им
    вопрос рядом со ссылкой привязывается к ТОЛЬКО ЧТО загруженному документу.
    """
    user_id = message.from_user.id
    await repo.save_dialog(user_id, "user", text, [])

    # Явный override (вопрос рядом со ссылкой) > липкий скоуп пользователя > по всем.
    sticky = _get_scope(user_id)
    scope = scope_override or sticky
    doc_ids = [scope[0]] if scope else None

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        answer = await agent.answer_question(user_id, text, doc_ids=doc_ids)
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
    # Подпись с «сбросить» — только для ЛИПКОГО скоупа (его есть смысл снимать).
    # Для одноразового override (вопрос рядом со ссылкой) сбрасывать нечего.
    if scope_override is None and sticky:
        await message.answer(f"🔎 по документу: {sticky[1]} · сбросить — /documents или /all")


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


# --- Агрегация альбома (несколько файлов одним сообщением) -------------------
# Telegram шлёт альбом ОТДЕЛЬНЫМИ апдейтами с общим media_group_id и без «конца
# альбома». Копим результаты приёма по media_group_id и после короткой паузы (нет
# новых файлов) шлём ОДНО сводное подтверждение вместо N штук.
_ALBUM_DEBOUNCE_SEC = 1.5
_album_buffers: dict[str, dict] = {}


def _album_add(
    mgid: str,
    message: Message,
    *,
    ok: bool,
    name: str,
    chunks: int = 0,
    reason: str | None = None,
) -> None:
    """Добавляет результат одного файла в буфер альбома и (пере)ставит debounce."""
    buf = _album_buffers.setdefault(mgid, {"ok": [], "failed": [], "task": None})
    buf["message"] = message  # любое сообщение альбома годится, чтобы ответить
    if ok:
        buf["ok"].append((name, chunks))
    else:
        buf["failed"].append((name, reason or "ошибка"))
    old = buf.get("task")
    if old is not None:
        old.cancel()  # пришёл ещё файл — отодвигаем отправку сводки
    buf["task"] = asyncio.create_task(_flush_album(mgid))


async def _flush_album(mgid: str) -> None:
    try:
        await asyncio.sleep(_ALBUM_DEBOUNCE_SEC)
    except asyncio.CancelledError:
        return  # пришёл новый файл — эта отправка отменена, будет новая
    buf = _album_buffers.pop(mgid, None)
    if buf is None:
        return
    # Это detached-задача: глобальный @dp.errors её не ловит. Сбой отправки (сеть/
    # удалённое сообщение) не должен уходить в «Task exception was never retrieved» —
    # логируем, сводку теряем осознанно, а не молча.
    try:
        await buf["message"].answer(format_album_result(buf["ok"], buf["failed"]))
    except Exception:  # noqa: BLE001
        log.exception("не удалось отправить сводку альбома %s", mgid)


async def _accept_file(message: Message, mgid: str | None, name: str, result) -> None:
    """Успешный приём: одиночный файл → сразу ответ; файл альбома → в буфер сводки."""
    if mgid is None:
        await _send_md(message, format_ingest_result(result))
    elif result.ok:
        _album_add(mgid, message, ok=True, name=name, chunks=result.chunks)
    else:
        _album_add(mgid, message, ok=False, name=name, reason=result.error or "ошибка")


async def _reject_file(
    message: Message, mgid: str | None, name: str, solo_text: str, reason: str
) -> None:
    """Отказ по файлу: одиночный → сразу текст; файл альбома → в буфер сводки."""
    if mgid is None:
        await message.answer(solo_text)
    else:
        _album_add(mgid, message, ok=False, name=name, reason=reason)


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

        # media_group_id → файл прислан в альбоме (несколько разом): подтверждения
        # копим в одну сводку, а не шлём по одному (см. _album_add / _flush_album).
        mgid = message.media_group_id

        # 2) размер — ДО скачивания
        if size > max_file_bytes:
            limit_mb = max_file_bytes // (1024 * 1024)
            await _reject_file(
                message, mgid, doc_name,
                f"Файл слишком большой ({size // (1024 * 1024)} МБ). Максимум — {limit_mb} МБ.",
                "слишком большой",
            )
            await state.set_state(Dialog.normal_question)
            return

        # 3) скачать и проверить magic bytes ДО вызова агента
        buffer = io.BytesIO()
        try:
            await bot.download(file_id, destination=buffer)
        except Exception:  # noqa: BLE001
            log.exception("download failed for user %s", user_id)
            await _reject_file(
                message, mgid, doc_name,
                "Не удалось скачать файл. Попробуйте прислать ещё раз.",
                "не скачался",
            )
            await state.set_state(Dialog.normal_question)
            return

        file_bytes = buffer.getvalue()
        mime = _sniff_mime(file_bytes[:16])
        if mime is None:
            await _reject_file(
                message, mgid, doc_name,
                "Поддерживаются только PDF, JPG и PNG. "
                "Пришлите документ в одном из этих форматов.",
                "неподдерживаемый тип",
            )
            await state.set_state(Dialog.normal_question)
            return

        # 4) обработка через контракт 3.1
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        try:
            result = await agent.ingest_document(user_id, file_bytes, mime, filename=doc_name)
        except Exception:  # noqa: BLE001
            log.exception("ingest_document failed for user %s", user_id)
            await _reject_file(
                message, mgid, doc_name,
                "Не получилось обработать документ. Попробуйте позже.",
                "ошибка обработки",
            )
            await state.set_state(Dialog.normal_question)
            return

        if result.ok:
            # Новый документ → сбрасываем прежний «липкий» скоуп, чтобы он не
            # «залипал» на старом файле (частая путаница). Поиск снова по всем,
            # включая только что загруженный; сузить — снова через /documents.
            _clear_scope(user_id)
        await _accept_file(message, mgid, doc_name, result)
        await state.set_state(Dialog.normal_question)

        # Одиночный файл прислан с подписью-вопросом → отвечаем по нему сразу
        # (как «ссылка+вопрос»). Для альбома пропускаем: подпись есть лишь у одного
        # файла и относилась бы не ко всей пачке.
        if mgid is None and result.ok:
            caption = (message.caption or "").strip()
            if _looks_like_question(caption):
                await _answer_question(
                    message, state, repo, agent, caption,
                    scope_override=(result.doc_id, doc_name),
                )
    finally:
        _ingest_end(user_id)


async def _refresh_picker(
    callback: CallbackQuery,
    agent: AgentClient,
    user_id: int,
    active_id: str | None,
    docs: list | None = None,
) -> None:
    """Best-effort перерисовка ✓ в клавиатуре пикера под сообщением /documents.

    Иначе галочка активного документа «залипает» до следующего /documents. Всё в
    try/except: старое сообщение или «разметка не изменилась» — не повод падать.
    """
    if callback.message is None:
        return
    try:
        if docs is None:
            docs = await agent.list_user_documents(user_id)
        if not docs:
            return
        # lazy-import: commands импортирует content на старте — не создаём цикл на модуле.
        from bot.handlers.commands import _documents_keyboard

        await callback.message.edit_reply_markup(
            reply_markup=_documents_keyboard(docs, active_id)
        )
    except TelegramBadRequest:
        pass  # message too old / not modified — не критично
    except Exception:  # noqa: BLE001
        log.exception("refresh picker failed for user %s", user_id)


@router.callback_query(F.data.startswith(SCOPE_PREFIX))
async def on_scope_select(callback: CallbackQuery, agent: AgentClient) -> None:
    """Кнопка пикера в /documents: выбрать активный документ или «искать по всем».

    callback_data = "scope:all" (сброс) либо "scope:<doc_id>" (скоуп на документ).
    После выбора двигаем ✓ в клавиатуре, чтобы она не показывала устаревший активный.
    """
    user_id = callback.from_user.id
    payload = callback.data[len(SCOPE_PREFIX):]

    if payload == "all":
        _clear_scope(user_id)  # сброс работает всегда, даже если агент недоступен
        await callback.answer("🔎 Ищу по всем документам")
        await _refresh_picker(callback, agent, user_id, active_id=None)
        return

    # payload = doc_id → находим имя (и заодно проверяем, что документ ещё существует)
    try:
        docs = await agent.list_user_documents(user_id)
    except Exception:  # noqa: BLE001
        log.exception("list_user_documents failed for user %s", user_id)
        await callback.answer("Не получилось выбрать документ, попробуйте позже.")
        return

    doc = next((d for d in docs if d.doc_id == payload), None)
    if doc is None:  # удалён/устарел — сбрасываем на «по всем»
        _clear_scope(user_id)
        await callback.answer("Документ не найден (возможно, удалён). Ищу по всем.")
        await _refresh_picker(callback, agent, user_id, active_id=None, docs=docs)
        return

    name = doc.filename or "без названия"
    _set_scope(user_id, doc.doc_id, name)
    await callback.answer(f"🔎 Ищу по: {name}")
    await _refresh_picker(callback, agent, user_id, active_id=doc.doc_id, docs=docs)


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
