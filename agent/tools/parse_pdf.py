"""Инструмент parse_pdf (Роль 2): PDF/фото -> текст, OCR для сканов.

TODO (слайс 2): PyMuPDF/pdfplumber для PDF, tesseract для сканов. Зависимости
(pymupdf, pytesseract) согласовать с Ролью 4 для pyproject.toml перед реализацией.
"""

from shared.contracts import ParsedDoc


def parse_pdf(file_bytes: bytes, mime: str) -> ParsedDoc:
    raise NotImplementedError("parse_pdf будет реализован во втором слайсе Роли 2")