"""ingest_document (Роль 2): загруженный документ -> user_documents в Qdrant.

Поток: parse_pdf -> чанки -> эмбеддинги (passage) -> upsert с ОБЯЗАТЕЛЬНЫМ
user_id в payload (изоляция по пользователю, схема 3.3). Зависимости (parse/
embed/upsert) внедряются — так поток тестируется без Qdrant/OCR/модели.
"""

import os
import re
import uuid
from datetime import datetime, timezone

from shared.contracts import IngestResult

USER_DOCS_COLLECTION = "user_documents"
MAX_CHUNK_CHARS = int(os.getenv("USER_DOC_CHUNK_CHARS", "1500"))

# Гейт качества OCR: сколько «словоподобных» токенов (≥3 букв) минимум должно быть,
# чтобы считать распознанное настоящим текстом документа. Мусорный OCR фото
# (несколько знаков пунктуации, «— | | ГА») иначе проходил бы пустой-check и уходил
# в doc-режим, где модель ДОСТРАИВАЕТ несуществующий документ (живой баг: фото
# каракулей → «свидетельство о регистрации акта… ст. 8 Закона об АГС», всё выдумано).
OCR_MIN_WORDS = int(os.getenv("OCR_MIN_WORDS", "4"))
_WORD_RE = re.compile(r"[а-яёa-z]{3,}", re.IGNORECASE)


def _has_meaningful_text(text: str) -> bool:
    """Похоже ли распознанное на реальный текст, а не на OCR-мусор.

    Считаем словоподобные токены (последовательности ≥3 букв кириллицы/латиницы):
    у настоящего документа их много, у шумовой картинки — почти нет. Порог низкий,
    чтобы не отсечь короткие реальные документы (квитанция, уведомление).
    """
    return len(_WORD_RE.findall(text or "")) >= OCR_MIN_WORDS


def _chunk(text: str) -> list[str]:
    """Режем по абзацам, склеивая до предела длины; фолбэк — по символам."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > MAX_CHUNK_CHARS:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    if not chunks and text.strip():
        t = text.strip()
        chunks = [t[i : i + MAX_CHUNK_CHARS] for i in range(0, len(t), MAX_CHUNK_CHARS)]
    return chunks


_qdrant = None


def _qdrant_client():
    # Кэш клиента (как в documents.py): новый AsyncQdrantClient на каждую загрузку
    # плодил бы соединения (аудит зоны).
    global _qdrant
    if _qdrant is None:
        from qdrant_client import AsyncQdrantClient

        _qdrant = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    return _qdrant


async def _upsert_user_docs(user_id, doc_id, chunks, vectors, filename=None) -> None:
    from qdrant_client.models import PointStruct

    client = _qdrant_client()
    now = datetime.now(timezone.utc).isoformat()
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={
                "user_id": user_id,  # изоляция: без этого поля search_law не отфильтрует
                "doc_id": doc_id,
                "filename": filename,  # имя для списка/выбора документа (UI Роли 1)
                "chunk_no": i,
                "text": chunk,
                "uploaded_at": now,
            },
        )
        for i, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    await client.upsert(collection_name=USER_DOCS_COLLECTION, points=points, wait=True)


async def ingest_document(
    user_id: int,
    file_bytes: bytes,
    mime: str,
    *,
    filename: str | None = None,
    parse=None,
    embed=None,
    upsert=None,
) -> IngestResult:
    """Контракт 3.1. filename — имя для списка документов (UI Роли 1), опционально.
    parse/embed/upsert внедряемы (для тестов); по умолчанию боевые."""
    if parse is None:
        from .tools.parse_pdf import parse_pdf as parse
    if embed is None:
        from .tools.embed import embed_passages as embed
    if upsert is None:
        upsert = _upsert_user_docs

    try:
        parsed = parse(file_bytes, mime)
    except Exception as e:  # noqa: BLE001 — вернуть ошибку в контракте, не падать
        return IngestResult(doc_id="", chunks=0, ok=False, error=f"parse: {e}")

    if not parsed.text.strip():
        return IngestResult(
            doc_id="", chunks=0, ok=False,
            error="не удалось извлечь текст (пустой документ или нераспознанный скан)",
        )

    # Гейт качества OCR: скудный/мусорный результат распознавания фото НЕ пускаем
    # дальше — иначе doc-режим сочинит несуществующий документ по нескольким шумовым
    # символам. Текстовый слой PDF (used_ocr=False) считаем надёжным и не режем.
    if parsed.used_ocr and not _has_meaningful_text(parsed.text):
        return IngestResult(
            doc_id="", chunks=0, ok=False,
            error="не удалось разобрать текст на изображении — пришлите более чёткое фото или файл PDF",
        )

    chunks = _chunk(parsed.text)
    doc_id = str(uuid.uuid4())
    try:
        vectors = embed(chunks)
        await upsert(user_id, doc_id, chunks, vectors, filename=filename)
    except Exception as e:  # noqa: BLE001
        return IngestResult(doc_id=doc_id, chunks=0, ok=False, error=f"index: {e}")

    return IngestResult(doc_id=doc_id, chunks=len(chunks), ok=True)


async def ingest_url(
    user_id: int,
    url: str,
    *,
    filename: str | None = None,
    fetch=None,
    embed=None,
    upsert=None,
) -> IngestResult:
    """Скачивает документ по URL (SSRF-безопасно) и индексирует в user_documents.

    Контент по ссылке трактуется так же, как загруженный файл: недоверенные
    данные (см. SECURITY_RULES) с обязательной изоляцией по user_id. Поддержка:
    PDF/фото (OCR), HTML (текст), text/*.
    """
    if fetch is None:
        from .tools.fetch_url import fetch_url as fetch

    try:
        data, mime = await fetch(url)
    except Exception as e:  # noqa: BLE001 — вернуть ошибку в контракте, не падать
        return IngestResult(doc_id="", chunks=0, ok=False, error=f"fetch: {e}")

    from .tools.extract import extract_document

    return await ingest_document(
        user_id, data, mime,
        filename=filename or url,  # по умолчанию показываем саму ссылку
        parse=extract_document, embed=embed, upsert=upsert,
    )