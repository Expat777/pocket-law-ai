"""Валидатор датасета эталонных юрвопросов (structure only, без LLM/Qdrant)."""

import json
from pathlib import Path

CASES_PATH = Path(__file__).with_name("cases.json")


def _load():
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def test_dataset_wellformed():
    data = _load()
    cases = data["cases"]

    # TEAM_PLAN требует 15–20 кейсов
    assert 15 <= len(cases) <= 100  # расширено eval-набором Роли 3

    ids = set()
    for c in cases:
        assert c["id"] and c["id"] not in ids, f"дубликат/пустой id: {c.get('id')}"
        ids.add(c["id"])
        assert c["question"].strip()
        assert "expected" in c and "articles" in c["expected"]
        assert isinstance(c["expected"]["articles"], list)


def test_has_dod_case_article_81():
    """DoD-кейс (увольнение в отпуске → ст. 81) должен присутствовать."""
    cases = _load()["cases"]
    dod = [c for c in cases if "81" in c["expected"]["articles"]]
    assert dod, "нет эталонного кейса с ожидаемой ст. 81 ТК РФ"


def test_has_out_of_scope_control_case():
    """Должен быть контрольный кейс вне права (пустой список статей)."""
    cases = _load()["cases"]
    control = [c for c in cases if not c["expected"]["articles"]]
    assert control, "нет контрольного кейса без ожидаемых статей"