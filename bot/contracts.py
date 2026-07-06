"""Контракты бот ↔ оркестратор.

ВРЕМЕННОЕ ЛОКАЛЬНОЕ ЗЕРКАЛО раздела 3.1 TEAM_PLAN.md.
Роль 4 переносит контракты в `shared/contracts.py` в день 1 (точка И0).
После И0 этот файл удаляется, а импорты меняются на:

    from shared.contracts import Answer, Citation, IngestResult

Пока `shared/` нет — бот пишется строго по этому зеркалу (1-в-1 с разделом 3.1),
чтобы не редактировать чужую папку `shared/`.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Citation(BaseModel):
    act: str  # "ТК РФ"
    article: str  # "81"
    revision_date: date
    source_url: str | None = None


class Answer(BaseModel):
    text: str  # готовый текст ответа, простым языком
    citations: list[Citation] = []  # минимум 1, если refused=False
    refused: bool = False  # True = честный отказ (данных нет)
    clarifying_question: str | None = None  # если задан — бот показывает его вместо ответа


class IngestResult(BaseModel):
    doc_id: str
    chunks: int
    ok: bool
    error: str | None = None
