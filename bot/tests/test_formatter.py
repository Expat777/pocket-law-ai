"""Оффлайн-тесты форматтера (формат 3.5) — без Telegram и без сети."""

from datetime import date

from bot.contracts import Answer, Citation, IngestResult
from bot.formatter import (
    DISCLAIMER,
    escape_md,
    format_answer,
    format_answer_message,
    format_ingest_result,
)


def test_escape_md_covers_all_specials():
    assert escape_md("ст. 81 (ред.)!") == "ст\\. 81 \\(ред\\.\\)\\!"
    for ch in r"_*[]()~`>#+-=|{}.!":
        assert escape_md(ch) == "\\" + ch


def test_format_answer_has_text_basis_and_disclaimer():
    ans = Answer(
        text="Уволить в отпуске нельзя.",
        citations=[Citation(act="ТК РФ", article="81", revision_date=date(2024, 11, 1))],
    )
    out = format_answer(ans)
    assert "Уволить в отпуске нельзя" in out
    assert "Основание" in out
    assert "81" in out and "ТК РФ" in out
    assert escape_md(DISCLAIMER) in out
    # ни одной «голой» точки — всё экранировано
    assert ". " not in out.replace("\\. ", "")


def test_format_answer_message_routes_clarify_and_refuse():
    clarify = Answer(text="", clarifying_question="Уточните статус работника?")
    assert format_answer_message(clarify).startswith("❓")

    refused = Answer(text="Не нашёл норму.", refused=True)
    out = format_answer_message(refused)
    assert out.startswith("⚠️")
    assert escape_md(DISCLAIMER) in out


def test_citation_with_source_url_builds_markdown_link():
    ans = Answer(
        text="Текст.",
        citations=[
            Citation(
                act="ТК РФ",
                article="81",
                revision_date=date(2024, 11, 1),
                source_url="http://pravo.gov.ru/doc",
            )
        ],
    )
    out = format_answer(ans)
    assert "](http://pravo.gov.ru/doc)" in out


def test_ingest_result_ok_and_error():
    ok = format_ingest_result(IngestResult(doc_id="x", chunks=3, ok=True))
    assert "3" in ok and "принят" in ok
    bad = format_ingest_result(IngestResult(doc_id="", chunks=0, ok=False, error="пусто"))
    assert "не принят" in bad
