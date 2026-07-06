"""Response Formatter (задача MVP 6, владение формата — раздел 3.5).

Структура ответа ВСЕГДА:
    ответ простым языком
    → блок «Основание: ст. N …»
    → строка дисклеймера «Не является юридической консультацией».

Всё выводится в MarkdownV2, поэтому любой текст из агента экранируется
`escape_md`, иначе Telegram отклонит сообщение на спецсимволах (точка, дефис,
скобки в номерах статей и т.п.).
"""

from __future__ import annotations

from bot.contracts import Answer, Citation, IngestResult

DISCLAIMER = "Не является юридической консультацией."

# Спецсимволы MarkdownV2, требующие экранирования обратным слэшем.
# https://core.telegram.org/bots/api#markdownv2-style
_MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
_TRANSLATION = {ord(ch): f"\\{ch}" for ch in _MDV2_SPECIALS}


def escape_md(text: str) -> str:
    """Экранирует все спецсимволы MarkdownV2 в обычном тексте."""
    return text.translate(_TRANSLATION)


def _format_citation(c: Citation) -> str:
    # «ст. 81 ТК РФ (ред. от 01.11.2024)» + опциональная ссылка
    rev = c.revision_date.strftime("%d.%m.%Y")
    line = f"ст\\. {escape_md(c.article)} {escape_md(c.act)} \\(ред\\. от {escape_md(rev)}\\)"
    if c.source_url:
        # url в () MarkdownV2-ссылки экранируется по своим правилам: \ и )
        safe_url = c.source_url.replace("\\", "\\\\").replace(")", "\\)")
        line = f"[{line}]({safe_url})"
    return line


def _basis_block(citations: list[Citation]) -> str:
    if not citations:
        return ""
    if len(citations) == 1:
        return f"*Основание:* {_format_citation(citations[0])}"
    items = "\n".join(f"• {_format_citation(c)}" for c in citations)
    return f"*Основание:*\n{items}"


def _disclaimer_line() -> str:
    return f"_{escape_md(DISCLAIMER)}_"


def format_answer(answer: Answer) -> str:
    """Готовое сообщение по ветке `answer` контракта 3.1 (не refused/clarify).

    Собирает: текст → «Основание: …» → дисклеймер. Всегда с MarkdownV2-экранированием.
    """
    parts = [escape_md(answer.text.strip())]

    basis = _basis_block(answer.citations)
    if basis:
        parts.append(basis)

    parts.append(_disclaimer_line())
    return "\n\n".join(p for p in parts if p)


def format_clarifying(question: str) -> str:
    """Ветка `clarifying_question`: бот переспрашивает вместо ответа."""
    return f"❓ {escape_md(question.strip())}"


def format_refused(answer: Answer) -> str:
    """Ветка `refused=True`: честный отказ, без цитат, но с дисклеймером."""
    text = answer.text.strip() or "Не нашёл подходящей нормы в базе законов."
    return f"⚠️ {escape_md(text)}\n\n{_disclaimer_line()}"


def format_answer_message(answer: Answer) -> str:
    """Единая точка: выбирает ветку по контракту и возвращает готовый текст.

    Приоритет как в разделе 4 (задачи 3–4): clarifying → refused → обычный ответ.
    """
    if answer.clarifying_question:
        return format_clarifying(answer.clarifying_question)
    if answer.refused:
        return format_refused(answer)
    return format_answer(answer)


def format_ingest_result(result: IngestResult) -> str:
    """Ответ на загрузку документа (задача MVP 5)."""
    if not result.ok:
        reason = escape_md(result.error or "не удалось обработать документ")
        return f"⚠️ Документ не принят: {reason}\\."
    return (
        f"✅ Документ принят, обработано фрагментов: *{result.chunks}*\\.\n"
        f"Теперь можно задать вопрос — учту содержимое документа\\."
    )
