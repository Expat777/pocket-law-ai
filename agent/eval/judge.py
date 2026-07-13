"""LLM-as-Judge: семантическая оценка ответа юр-бота по рубрике.

Зачем: регэксп-метрики (совпал ли номер статьи, есть ли слово-маркер) тонут в
шуме LLM и не ловят суть — «верно ли по праву», «не выдумана ли норма», «те ли
цитаты». Судья-LLM (temp=0, строгий промпт, JSON) даёт стабильный семантический
сигнал для A/B. Судья — оффлайн-инструмент оценки, НЕ рантайм-звено (в ответ
пользователю не влезает): лишняя латентность/стоимость и сам судья не безгрешен.

ВАЖНО: судью нужно ВАЛИДИРОВАТЬ (хороший ответ → высоко, плохой → низко) на
эталонах, прежде чем доверять его числам — см. agent/eval/run_judge.py.
"""

import json
import os

from agent.llm.base import LLMClient

# Критерии 0..2; total 0..8. verdict — грубая сводка. issues — что не так.
JUDGE_SYSTEM = """Ты — строгий эксперт по праву РФ, оцениваешь ответ юридического бота. Тебе дают ВОПРОС пользователя, ОТВЕТ бота и его ЦИТАТЫ («Основание»). Оцени СТРОГО и верни РОВНО один JSON-объект без пояснений вокруг:
{
  "grounded": 0-2,        // 2 — все правовые утверждения опираются на закон и ничего не выдумано; 1 — частично; 0 — есть выдуманные нормы/номера статей
  "correct": 0-2,         // 2 — юридически верно; 1 — с неточностями; 0 — неверно или вводит в заблуждение
  "citations_match": 0-2, // 2 — цитаты уместны и соответствуют сути ответа; 1 — частично; 0 — цитаты не те/мусорные/выдуманные
  "complete": 0-2,        // 2 — покрыты ключевые моменты вопроса; 1 — упущено второстепенное; 0 — упущено главное
  "verdict": "good|weak|bad",
  "issues": "одной строкой: что не так (пусто, если всё хорошо)"
}
Опирайся на право РФ. Если дан ЭТАЛОН приемлемых статей — используй как ориентир, но оценивай по существу, а не по буквальному совпадению номеров. Отвечай ТОЛЬКО JSON."""

_KEYS = ("grounded", "correct", "citations_match", "complete")


def build_judge_llm() -> LLMClient:
    """LLM-клиент для судьи: temp=0 (детерминизм), модель JUDGE_MODEL (иначе LLM_MODEL)."""
    from agent.llm.openai_compat import OpenAICompatLLM

    return OpenAICompatLLM(
        model=os.getenv("JUDGE_MODEL") or None, temperature=0.0, max_tokens=400
    )


def _parse(raw: str) -> dict:
    """Толерантный разбор JSON из ответа судьи (вырезаем первый {...})."""
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {}


def _norm(v) -> int:
    """Приводим оценку критерия к 0..2 (защита от дичи судьи)."""
    try:
        return max(0, min(2, int(v)))
    except (TypeError, ValueError):
        return 0


async def judge_answer(
    question: str,
    answer_text: str,
    citations: list | None = None,
    expected: str | None = None,
    *,
    llm: LLMClient | None = None,
) -> dict:
    """Оценивает один ответ. -> {grounded,correct,citations_match,complete,total,verdict,issues}.

    citations — список Citation (или строк «Акт ст.N»); expected — опц. эталон-ориентир.
    Сбой/непарсинг судьи -> total=None (не путать с настоящим нулём).
    """
    llm = llm or build_judge_llm()
    cites = ", ".join(
        c if isinstance(c, str) else f"{getattr(c, 'act', '')} ст.{getattr(c, 'article', '')}".strip()
        for c in (citations or [])
    ) or "(нет)"
    user = (
        f"ВОПРОС:\n{question}\n\n"
        f"ОТВЕТ БОТА:\n{answer_text}\n\n"
        f"ЦИТАТЫ (Основание): {cites}\n"
    )
    if expected:
        user += f"\nЭТАЛОН (ориентир приемлемых статей): {expected}\n"

    raw = await llm.complete(JUDGE_SYSTEM, user)
    parsed = _parse(raw)
    if not parsed:
        return {"total": None, "verdict": "parse_error", "issues": "судья вернул не-JSON", "raw": raw[:200]}

    scores = {k: _norm(parsed.get(k)) for k in _KEYS}
    scores["total"] = sum(scores.values())  # 0..8
    scores["verdict"] = parsed.get("verdict", "")
    scores["issues"] = parsed.get("issues", "")
    return scores


def aggregate(results: list[dict]) -> dict:
    """Сводка по набору оценок: средние по критериям + total, доля parse_error."""
    ok = [r for r in results if r.get("total") is not None]
    n = len(ok)
    if not n:
        return {"n": 0, "parse_errors": len(results)}
    agg = {k: round(sum(r[k] for r in ok) / n, 2) for k in _KEYS}
    agg["total"] = round(sum(r["total"] for r in ok) / n, 2)
    agg["n"] = n
    agg["parse_errors"] = len(results) - n
    return agg