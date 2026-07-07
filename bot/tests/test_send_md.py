"""Тесты разбивки длинных сообщений (`_split_md`) — дисклеймер не должен теряться."""

from bot.formatter import DISCLAIMER, escape_md
from bot.handlers.content import _TG_LIMIT, _split_md

_DISC = escape_md(DISCLAIMER)


def test_short_message_single_part():
    assert _split_md("короткий ответ") == ["короткий ответ"]


def test_paragraph_split_keeps_disclaimer_in_last_part():
    blocks = ["Б" * 2500, "О" * 2500, _DISC]  # суммарно > лимита
    parts = _split_md("\n\n".join(blocks))
    assert len(parts) >= 2
    assert all(len(p) <= _TG_LIMIT for p in parts)
    assert _DISC in parts[-1]  # обязательный дисклеймер (152-ФЗ) сохранён


def test_single_huge_block_hard_split_but_all_le_limit():
    parts = _split_md("А" * (_TG_LIMIT * 2 + 100) + "\n\n" + _DISC)
    assert all(len(p) <= _TG_LIMIT for p in parts)
    assert _DISC in parts[-1]
