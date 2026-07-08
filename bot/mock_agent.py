"""Мок агента на старте (задача-мок Роли 1).

Реализует контракт 3.1 (`answer_question` / `ingest_document`) фикстурами,
чтобы бот жил и демонстрировал все три ветки БЕЗ реального `agent/`:

  1) нормальный ответ с цитатой (ст. 81 ТК РФ),
  2) честный отказ (refused=True),
  3) уточняющий вопрос (clarifying_question).

Ветка выбирается по ключевым словам вопроса — этого достаточно для DoD Роли 1.
И1 выполнен: в проде бот использует `agent.Agent` (bot/main.py). MockAgent
остаётся только для юнит-тестов бота (bot/tests) — не требует LLM/Qdrant.
"""

from __future__ import annotations

import uuid
from datetime import date

from shared.contracts import Answer, Citation, IngestResult, UserDocument

# --- фикстуры трёх веток -----------------------------------------------------

_ANSWER_FIXTURE = Answer(
    text=(
        "По общему правилу уволить работника в период его отпуска нельзя. "
        "Расторжение трудового договора по инициативе работодателя во время "
        "отпуска не допускается — кроме случая полной ликвидации организации "
        "либо прекращения деятельности ИП."
    ),
    citations=[
        Citation(
            act="ТК РФ",
            article="81",
            revision_date=date(2024, 11, 1),
            source_url="http://pravo.gov.ru/",
        )
    ],
    refused=False,
    clarifying_question=None,
)

_CLARIFY_FIXTURE = Answer(
    text="",
    citations=[],
    refused=False,
    clarifying_question=(
        "Уточните, пожалуйста: речь про увольнение по инициативе работодателя "
        "или по собственному желанию? И в каком статусе работник — штат, "
        "совместитель, на испытательном сроке?"
    ),
)

_REFUSED_FIXTURE = Answer(
    text=(
        "Не нашёл в доступной базе законов норму, которая прямо отвечает на этот "
        "вопрос. Чтобы не выдумывать — честно отказываюсь ответить. "
        "Попробуйте переформулировать или уточнить отрасль права."
    ),
    citations=[],
    refused=True,
    clarifying_question=None,
)

# Ключевые слова → ветка. Порядок проверки: clarify, refuse, иначе answer.
_CLARIFY_TRIGGERS = ("уволить", "отпуск", "увольн")
_REFUSE_TRIGGERS = ("погода", "рецепт", "asdf", "бессмыслица", "футбол")


class MockAgent:
    """Фикстурная реализация AgentClient. Никаких внешних вызовов.

    Хранит загруженные документы в памяти, чтобы list/delete работали в тестах.
    """

    def __init__(self) -> None:
        self._docs: dict[int, list[UserDocument]] = {}

    async def answer_question(self, user_id: int, text: str) -> Answer:
        low = text.lower().strip()

        if not low or any(t in low for t in _REFUSE_TRIGGERS):
            return _REFUSED_FIXTURE

        # "могут ли уволить в отпуске?" → нормальный ответ с цитатой
        if "уволить" in low and "отпуск" in low:
            return _ANSWER_FIXTURE

        # одиночные триггеры без пары → просим уточнить
        if any(t in low for t in _CLARIFY_TRIGGERS):
            return _CLARIFY_FIXTURE

        return _ANSWER_FIXTURE

    async def ingest_document(
        self, user_id: int, file_bytes: bytes, mime: str, filename: str | None = None
    ) -> IngestResult:
        if not file_bytes:
            return IngestResult(doc_id="", chunks=0, ok=False, error="пустой файл")

        # мок: «нарезал» ~1 фрагмент на каждые 2 КБ
        chunks = max(1, len(file_bytes) // 2048)
        doc_id = uuid.uuid4().hex
        self._docs.setdefault(user_id, []).append(
            UserDocument(doc_id=doc_id, filename=filename, chunks=chunks)
        )
        return IngestResult(doc_id=doc_id, chunks=chunks, ok=True, error=None)

    async def ingest_url(
        self, user_id: int, url: str, filename: str | None = None
    ) -> IngestResult:
        if not url.startswith(("http://", "https://")):
            return IngestResult(doc_id="", chunks=0, ok=False, error="некорректная ссылка")
        doc_id = uuid.uuid4().hex
        self._docs.setdefault(user_id, []).append(
            UserDocument(doc_id=doc_id, filename=filename or url, chunks=3)
        )
        return IngestResult(doc_id=doc_id, chunks=3, ok=True, error=None)

    async def list_user_documents(self, user_id: int) -> list[UserDocument]:
        return list(reversed(self._docs.get(user_id, [])))  # свежие сверху

    async def delete_user_documents(
        self, user_id: int, doc_id: str | None = None
    ) -> None:
        if doc_id is None:
            self._docs.pop(user_id, None)
        else:
            self._docs[user_id] = [
                d for d in self._docs.get(user_id, []) if d.doc_id != doc_id
            ]
