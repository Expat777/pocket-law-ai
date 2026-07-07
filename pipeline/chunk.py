"""chunk: статья -> чанки для Qdrant.

Разрез строго по статьям (контракт TEAM_PLAN 3.3); статьи длиннее MAX_CHUNK_CHARS
дорезаются по абзацам, каждый чанк несёт полные метаданные своей статьи.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from .config import MAX_CHUNK_CHARS
from .parse import Article

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "pocket-law-ai/law_articles")


@dataclass
class Chunk:
    id: str            # детерминированный uuid5 -> повторный прогон не плодит дубликатов
    text: str          # то, что эмбеддится и попадает в payload.text
    payload: dict      # схема 3.3: act, article_no, chapter, status, effective_date, text


def _split_paragraphs(paragraphs: list[str], limit: int) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for p in paragraphs:
        if buf and size + len(p) > limit:
            parts.append("\n".join(buf))
            buf, size = [], 0
        buf.append(p)
        size += len(p)
    if buf:
        parts.append("\n".join(buf))
    return parts


def chunk_article(
    article: Article, effective_date: date | None = None, source_url: str | None = None
) -> list[Chunk]:
    header = f"{article.act}, статья {article.article_no}. {article.title}".strip()
    paragraphs = [p for p in article.text.split("\n") if p.strip()]
    pieces = _split_paragraphs(paragraphs, MAX_CHUNK_CHARS) or [""]

    chunks = []
    for i, piece in enumerate(pieces):
        text = f"{header}\n{piece}".strip()
        chunk_id = str(uuid.uuid5(_NAMESPACE, f"{article.act}:{article.article_no}:{i}"))
        chunks.append(Chunk(
            id=chunk_id,
            text=text,
            payload={
                "act": article.act,
                "article_no": article.article_no,
                "chapter": article.chapter,
                "status": article.status,
                # дата последней редакции документа; по-статейно — фаза 2 (SOURCE.md)
                "effective_date": effective_date.isoformat() if effective_date else None,
                # ссылка на акт целиком (Роль 2 -> Citation.source_url -> кликабельно у Роли 1)
                "source_url": source_url,
                "text": text,
            },
        ))
    return chunks
