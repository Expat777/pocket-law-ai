"""ingest_document (Роль 2): загруженный документ -> user_documents в Qdrant.

Поток: parse_pdf -> чанки -> эмбеддинги (passage) -> upsert с ОБЯЗАТЕЛЬНЫМ
user_id в payload (изоляция по пользователю, схема 3.3). Зависимости (parse/
embed/upsert) внедряются — так поток тестируется без Qdrant/OCR/модели.
"""

import os
import uuid
from datetime import datetime, timezone

from shared.contracts import IngestResult

USER_DOCS_COLLECTION = "user_documents"
MAX_CHUNK_CHARS = int(os.getenv("USER_DOC_CHUNK_CHARS", "1500"))


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


async def _upsert_user_docs(user_id, doc_id, chunks, vectors) -> None:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointStruct

    client = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    now = datetime.now(timezone.utc).isoformat()
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={
                "user_id": user_id,  # изоляция: без этого поля search_law не отфильтрует
                "doc_id": doc_id,
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
    parse=None,
    embed=None,
    upsert=None,
) -> IngestResult:
    """Контракт 3.1. parse/embed/upsert внедряемы (для тестов); по умолчанию боевые."""
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

    chunks = _chunk(parsed.text)
    doc_id = str(uuid.uuid4())
    try:
        vectors = embed(chunks)
        await upsert(user_id, doc_id, chunks, vectors)
    except Exception as e:  # noqa: BLE001
        return IngestResult(doc_id=doc_id, chunks=0, ok=False, error=f"index: {e}")

    return IngestResult(doc_id=doc_id, chunks=len(chunks), ok=True)