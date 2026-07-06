"""Инструмент parse_pdf (Роль 2): PDF/фото -> текст, OCR для сканов.

PyMuPDF (fitz) — извлечение текстового слоя; если его нет (скан) или пришло
фото — OCR через tesseract (pytesseract, язык rus+eng). Импорты ленивые, чтобы
пакет agent импортировался без этих зависимостей (тесты графа их не требуют).

Зависимости запрошены у Роли 4 для pyproject: pymupdf, pytesseract, pillow
(+ системный tesseract-ocr / tesseract-ocr-rus).
"""

from shared.contracts import ParsedDoc

OCR_LANG = "rus+eng"


def _ocr_image_bytes(image_bytes: bytes) -> str:
    import io

    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    return pytesseract.image_to_string(img, lang=OCR_LANG).strip()


def _ocr_pdf(doc) -> str:
    """OCR постранично: рендерим страницу в картинку и распознаём."""
    import io

    import pytesseract
    from PIL import Image

    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        out.append(pytesseract.image_to_string(img, lang=OCR_LANG))
    return "\n".join(out).strip()


def parse_pdf(file_bytes: bytes, mime: str) -> ParsedDoc:
    if not file_bytes:
        return ParsedDoc(text="", pages=0, used_ocr=False)

    # фото — сразу OCR
    if mime.startswith("image/"):
        return ParsedDoc(text=_ocr_image_bytes(file_bytes), pages=1, used_ocr=True)

    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        pages = doc.page_count
        text = "\n".join(page.get_text() for page in doc).strip()
        used_ocr = False
        if not text:  # скан без текстового слоя
            text = _ocr_pdf(doc)
            used_ocr = True
    finally:
        doc.close()

    return ParsedDoc(text=text, pages=pages, used_ocr=used_ocr)