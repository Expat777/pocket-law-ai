"""Контракты между зонами проекта. См. TEAM_PLAN.md, раздел 3.

Меняется только через PR с тегом всех четырёх ролей.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

# --- 3.1 Бот <-> Оркестратор (потребитель: Роль 1, поставщик: Роль 2) ---


class Citation(BaseModel):
    act: str  # "ТК РФ"
    article: str  # "81"
    revision_date: date
    source_url: str | None = None


class Answer(BaseModel):
    text: str  # готовый текст ответа, простым языком
    citations: list[Citation]  # минимум 1, если refused=False
    refused: bool = False  # True = честный отказ (данных нет)
    clarifying_question: str | None = None  # если задан — бот показывает его вместо ответа


class IngestResult(BaseModel):
    doc_id: str
    chunks: int
    ok: bool
    error: str | None = None


async def answer_question(user_id: int, text: str) -> Answer: ...


async def ingest_document(user_id: int, file_bytes: bytes, mime: str) -> IngestResult: ...


# --- 3.2 Оркестратор <-> Хранилища (потребитель: Роль 2, поставщики: Роли 3 и 4) ---


class RetrievedChunk(BaseModel):
    text: str
    source: Literal["law", "user_doc"]
    act: str | None = None
    article: str | None = None
    status: Literal["active", "amended", "repealed"] | None = None
    effective_date: date | None = None
    source_url: str | None = None
    score: float


class CitationStatus(BaseModel):
    exists: bool
    active: bool
    current_revision: date | None = None


class ParsedDoc(BaseModel):
    text: str
    pages: int
    used_ocr: bool


async def search_law(
    query: str, user_id: int | None, acts: list[str] | None = None
) -> list[RetrievedChunk]:
    """Гибридный поиск: law_articles всегда + user_documents этого user_id, если есть.

    acts: сузить поиск до этих значений `act` (мультикодексная база); None/пусто — без фильтра.
    """
    ...


async def verify_citation(citation: Citation) -> CitationStatus:
    """Существует ли статья и действует ли редакция."""
    ...


def parse_pdf(file_bytes: bytes, mime: str) -> ParsedDoc:
    """Текст из PDF/фото; OCR для сканов."""
    ...
