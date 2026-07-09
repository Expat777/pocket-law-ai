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

from shared.contracts import Answer, Citation, IngestResult, UserDocument

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


def format_documents_list(docs: list[UserDocument]) -> str:
    """Список загруженных документов (`/documents`). Обычный текст, без MarkdownV2.

    Имена файлов приходят от пользователя, поэтому НЕ выводим их в MarkdownV2 —
    отправляем как обычный текст, чтобы спецсимволы в имени не ломали сообщение.
    """
    if not docs:
        return (
            "📄 У вас пока нет загруженных документов.\n"
            "Пришлите PDF или фото — я учту его содержимое в ответах."
        )
    lines = ["📄 Ваши загруженные документы:", ""]
    for i, d in enumerate(docs, 1):
        name = d.filename or "без названия"
        when = f" · {d.uploaded_at}" if d.uploaded_at else ""
        lines.append(f"{i}. {name} — фрагментов: {d.chunks}{when}")
    lines.append("")
    lines.append("Удалить все свои данные и документы — /delete.")
    return "\n".join(lines)


def format_album_result(
    ok: list[tuple[str, int]], failed: list[tuple[str, str]]
) -> str:
    """Сводка приёма альбома (несколько файлов разом). Обычный текст — имена не в MarkdownV2."""
    lines: list[str] = []
    if ok:
        total = sum(chunks for _, chunks in ok)
        lines.append(f"✅ Принято документов: {len(ok)} (фрагментов: {total})")
        lines += [f"  • {name} — {chunks}" for name, chunks in ok]
    if failed:
        if ok:
            lines.append("")
        lines.append(f"⚠️ Не приняты: {len(failed)}")
        lines += [f"  • {name} — {reason}" for name, reason in failed]
    if not lines:
        return "Не удалось обработать файлы."
    lines.append("")
    lines.append("Список загруженного — /documents.")
    return "\n".join(lines)


def format_ingest_result(result: IngestResult) -> str:
    """Ответ на загрузку документа (задача MVP 5)."""
    if not result.ok:
        reason = escape_md(result.error or "не удалось обработать документ")
        return f"⚠️ Документ не принят: {reason}\\."
    return (
        f"✅ Документ принят, обработано фрагментов: *{result.chunks}*\\.\n"
        f"Теперь можно задать вопрос — учту содержимое документа\\."
    )


def format_export_text(question: str, answer: Answer, when: str) -> str:
    """«Памятка» для скачивания — ЧИСТЫЙ текст (.txt), читается в любом просмотрщике.

    Без Markdown-разметки (`#`/`**`/`-`) — обычный пользователь открыл бы .md и увидел
    сырые символы. Структура — заголовками капсом, разделителями и «•». Оформлена как
    СПРАВКА, не заключение: дисклеймер сверху и снизу, явно «не официальный документ».
    """
    sep = "─" * 40
    lines = [
        "СПРАВОЧНАЯ ИНФОРМАЦИЯ ПО ВАШЕМУ ВОПРОСУ",
        f"Сгенерировано ботом pocket-law-ai · {when}",
        "Носит справочный характер, не является юридической консультацией.",
        sep,
        "",
        "ВОПРОС:",
        question.strip(),
        "",
        "ОТВЕТ:",
        answer.text.strip() or "—",
        "",
    ]
    if answer.citations:
        lines.append("ОСНОВАНИЕ:")
        for c in answer.citations:
            rev = c.revision_date.strftime("%d.%m.%Y")
            lines.append(f"• ст. {c.article} {c.act} (ред. от {rev})")
            if c.source_url:
                lines.append(f"  {c.source_url}")
        lines.append("")
    lines += [
        sep,
        "⚠️ НЕ является юридической консультацией и НЕ является официальным документом.",
        "Информация носит справочный характер. Проверьте актуальность нормы.",
        "При важных вопросах обратитесь к юристу.",
    ]
    return "\n".join(lines)


def _wrap_line(text: str, font, size: float, max_w: float) -> list[str]:
    """Перенос одной строки по ширине max_w (слова; сверхдлинное слово/URL — жёстко)."""
    if not text:
        return [""]
    out: list[str] = []
    cur = ""
    for word in text.split(" "):
        trial = word if not cur else f"{cur} {word}"
        if font.text_length(trial, size) <= max_w:
            cur = trial
            continue
        if cur:
            out.append(cur)
            cur = ""
        if font.text_length(word, size) > max_w:  # длинное слово/URL — режем посимвольно
            chunk = ""
            for ch in word:
                if font.text_length(chunk + ch, size) <= max_w:
                    chunk += ch
                else:
                    out.append(chunk)
                    chunk = ch
            cur = chunk
        else:
            cur = word
    if cur:
        out.append(cur)
    return out


def format_export_pdf(question: str, answer: Answer, when: str) -> bytes:
    """Та же «памятка», что и .txt, но в PDF — читабельно и печатно для юзера.

    Рендер через PyMuPDF (уже зависимость проекта) встроенным шрифтом `helv`
    (покрывает кириллицу) — без внешних TTF и без новых зависимостей.
    """
    import fitz  # локальный импорт: нужен только здесь (тяжёлая зависимость)

    text = format_export_text(question, answer, when)
    font = fitz.Font("helv")
    size, margin, lead = 11, 50.0, 15.9  # lead = size * 1.45
    doc = fitz.open()
    try:
        page = doc.new_page()
        max_w = page.rect.width - 2 * margin
        writer = fitz.TextWriter(page.rect)
        y = margin + size
        for paragraph in text.split("\n"):
            for line in _wrap_line(paragraph, font, size, max_w):
                if y > page.rect.height - margin:
                    writer.write_text(page)
                    page = doc.new_page()
                    writer = fitz.TextWriter(page.rect)
                    y = margin + size
                if line:
                    writer.append((margin, y), line, font=font, fontsize=size)
                y += lead
        writer.write_text(page)
        return doc.tobytes()
    finally:
        doc.close()
