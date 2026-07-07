"""Извлечение текста из скачанного контента по MIME-типу.

PDF/фото -> parse_pdf (OCR); HTML -> текст без тегов; text/* -> как есть.
Возвращает ParsedDoc — дальше идёт обычный pipeline ingest (chunk/embed/upsert).
"""

import html as _html
import re

from shared.contracts import ParsedDoc


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _html_to_text(data: bytes) -> str:
    txt = _decode(data)
    txt = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", txt)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)  # снять теги
    txt = _html.unescape(txt)
    txt = re.sub(r"[ \t\r\f]+", " ", txt)
    txt = re.sub(r"\n[ \t]*\n[ \t]*(\n)+", "\n\n", txt)
    return txt.strip()


def extract_document(file_bytes: bytes, mime: str) -> ParsedDoc:
    """Роутер по MIME. Для ingest_url; сигнатура совместима с parse (file_bytes, mime)."""
    m = (mime or "").lower()
    if m == "application/pdf" or m.startswith("image/"):
        from .parse_pdf import parse_pdf

        return parse_pdf(file_bytes, mime)
    if m.startswith("text/html") or m == "application/xhtml+xml":
        return ParsedDoc(text=_html_to_text(file_bytes), pages=1, used_ocr=False)
    if m.startswith("text/"):
        return ParsedDoc(text=_decode(file_bytes).strip(), pages=1, used_ocr=False)
    raise ValueError(f"неподдерживаемый тип для извлечения текста: {mime or 'неизвестно'}")