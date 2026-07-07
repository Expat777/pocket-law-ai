FROM python:3.11-slim

# tesseract-ocr-rus: agent/tools/parse_pdf.py гоняет OCR со scan/фото в lang=rus+eng
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY shared/ shared/
COPY agent/ agent/
COPY bot/ bot/
COPY pipeline/ pipeline/
RUN pip install --no-cache-dir .

CMD ["python", "-m", "bot.main"]
