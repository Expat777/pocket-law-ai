"""Мок агента на старте (задача-мок Роли 1).

Реализует контракт 3.1 (`answer_question` / `ingest_document`) фикстурами,
чтобы бот жил и демонстрировал все три ветки БЕЗ реального `agent/`:

  1) нормальный ответ с цитатой (ст. 81 ТК РФ),
  2) честный отказ (refused=True),
  3) уточняющий вопрос (clarifying_question).

Ветка выбирается по ключевым словам вопроса — этого достаточно для DoD Роли 1.
Заменяется на реальный `agent/` в точке И1 (см. bot/agent_client.py).
"""

from __future__ import annotations

import uuid
from datetime import date

from shared.contracts import Answer, Citation, IngestResult

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
    """Фикстурная реализация AgentClient. Никаких внешних вызовов."""

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
        self, user_id: int, file_bytes: bytes, mime: str
    ) -> IngestResult:
        if not file_bytes:
            return IngestResult(doc_id="", chunks=0, ok=False, error="пустой файл")

        # мок: «нарезал» ~1 фрагмент на каждые 2 КБ
        chunks = max(1, len(file_bytes) // 2048)
        return IngestResult(
            doc_id=uuid.uuid4().hex, chunks=chunks, ok=True, error=None
        )
