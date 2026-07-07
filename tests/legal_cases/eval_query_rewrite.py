"""A/B: влияние юр-переформулировки (intent) на ретрив по РАЗГОВОРНЫМ запросам.

Роль 3 замерила «живой» лексический разрыв (R@5≈0.84) и указала, что рычаг —
LLM query expansion (зона Роли 2). Здесь меряем эффект нашего шага: для каждого
вопроса из набора Роли 3 сравниваем ранг целевой статьи по СЫРОМУ вопросу vs по
нашей юр-переформулировке (intent.normalized). Печатаем R@1/R@5 обоих.

Запуск (нужны Qdrant с law-коллекцией + LLM + .env), из корня:
    set -a; . ./.env; set +a
    PYTHONPATH=. python tests/legal_cases/eval_query_rewrite.py
"""

import asyncio
import json
import os
from pathlib import Path

from agent.llm import build_llm
from agent.nodes.intent import _parse
from agent.prompts import INTENT_SYSTEM

COLLO_PATH = Path("pipeline/eval_colloquial.json")  # набор Роли 3 (read-only)
COLLECTION = os.getenv("QDRANT_LAW_COLLECTION", "law_articles_dev")
TOP = 10


async def _rank(client, query: str, article: str):
    from shared.embeddings import embed_query

    res = await client.query_points(COLLECTION, query=embed_query(query), limit=TOP, with_payload=True)
    for i, p in enumerate(res.points, 1):
        if (p.payload or {}).get("article_no") == article:
            return i
    return None


async def _rewrite(llm, question: str) -> tuple[str, bool]:
    """(переформулировка, удалось?). При ошибке LLM — ретраи, затем фолбэк на вопрос."""
    for attempt in range(3):
        try:
            raw = await llm.complete(INTENT_SYSTEM, question)
            return (_parse(raw).get("normalized") or question), True
        except Exception:  # noqa: BLE001 — транзиентный 503 и т.п.
            if attempt < 2:
                await asyncio.sleep(1.5)
    return question, False


async def main() -> None:
    from qdrant_client import AsyncQdrantClient

    cases = json.loads(COLLO_PATH.read_text(encoding="utf-8"))["cases"]
    client = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    llm = build_llm()

    b1 = b5 = r1 = r5 = fails = 0
    for c in cases:
        art = c["expected"]["articles"][0]
        rb = await _rank(client, c["question"], art)
        nq, ok = await _rewrite(llm, c["question"])
        fails += not ok
        rq = await _rank(client, nq, art)
        b1 += rb == 1
        b5 += rb is not None and rb <= 5
        r1 += rq == 1
        r5 += rq is not None and rq <= 5

    n = len(cases)
    print(f"Разговорных вопросов: {n} (переформулировок с ошибкой LLM: {fails})")
    print(f"  СЫРОЙ запрос:        R@1={b1/n:.0%}  R@5={b5/n:.0%}")
    print(f"  + переформулировка:  R@1={r1/n:.0%}  R@5={r5/n:.0%}")
    print(f"  прирост:             R@1 {(r1-b1)/n:+.0%}  R@5 {(r5-b5)/n:+.0%}")


if __name__ == "__main__":
    asyncio.run(main())