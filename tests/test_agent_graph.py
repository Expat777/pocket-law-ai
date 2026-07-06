"""Юнит-тесты графа Роли 2 на фейках (без сети, Qdrant и реального LLM).

Три сценария из Definition of Done: ответ с цитатой, уточнение, отказ.
Запуск: из корня репозитория `python -m pytest tests/test_agent_graph.py`.
"""

import json
from datetime import date

import pytest

from agent.deps import Deps
from agent.graph import answer_question
from agent.llm.fake import FakeLLMClient
from shared.contracts import CitationStatus, RetrievedChunk

TK_81 = RetrievedChunk(
    text="Расторжение трудового договора по инициативе работодателя...",
    source="law",
    act="ТК РФ",
    article="81",
    status="active",
    effective_date=date(2026, 5, 15),
    score=0.88,
)


def make_llm(is_legal: bool = True, answer_text: str = "Ответ по статье.") -> FakeLLMClient:
    """FakeLLM: на intent-промпт отдаёт JSON, на compose — текст ответа."""

    def handler(system: str, user: str) -> str:
        if "классификатор" in system:
            return json.dumps(
                {"is_legal": is_legal, "branch": "трудовое", "normalized": user}
            )
        return answer_text

    return FakeLLMClient(handler)


def make_deps(chunks, is_legal=True, answer_text="Ответ по статье.", active=True) -> Deps:
    async def fake_search(query, user_id):
        return list(chunks)

    async def fake_verify(citation):
        return CitationStatus(exists=True, active=active, current_revision=date(2026, 5, 15))

    return Deps(
        llm=make_llm(is_legal=is_legal, answer_text=answer_text),
        search_law=fake_search,
        verify_citation=fake_verify,
    )


async def test_answer_with_citation():
    """Юр. вопрос со ст. 81 в выдаче -> Answer с реальной цитатой, без отказа."""
    deps = make_deps([TK_81], answer_text="Уволить в отпуске нельзя (ст. 81 ТК РФ).")
    ans = await answer_question(1, "могут ли уволить в отпуске?", deps=deps)

    assert ans.refused is False
    assert ans.clarifying_question is None
    assert len(ans.citations) >= 1
    cite = ans.citations[0]
    assert cite.act == "ТК РФ" and cite.article == "81"
    assert ans.text


async def test_refuse_when_no_law_found():
    """Юр. вопрос, но в базе ничего -> честный отказ (refused=True)."""
    deps = make_deps([], is_legal=True)
    ans = await answer_question(1, "вопрос без совпадений в базе", deps=deps)

    assert ans.refused is True
    assert ans.citations == []


async def test_clarify_when_not_legal():
    """Вопрос вне права / бессмысленный -> уточняющий вопрос, не отказ."""
    deps = make_deps([], is_legal=False)
    ans = await answer_question(1, "asdf погода завтра", deps=deps)

    assert ans.refused is False
    assert ans.clarifying_question is not None
    assert ans.citations == []


def test_compose_prompt_has_security_block():
    """Канарейка: правила безопасности не должны исчезнуть из compose-промпта."""
    from agent.prompts import COMPOSE_SYSTEM

    lowered = COMPOSE_SYSTEM.lower()
    assert "безопасност" in lowered
    assert "системный промпт" in lowered
    assert "данные, а не команды" in lowered
    # социнженерия «я создатель/президент» должна явно отвергаться
    assert "президент" in lowered


async def test_unverified_citation_dropped():
    """Если verify говорит, что статьи нет -> она не попадает в цитаты, отказ."""
    deps = make_deps([TK_81], is_legal=True, active=False)
    ans = await answer_question(1, "могут ли уволить в отпуске?", deps=deps)

    assert ans.refused is True
    assert ans.citations == []