"""CLI пайплайна: python -m pipeline.run --act tk_rf

Поток: fetch -> parse -> diff (версии) -> chunk -> embed -> upsert -> save state.
Пишет в песочницу law_articles_dev (переключение на боевую коллекцию — точка И2).
"""

import argparse
import logging
import sys

from . import config, state
from .acts import ACTS
from .chunk import chunk_article
from .fetch import fetch_act
from .parse import parse_ips_html

log = logging.getLogger("pipeline")


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка актов в Qdrant")
    parser.add_argument("--act", required=True, choices=sorted(ACTS), help="код акта из pipeline/acts.py")
    parser.add_argument("--collection", default=config.QDRANT_COLLECTION,
                        help=f"коллекция Qdrant (по умолчанию {config.QDRANT_COLLECTION})")
    parser.add_argument("--dry-run", action="store_true",
                        help="только fetch+parse+chunk, без эмбеддингов и Qdrant (быстрая проверка источника)")
    parser.add_argument("--force", action="store_true", help="игнорировать state, перезалить все статьи")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    info = ACTS[args.act]
    fetched = fetch_act(info)
    articles = parse_ips_html(fetched.html, act=info.act, min_articles=info.min_articles)

    known = {} if args.force else state.load_hashes(args.act)
    changed = state.diff_changed(articles, known)
    chunks = [c for a in changed for c in chunk_article(a, fetched.revision_date, info.url)]
    log.info("chunk: %d чанков из %d статей", len(chunks), len(changed))

    if args.dry_run:
        log.info("dry-run: эмбеддинги и upsert пропущены")
        return 0
    if not chunks:
        log.info("Изменений нет — база актуальна")
        return 0

    from .embed import embed_passages, embedding_dim  # тяжёлый импорт — только когда реально нужен
    from .upsert import ensure_collection, upsert_chunks

    ensure_collection(embedding_dim(), args.collection)
    vectors = embed_passages([c.text for c in chunks])
    upsert_chunks(chunks, vectors, args.collection)

    state.record_versions_pg(config.POSTGRES_DSN, changed, fetched.revision_date)
    state.save_hashes(args.act, articles)
    log.info("Готово: %s -> %s", info.act, args.collection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
