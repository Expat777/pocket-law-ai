"""Прогон эталонных юркейсов через РЕАЛЬНОГО агента — таблица и Recall.

Показывает по каждому кейсу: ожидаемую статью, что реально попало в цитаты и
совпало ли. Для контрольных кейсов (вне права, пустой список статей) успех —
это отказ/уточнение без цитат.

Нужны рабочие Qdrant (наполненная law-коллекция) + LLM + .env. Запуск из корня:
    set -a; . ./.env; set +a
    PYTHONPATH=. python tests/legal_cases/run_eval.py           # все кейсы
    PYTHONPATH=. python tests/legal_cases/run_eval.py 10        # первые 10

ВНИМАНИЕ: каждый кейс = 2 вызова LLM (intent + compose). На 63 кейсах это ~126
вызовов — держите в уме бюджет.
"""

import asyncio
import json
import sys
from pathlib import Path

from agent.graph import answer_question

CASES_PATH = Path(__file__).with_name("cases.json")


def _articles(answer) -> set[str]:
    return {c.article for c in answer.citations}


async def main(limit: int | None = None) -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    if limit:
        cases = cases[:limit]

    hits = 0
    scored = 0
    control_ok = 0
    control_total = 0
    rows = []

    for c in cases:
        expected = set(c["expected"]["articles"])
        ans = await answer_question(1, c["question"])
        got = _articles(ans)

        if expected:  # юридический кейс
            scored += 1
            ok = bool(expected & got)
            hits += ok
            mark = "OK " if ok else "MISS"
        else:  # контрольный кейс вне права
            control_total += 1
            ok = ans.refused or bool(ans.clarifying_question) or not ans.citations
            control_ok += ok
            mark = "OK*" if ok else "BAD"

        rows.append(
            f"{mark}  {c['id'][:34]:34}  ждём: {','.join(sorted(expected)) or '(отказ)':14}  "
            f"получено: {','.join(sorted(got)) or '-'}"
        )

    print("\n".join(rows))
    print("-" * 70)
    if scored:
        print(f"Recall@цитаты (юр. кейсы): {hits}/{scored} = {hits / scored:.0%}")
    if control_total:
        print(f"Контроль (вне права, корректный отказ): {control_ok}/{control_total}")


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(main(_limit))