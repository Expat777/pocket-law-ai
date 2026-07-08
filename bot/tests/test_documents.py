"""Управление документами (бот-часть предложения Роли 1):
- /documents — список загруженного;
- /delete — чистит и Postgres, и user_documents в Qdrant (152-ФЗ);
- имя файла прокидывается в ingest_document → попадает в список.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.formatter import format_documents_list
from bot.handlers.commands import cmd_delete, cmd_documents
from bot.mock_agent import MockAgent
from bot.repository import InMemoryRepository
from shared.contracts import UserDocument


def _fake_message(uid: int = 42):
    msg = MagicMock()
    msg.from_user = MagicMock(id=uid, username="u")
    msg.chat = MagicMock(id=uid)
    msg.answer = AsyncMock()
    return msg


def _fake_state():
    state = MagicMock()
    state.clear = AsyncMock()
    return state


def test_format_documents_list_empty():
    out = format_documents_list([])
    assert "пока нет загруженных" in out


def test_format_documents_list_nonempty():
    docs = [
        UserDocument(doc_id="a", filename="договор.pdf", chunks=3),
        UserDocument(doc_id="b", filename=None, chunks=1),
    ]
    out = format_documents_list(docs)
    assert "договор.pdf" in out
    assert "без названия" in out          # filename=None → подпись
    assert "1." in out and "2." in out    # нумерация


@pytest.mark.asyncio
async def test_documents_command_lists_ingested():
    agent = MockAgent()
    await agent.ingest_document(42, b"x" * 5000, "application/pdf", filename="дог.pdf")
    msg = _fake_message(42)
    await cmd_documents(msg, agent)
    out = msg.answer.await_args.args[0]
    assert "дог.pdf" in out


@pytest.mark.asyncio
async def test_delete_purges_documents_and_postgres():
    agent = MockAgent()
    repo = InMemoryRepository()
    await agent.ingest_document(42, b"x" * 5000, "application/pdf", filename="дог.pdf")
    assert await agent.list_user_documents(42)  # документ есть

    msg = _fake_message(42)
    await cmd_delete(msg, _fake_state(), repo, agent)

    assert await agent.list_user_documents(42) == []  # 152-ФЗ: документы вычищены
    assert "загруженные документы" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_delete_survives_agent_purge_error():
    """Сбой очистки Qdrant не роняет /delete (Postgres уже очищен)."""
    agent = MagicMock()
    agent.delete_user_documents = AsyncMock(side_effect=RuntimeError("qdrant down"))
    repo = InMemoryRepository()
    msg = _fake_message(42)

    await cmd_delete(msg, _fake_state(), repo, agent)  # не должно бросить

    msg.answer.assert_awaited_once()  # пользователь всё равно получил подтверждение
