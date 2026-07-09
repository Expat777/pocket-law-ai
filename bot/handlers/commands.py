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
from bot.config import Config
from bot.formatter import format_documents_list
from bot.handlers.content import (
    SCOPE_PREFIX,
    _answer_question,
    _clear_last_answer,
    _clear_scope,
    _scope_ids,
)
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
    "  Вопрос можно сразу написать в подписи к файлу.\n"
    "• Если данных не хватит, я переспрошу, а не выдумаю ответ.\n\n"
    "Команды:\n"
    "/start — начать и дать согласие на обработку данных\n"
    "/help — эта справка\n"
    "/topics — частые темы и вопросы (быстрый старт)\n"
    "/documents — список документов; тапом отметьте один или несколько для поиска "
    "(там же — «Отметить все» и «Сбросить отметки»)\n"
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
            "С возвращением! Задайте вопрос по законам РФ или пришлите документ.",
            reply_markup=topics_entry_kb(),
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
            "или пришлите PDF/фото документа.",
            reply_markup=topics_entry_kb(),
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


def _documents_keyboard(docs: list, active_ids) -> InlineKeyboardMarkup:
    """Пикер скоупа: кнопка на каждый документ (тап переключает ✓) + «искать по всем».

    `active_ids` — множество отмеченных doc_id (мультивыбор): у всех отмеченных ✓.
    """
    active_ids = set(active_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for i, d in enumerate(docs, 1):
        name = d.filename or "без названия"
        if len(name) > 30:  # длинные имена режем для подписи кнопки
            name = name[:29] + "…"
        mark = "✓ " if d.doc_id in active_ids else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{i}. {name}",
                    callback_data=f"{SCOPE_PREFIX}{d.doc_id}",
                )
            ]
        )
    # «Отметить все» — показываем, когда отмечены не все (иначе кнопка бессмысленна).
    all_ids = {d.doc_id for d in docs}
    if active_ids != all_ids:
        rows.append(
            [InlineKeyboardButton(text="☑️ Отметить все", callback_data=f"{SCOPE_PREFIX}mark_all")]
        )
    # «Сбросить/искать по всем» — явный сброс, когда что-то отмечено; иначе индикатор режима.
    if not active_ids:
        all_text = "✓ 🔎 Искать по всем"
    else:
        all_text = "♻️ Сбросить отметки — искать по всем"
    rows.append(
        [InlineKeyboardButton(text=all_text, callback_data=f"{SCOPE_PREFIX}all")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _documents_view(docs: list, active_ids):
    """Текст + клавиатура для /documents из ОДНОГО источника (мультивыбор).

    Заголовок «Сейчас ищу по: …» и галочки ✓ строятся здесь вместе, поэтому не
    расходятся при перерисовке после смены отметок (см. content._refresh_picker).
    Имена отмеченных берём из самого списка — всегда актуальные.
    """
    active_ids = set(active_ids)
    text = format_documents_list(docs)
    if active_ids:
        names = [d.filename or "без названия" for d in docs if d.doc_id in active_ids]
        if len(names) == 1:
            head = f"🔎 Сейчас ищу только по документу: {names[0]}"
        else:
            head = f"🔎 Сейчас ищу по {len(names)} документам: {', '.join(names)}"
        text = (
            head + "\nТап по документу — отметить/снять (можно несколько). "
            "Кнопки ниже: «☑️ Отметить все» и «♻️ Сбросить отметки».\n\n"
        ) + text
    return text, _documents_keyboard(docs, active_ids)


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

    text, keyboard = _documents_view(docs, set(_scope_ids(user_id)))
    await message.answer(text, reply_markup=keyboard)


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
    _clear_last_answer(user_id)  # и последний ответ для экспорта (152-ФЗ)
    await state.clear()
    await message.answer(
        "🗑 Готово. Я удалил историю диалога, ваше согласие и загруженные документы. "
        "Чтобы снова пользоваться ботом — отправьте /start."
    )


# --- Онбординг: частые темы и вопросы ---------------------------------------
# Кнопки-темы снижают порог входа (пустое поле пугает) и ведут к вопросам, которые
# наша база уверенно закрывает. Тап по вопросу прогоняется через обычный
# _answer_question. Callback: "topics:root" (список тем) / "topic:<id>" (вопросы
# темы) / "tq:<id>:<idx>" (задать вопрос). Вопросы взяты из покрытых нами отраслей.
TOPICS: dict[str, tuple[str, list[str]]] = {
    "labor": ("💼 Трудовые", [
        "Могут ли уволить во время отпуска?",
        "Сколько дней ежегодного отпуска положено?",
        "Что положено работнику при сокращении?",
        "Какой максимальный испытательный срок?",
    ]),
    "family": ("👪 Семейные", [
        "Как подать на развод?",
        "Как рассчитываются алименты на ребёнка?",
        "Как делится имущество супругов при разводе?",
    ]),
    "consumer": ("🛒 Права потребителя", [
        "Как вернуть некачественный товар?",
        "В какой срок можно вернуть товар?",
        "Что делать, если не возвращают деньги за товар?",
    ]),
    "housing": ("🏠 Жильё и ЖКХ", [
        "Что делать, если затопил сосед сверху?",
        "Как приватизировать квартиру?",
        "Кто отвечает за капитальный ремонт дома?",
    ]),
    "traffic": ("🚗 Штрафы и ДТП", [
        "Как оспорить штраф ГИБДД?",
        "Что делать при ДТП без пострадавших?",
        "Как получить выплату по ОСАГО?",
    ]),
    "money": ("💳 Кредиты и долги", [
        "Можно ли досрочно погасить кредит без штрафа?",
        "Что делать, если приставы арестовали карту?",
        "Как объявить себя банкротом?",
    ]),
}

_TOPICS_INTRO = "💡 Выберите тему — покажу частые вопросы. Или просто напишите свой вопрос."


def topics_entry_kb() -> InlineKeyboardMarkup:
    """Одна кнопка «Частые темы» — под приветствием/согласием."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💡 Частые темы", callback_data="topics:root")]]
    )


def _topics_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=title, callback_data=f"topic:{tid}")]
        for tid, (title, _) in TOPICS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _topic_questions_keyboard(topic_id: str) -> InlineKeyboardMarkup:
    _, questions = TOPICS[topic_id]
    rows = [
        [InlineKeyboardButton(text=q, callback_data=f"tq:{topic_id}:{i}")]
        for i, q in enumerate(questions)
    ]
    rows.append([InlineKeyboardButton(text="← Назад к темам", callback_data="topics:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("topics"))
async def cmd_topics(message: Message) -> None:
    await message.answer(_TOPICS_INTRO, reply_markup=_topics_keyboard())


@router.callback_query(F.data == "topics:root")
async def on_topics_root(callback: CallbackQuery) -> None:
    if callback.message is not None:
        try:
            await callback.message.edit_text(_TOPICS_INTRO, reply_markup=_topics_keyboard())
        except Exception:  # noqa: BLE001 — сообщение старое/не изменилось
            await callback.message.answer(_TOPICS_INTRO, reply_markup=_topics_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("topic:"))
async def on_topic_pick(callback: CallbackQuery) -> None:
    topic_id = callback.data.split(":", 1)[1]
    if topic_id not in TOPICS:
        await callback.answer("Тема не найдена")
        return
    title, _ = TOPICS[topic_id]
    text = f"{title} — частые вопросы. Выберите или напишите свой:"
    if callback.message is not None:
        try:
            await callback.message.edit_text(text, reply_markup=_topic_questions_keyboard(topic_id))
        except Exception:  # noqa: BLE001
            await callback.message.answer(text, reply_markup=_topic_questions_keyboard(topic_id))
    await callback.answer()


@router.callback_query(F.data.startswith("tq:"))
async def on_topic_question(
    callback: CallbackQuery,
    state: FSMContext,
    repo: Repository,
    agent: AgentClient,
    config: Config,
) -> None:
    """Тап по частому вопросу → прогоняем через обычный ответ (с гейтами согласия/лимита)."""
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] not in TOPICS:
        await callback.answer("Вопрос не найден")
        return
    topic_id, idx = parts[1], int(parts[2])
    questions = TOPICS[topic_id][1]
    if not (0 <= idx < len(questions)):
        await callback.answer("Вопрос не найден")
        return
    question = questions[idx]
    user_id = callback.from_user.id

    # Callback идёт мимо consent/rate-limit middlewares (они на content-роутере) —
    # повторяем гейты здесь: без согласия и сверх лимита вопрос в LLM не уходит.
    if not await repo.has_consent(user_id):
        await callback.answer("Сначала дайте согласие — отправьте /start", show_alert=True)
        return
    decision = await repo.check_rate_limit(user_id, config.rate_limit_per_hour)
    if not decision.allowed:
        minutes = max(1, decision.retry_after_sec // 60)
        await callback.answer(
            f"Слишком много запросов (лимит {config.rate_limit_per_hour}/час). "
            f"Попробуйте через ~{minutes} мин.",
            show_alert=True,
        )
        return
    if callback.message is None:
        await callback.answer("Откройте /topics заново", show_alert=True)
        return

    await repo.ensure_user(user_id, callback.from_user.username)
    await callback.answer()  # закрыть «часики» до похода в LLM
    await callback.message.answer(f"❓ {question}")  # показать выбранный вопрос
    await _answer_question(
        callback.message, state, repo, agent, question, user_id=user_id
    )
