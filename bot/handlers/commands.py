"""Команды и поток согласия ПДн (задача MVP 1).

/start — согласие 152-ФЗ (без него бот не отвечает), /help, /delete_my_data.
Этот роутер НЕ закрыт consent-middleware: иначе пользователь не смог бы дать согласие.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.repository import Repository
from bot.states import Dialog

router = Router(name="commands")

_CONSENT_TEXT = (
    "👋 Я помогаю разобраться в законах РФ и отвечаю строго со ссылкой на статью.\n\n"
    "Чтобы продолжить, нужно ваше согласие на обработку персональных данных "
    "в соответствии с 152-ФЗ. Я храню историю диалога, чтобы отвечать по контексту; "
    "удалить всё можно в любой момент командой /delete_my_data.\n\n"
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
    "/delete_my_data — удалить все мои данные о вас\n\n"
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


@router.message(Command("delete_my_data"))
async def cmd_delete(message: Message, state: FSMContext, repo: Repository) -> None:
    await repo.delete_user_data(message.from_user.id)
    await state.clear()
    await message.answer(
        "🗑 Готово. Я удалил историю диалога и ваше согласие. "
        "Чтобы снова пользоваться ботом — отправьте /start."
    )
