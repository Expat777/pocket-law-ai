"""Онбординг: частые темы → вопросы → прогон через обычный ответ (с гейтами)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import Config
from bot.handlers.commands import (
    TOPICS,
    cmd_topics,
    on_topic_pick,
    on_topic_question,
)
from bot.repository import InMemoryRepository
from shared.contracts import Answer


def _cfg(limit: int = 20) -> Config:
    return Config(bot_token="x", rate_limit_per_hour=limit)


def _msg():
    m = MagicMock()
    m.from_user = MagicMock(id=1, username="u")
    m.answer = AsyncMock()
    return m


def _cb(uid: int, data: str):
    cb = MagicMock()
    cb.from_user = MagicMock(id=uid, username="u")
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.chat = MagicMock(id=uid)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.bot = MagicMock()
    cb.message.bot.send_chat_action = AsyncMock()
    return cb


def _state():
    s = MagicMock()
    s.set_state = AsyncMock()
    return s


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_cmd_topics_lists_topics():
    m = _msg()
    await cmd_topics(m)
    kb = m.answer.await_args.kwargs["reply_markup"]
    assert any("Трудовые" in t for t in _labels(kb))


@pytest.mark.asyncio
async def test_topic_pick_shows_questions_and_back():
    cb = _cb(1, "topic:labor")
    await on_topic_pick(cb)
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    labels = _labels(kb)
    assert any("отпуск" in t.lower() for t in labels)
    assert any("Назад" in t for t in labels)


@pytest.mark.asyncio
async def test_topic_question_blocked_without_consent():
    repo = InMemoryRepository()  # согласия нет
    agent = MagicMock()
    agent.answer_question = AsyncMock()
    cb = _cb(1, "tq:labor:0")

    await on_topic_question(cb, _state(), repo, agent, _cfg())

    agent.answer_question.assert_not_awaited()  # в LLM не ушли
    assert "согласие" in cb.answer.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_topic_question_answers_with_consent():
    repo = InMemoryRepository()
    await repo.set_consent(1, True)
    agent = MagicMock()
    agent.answer_question = AsyncMock(
        return_value=Answer(text="ответ", citations=[], refused=False)
    )
    cb = _cb(1, "tq:labor:0")

    await on_topic_question(cb, _state(), repo, agent, _cfg())

    agent.answer_question.assert_awaited_once()
    # ушёл ПОЛНЫЙ вопрос темы (не короткий label кнопки), user_id — из callback
    assert agent.answer_question.await_args.args[0] == 1
    assert agent.answer_question.await_args.args[1] == TOPICS["labor"][1][0][1]
    # вопрос показан пользователю
    assert any("❓" in c.args[0] for c in cb.message.answer.await_args_list)


@pytest.mark.asyncio
async def test_topic_question_rate_limited():
    repo = InMemoryRepository()
    await repo.set_consent(1, True)
    await repo.check_rate_limit(1, 2)  # исчерпываем лимит=2
    await repo.check_rate_limit(1, 2)
    agent = MagicMock()
    agent.answer_question = AsyncMock()
    cb = _cb(1, "tq:labor:0")

    await on_topic_question(cb, _state(), repo, agent, _cfg(limit=2))

    agent.answer_question.assert_not_awaited()
    assert "запросов" in cb.answer.await_args.args[0].lower()
