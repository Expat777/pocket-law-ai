"""Оффлайн-оценка качества ответов агента (Роль 2).

LLM-as-Judge: строгий эксперт-LLM оценивает ответ по рубрике (grounding /
корректность / соответствие цитат / полнота) — семантическая метрика вместо
хрупких регэкспов. Нужна для честного A/B (регэксп-метрики тонут в шуме).
"""

from .judge import JUDGE_SYSTEM, aggregate, build_judge_llm, judge_answer

__all__ = ["JUDGE_SYSTEM", "aggregate", "build_judge_llm", "judge_answer"]