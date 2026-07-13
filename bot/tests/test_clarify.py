"""Контекст уточнения: бот переспросил → ответ пользователя склеивается с исходным
вопросом (агент безстейтовый, иначе уточнение уходит как новый вопрос — баг с теста)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import on_question
from bot.repository import InMemoryRepository
from bot.states import Dialog
from shared.contracts import Answer


class _FakeState:
    """Мини-FSMContext: хранит состояние и data (MagicMock их не отслеживает)."""

    def __init__(self):
        self._state = None
        self._data = {}

    async def set_state(self, s):
        self._state = getattr(s, "state", s)

    async def get_state(self):
        return self._state

    async def update_data(self, **kw):
        self._data.update(kw)
        return dict(self._data)

    async def get_data(self):
        return dict(self._data)


def _fake_message(text: str, uid: int):
    msg = MagicMock()
    msg.text = text
    msg.from_user = MagicMock(id=uid, username="u")
    msg.chat = MagicMock(id=uid)
    msg.bot = MagicMock()
    msg.bot.send_chat_action = AsyncMock()
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_clarification_reply_keeps_original_question():
    uid = 701
    agent = MagicMock()
    agent.answer_question = AsyncMock(
        side_effect=[
            Answer(
                text="Уточните, пожалуйста.",
                citations=[],
                refused=False,
                clarifying_question="У вас трудовой договор или ГПХ?",
            ),
            Answer(text="Ответ по существу.", citations=[], refused=False),
        ]
    )
    state = _FakeState()

    # 1) исходный вопрос → агент переспрашивает, ждём уточнение
    await on_question(_fake_message("могут ли меня уволить?", uid), state, InMemoryRepository(), agent)
    assert state._state == Dialog.awaiting_clarification.state

    # 2) короткое уточнение одним словом
    await on_question(_fake_message("трудовой", uid), state, InMemoryRepository(), agent)

    # второй вызов агента получил СКЛЕЙКУ: исходный вопрос + переспрос + ответ
    second_text = agent.answer_question.await_args_list[1].args[1]
    assert "могут ли меня уволить?" in second_text  # исходный вопрос не потерян
    assert "трудовой" in second_text  # ответ пользователя учтён
    assert "ГПХ" in second_text  # варианты из переспроса сохранены
    # после содержательного ответа — обычный режим, pending очищен
    assert state._state == Dialog.normal_question.state
    assert not state._data.get("pending_question")


@pytest.mark.asyncio
async def test_normal_question_not_wrapped():
    """Вне режима уточнения текст уходит агенту как есть (без склейки)."""
    uid = 702
    agent = MagicMock()
    agent.answer_question = AsyncMock(
        return_value=Answer(text="ок", citations=[], refused=False)
    )
    state = _FakeState()

    await on_question(_fake_message("сколько дней отпуска?", uid), state, InMemoryRepository(), agent)

    assert agent.answer_question.await_args.args[1] == "сколько дней отпуска?"
    assert state._state == Dialog.normal_question.state
