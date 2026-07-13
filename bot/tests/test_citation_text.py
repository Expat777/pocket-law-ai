"""Рендер дословной выдержки статьи (Citation.text, контракт 2б) — в ответе и памятке.

Роль 2 (verify) кладёт короткую выдержку в Citation.text; наш форматтер показывает её
под «Основание», чтобы не гонять пользователя по ссылке. Поле опционально —
без него всё как раньше (обратная совместимость)."""

from datetime import date

from bot.formatter import (
    _EXCERPT_TG_LIMIT,
    format_answer,
    format_export_text,
)
from shared.contracts import Answer, Citation

_ARTICLE = (
    "Расторжение трудового договора по инициативе работодателя допускается "
    "в случаях, предусмотренных настоящей статьёй, с соблюдением установленного порядка."
)


def _cit(text=None, article="81", url=None):
    return Citation(
        act="ТК РФ",
        article=article,
        revision_date=date(2024, 11, 1),
        source_url=url,
        text=text,
    )


def test_excerpt_shown_under_single_citation():
    out = format_answer(Answer(text="ответ", citations=[_cit(_ARTICLE)], refused=False))
    assert "Расторжение трудового договора" in out  # выдержка попала в сообщение
    assert "«" in out and "»" in out  # оформлена кавычками-ёлочками


def test_excerpt_shown_for_each_of_several_citations():
    ans = Answer(
        text="ответ",
        citations=[_cit("Первая норма про увольнение.", "81"),
                   _cit("Вторая норма про отпуск.", "127")],
        refused=False,
    )
    out = format_answer(ans)
    assert "Первая норма про увольнение" in out
    assert "Вторая норма про отпуск" in out


def test_no_text_keeps_old_output():
    """Цитата без text → выдержки нет, лишних кавычек не появляется (совместимость)."""
    out = format_answer(Answer(text="ответ", citations=[_cit(None)], refused=False))
    assert "«" not in out and "»" not in out
    assert "ст\\. 81 ТК РФ" in out  # сама цитата на месте (MarkdownV2)


def test_long_excerpt_truncated_in_telegram():
    long_text = "слово " * 200  # заведомо длиннее лимита
    out = format_answer(Answer(text="ответ", citations=[_cit(long_text)], refused=False))
    assert "…" in out  # обрезано многоточием
    # длина выдержки ограничена лимитом (± служебные символы)
    excerpt = out.split("«", 1)[1].split("»", 1)[0]
    assert len(excerpt) <= _EXCERPT_TG_LIMIT + 1


def test_excerpt_in_export_memo():
    memo = format_export_text("вопрос?", Answer(text="ответ", citations=[_cit(_ARTICLE)], refused=False), "13.07.2026")
    assert "ОСНОВАНИЕ:" in memo
    assert "Расротжение" not in memo  # sanity: без опечаток
    assert "Расторжение трудового договора" in memo  # выдержка в памятке
