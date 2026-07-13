"""Голосовой ввод (STT): voice → transcribe_voice → эхо распознанного → обычный ответ.

Согласие/лимит навешаны мидлварями content_router — тут проверяем логику самого
хендлера (скачивание, распознавание, эхо, проброс в поток вопроса, деградации)."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.content import _MAX_VOICE_SEC, on_voice
from bot.repository import InMemoryRepository
from bot.states import Dialog
from shared.contracts import Answer

_ANSWER = Answer(text="ответ по существу", citations=[], refused=False)


class _FakeState:
    def __init__(self):
        self._state = None
        self._data = {}

    async def set_state(self, s):
        self._state = getattr(s, "state", s)

    async def get_state(self):
        return self._state

    async def update_data(self, **kw):
        self._data.update(kw)

    async def get_data(self):
        return dict(self._data)


def _fake_voice_message(uid, *, duration=5, size=2000, audio=b"OggS____voice"):
    m = MagicMock()
    m.text = None
    m.from_user = MagicMock(id=uid, username="u")
    m.chat = MagicMock(id=uid)
    m.voice = MagicMock(file_id="vfid", file_size=size, duration=duration)
    m.bot = MagicMock()
    m.bot.send_chat_action = AsyncMock()

    async def _dl(file_id, destination):
        destination.write(audio)

    m.bot.download = AsyncMock(side_effect=_dl)
    m.answer = AsyncMock()
    return m


def _agent(transcript="могут ли уволить в отпуске?"):
    a = MagicMock()
    a.transcribe_voice = AsyncMock(return_value=transcript)
    a.answer_question = AsyncMock(return_value=_ANSWER)
    return a


async def _call(msg, agent, state=None):
    await on_voice(
        msg, state or _FakeState(), InMemoryRepository(), agent,
        msg.bot, max_file_bytes=20 * 1024 * 1024,
    )


@pytest.mark.asyncio
async def test_voice_transcribed_echoed_and_answered():
    uid = 801
    msg = _fake_voice_message(uid)
    agent = _agent("сколько дней отпуска?")

    await _call(msg, agent)

    # распознали именно скачанные байты
    agent.transcribe_voice.assert_awaited_once()
    assert agent.transcribe_voice.await_args.args[0] == uid
    # эхо распознанного показано пользователю
    assert any("🎙" in c.args[0] and "сколько дней отпуска?" in c.args[0]
               for c in msg.answer.await_args_list)
    # распознанный текст ушёл в обычный поток вопроса
    agent.answer_question.assert_awaited_once()
    assert agent.answer_question.await_args.args[1] == "сколько дней отпуска?"


@pytest.mark.asyncio
async def test_empty_transcription_asks_to_retry():
    uid = 802
    msg = _fake_voice_message(uid)
    agent = _agent(transcript="   ")  # тишина/неразборчиво

    await _call(msg, agent)

    agent.answer_question.assert_not_awaited()  # в агента вопрос не уходит
    assert any("разобрал" in c.args[0].lower() for c in msg.answer.await_args_list)


@pytest.mark.asyncio
async def test_too_long_voice_rejected():
    uid = 803
    msg = _fake_voice_message(uid, duration=_MAX_VOICE_SEC + 1)
    agent = _agent()

    await _call(msg, agent)

    agent.transcribe_voice.assert_not_awaited()  # даже не скачиваем/не распознаём
    msg.bot.download.assert_not_awaited()
    assert any("длинное" in c.args[0].lower() for c in msg.answer.await_args_list)


@pytest.mark.asyncio
async def test_transcribe_failure_degrades_softly():
    uid = 804
    msg = _fake_voice_message(uid)
    agent = _agent()
    agent.transcribe_voice = AsyncMock(side_effect=RuntimeError("stt down"))

    await _call(msg, agent)

    agent.answer_question.assert_not_awaited()
    assert any("распознать" in c.args[0].lower() for c in msg.answer.await_args_list)


@pytest.mark.asyncio
async def test_voice_reply_keeps_clarification_context():
    """Голосом отвечают на переспрос → склейка с исходным вопросом (как для текста)."""
    uid = 805
    state = _FakeState()
    state._state = Dialog.awaiting_clarification.state
    state._data = {"pending_question": "можно ли уволить?", "pending_clarify": "трудовой или ГПХ?"}
    msg = _fake_voice_message(uid)
    agent = _agent(transcript="трудовой")

    await _call(msg, agent, state)

    sent = agent.answer_question.await_args.args[1]
    assert "можно ли уволить?" in sent and "трудовой" in sent
