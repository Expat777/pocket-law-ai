"""Команды и поток согласия ПДн (задача MVP 1).

/start — согласие 152-ФЗ (без него бот не отвечает), /help, /delete.
Этот роутер НЕ закрыт consent-middleware: иначе пользователь не смог бы дать согласие.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.agent_client import AgentClient
from bot.formatter import format_documents_list
from bot.handlers.content import SCOPE_PREFIX, _clear_scope, _get_scope
from bot.repository import Repository
from bot.states import Dialog

log = logging.getLogger(__name__)

router = Router(name="commands")

_CONSENT_TEXT = (
    "👋 Я помогаю разобраться в законах РФ и отвечаю строго со ссылкой на статью.\n\n"
    "Чтобы продолжить, нужно ваше согласие на обработку персональных данных "
    "в соответствии с 152-ФЗ. Я храню историю диалога, чтобы отвечать по контексту; "
    "удалить всё можно в любой момент командой /delete.\n\n"
    "Даёте согласие?"
)

_HELP_TEXT = (
    "ℹ️ Я отвечаю на вопросы по законам РФ — всегда со ссылкой на статью-источник.\n\n"
    "• Просто напишите вопрос текстом.\n"
    "• Можно прислать PDF или фото документа (договор, претензия) — учту его в ответе.\n"
    "• Если данных не хватит, я переспрошу, а не выдумаю ответ.\n\n"
    "Команды:\n"
    "/start — начать и дать согласие на обработку данных\n"
    "/help — эта справка\n"
    "/documents — список загруженных вами документов\n"
    "/delete — удалить все мои данные о вас\n\n"
    "⚠️ Ответы бота не являются юридической консультацией."
)


def _consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен", callback_data="consent:yes")],
            [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent:no")],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, repo: Repository) -> None:
    user = message.from_user
    await repo.ensure_user(user.id, user.username)

    if await repo.has_consent(user.id):
        await state.set_state(Dialog.normal_question)
        await message.answer(
            "С возвращением! Задайте вопрос по законам РФ или пришлите документ."
        )
        return

    await message.answer(_CONSENT_TEXT, reply_markup=_consent_keyboard())


@router.callback_query(F.data == "consent:yes")
async def consent_yes(
    callback: CallbackQuery, state: FSMContext, repo: Repository
) -> None:
    # Идемпотентность: повторное нажатие на старую кнопку (согласие уже есть) —
    # просто убираем кнопки и тихо подтверждаем, не переигрывая поток заново.
    if await repo.has_consent(callback.from_user.id):
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Согласие уже получено")
        return

    await repo.ensure_user(callback.from_user.id, callback.from_user.username)
    await repo.set_consent(callback.from_user.id, True)
    await state.set_state(Dialog.normal_question)

    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Спасибо! Согласие получено. Задайте вопрос по законам РФ "
            "или пришлите PDF/фото документа."
        )
    await callback.answer()


@router.callback_query(F.data == "consent:no")
async def consent_no(callback: CallbackQuery, repo: Repository) -> None:
    await repo.set_consent(callback.from_user.id, False)
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Понимаю. Без согласия на обработку данных я не могу отвечать. "
            "Если передумаете — отправьте /start."
        )
    await callback.answer()


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)


def _documents_keyboard(docs: list, active_doc_id: str | None) -> InlineKeyboardMarkup:
    """Пикер скоупа: по кнопке на документ + «искать по всем». Активный помечен ✓."""
    rows: list[list[InlineKeyboardButton]] = []
    for i, d in enumerate(docs, 1):
        name = d.filename or "без названия"
        if len(name) > 30:  # длинные имена режем для подписи кнопки
            name = name[:29] + "…"
        mark = "✓ " if d.doc_id == active_doc_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{i}. {name}",
                    callback_data=f"{SCOPE_PREFIX}{d.doc_id}",
                )
            ]
        )
    all_mark = "✓ " if active_doc_id is None else ""
    rows.append(
        [InlineKeyboardButton(text=f"{all_mark}🔎 Искать по всем", callback_data=f"{SCOPE_PREFIX}all")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("documents"))
async def cmd_documents(message: Message, agent: AgentClient) -> None:
    """Список загруженных документов + пикер: по какому искать (скоуп)."""
    user_id = message.from_user.id
    try:
        docs = await agent.list_user_documents(user_id)
    except Exception:  # noqa: BLE001 — деградируем мягко
        log.exception("list_user_documents failed for user %s", user_id)
        await message.answer(
            "Не получилось получить список документов. Попробуйте позже."
        )
        return

    if not docs:  # без документов пикер не нужен
        await message.answer(format_documents_list(docs))
        return

    scope = _get_scope(user_id)
    active_doc_id = scope[0] if scope else None
    await message.answer(
        format_documents_list(docs),
        reply_markup=_documents_keyboard(docs, active_doc_id),
    )


@router.message(Command("delete"))
async def cmd_delete(
    message: Message, state: FSMContext, repo: Repository, agent: AgentClient
) -> None:
    user_id = message.from_user.id
    await repo.delete_user_data(user_id)  # Postgres: согласие + история диалога
    # 152-ФЗ: удаляем и загруженные документы из векторной базы (Qdrant user_documents).
    # best-effort: сбой очистки не должен ронять /delete (Postgres уже очищен).
    try:
        await agent.delete_user_documents(user_id)
    except Exception:  # noqa: BLE001
        log.exception("delete_user_documents failed for user %s", user_id)
    _clear_scope(user_id)  # выбранного документа больше нет — сбрасываем скоуп
    await state.clear()
    await message.answer(
        "🗑 Готово. Я удалил историю диалога, ваше согласие и загруженные документы. "
        "Чтобы снова пользоваться ботом — отправьте /start."
    )
