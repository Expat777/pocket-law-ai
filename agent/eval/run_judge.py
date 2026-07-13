"""Прогон LLM-судьи по eval-набору: агент отвечает -> судья оценивает -> сводка.

Использование (внутри контейнера с боевым LLM/Qdrant):
    python -m agent.eval.run_judge [путь_к_eval.json] [лимит_кейсов]
По умолчанию — tests/legal_cases/multicode_eval.json. Для A/B: прогнать один и тот
же набор до/после правки и сравнить средний total (семантика, не регэксп).
"""

import asyncio
import json
import sys

from agent.deps import build_default_deps
from agent.eval.judge import aggregate, build_judge_llm, judge_answer
from agent.graph import answer_question


async def run(path: str, limit: int | None = None) -> None:
    data = json.load(open(path, encoding="utf-8"))
    cases = data["cases"][:limit] if limit else data["cases"]
    deps = build_default_deps()
    judge = build_judge_llm()
    results = []
    for c in cases:
        ans = await answer_question(abs(hash(c["q"])) % 100000, c["q"], deps=deps)
        expected = None
        if c.get("articles"):
            expected = f"{'/'.join(c.get('acts', []))} ст. {', '.join(c['articles'])}"
        r = await judge_answer(c["q"], ans.text, ans.citations, expected=expected, llm=judge)
        results.append(r)
        print(f"[{r.get('total')}/8 {r.get('verdict', ''):5s}] {c['q'][:52]:52s} {str(r.get('issues', ''))[:55]}")
    print("\nСВОДКА:", aggregate(results))


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "tests/legal_cases/multicode_eval.json"
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
    asyncio.run(run(p, lim))