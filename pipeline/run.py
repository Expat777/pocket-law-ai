"""CLI пайплайна: python -m pipeline.run --act tk_rf

Поток: fetch -> parse -> diff (версии) -> chunk -> embed -> upsert -> save state.
Пишет в песочницу law_articles_dev (переключение на боевую коллекцию — точка И2).

Ядро вынесено в update_act(): его же зовёт pipeline.watch (автообновление по расписанию).
CLI и флаги не менялись — команды Роли 4 работают как раньше.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import config, state
from .acts import ACTS, ActInfo
from .chunk import chunk_article
from .fetch import fetch_act
from .parse import parse_ips_html

log = logging.getLogger("pipeline")


def update_act(
    info: ActInfo,
    collection: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Полный прогон одного акта. Возвращает сводку (для watch/DAG).

    force=True — игнорировать state и перезалить все статьи (нужно, когда меняется
    не текст, а метаданные: так чинили ложный repealed — текст тот же, хэш тот же,
    обычный прогон payload бы не переписал).
    """
    collection = collection or config.QDRANT_COLLECTION
    fetched = fetch_act(info)
    articles = parse_ips_html(fetched.html, act=info.act, min_articles=info.min_articles)

    known = {} if force else state.load_hashes(info.code)
    changed = state.diff_changed(articles, known)
    chunks = [c for a in changed for c in chunk_article(a, fetched.revision_date, info.url)]
    log.info("chunk: %d чанков из %d статей", len(chunks), len(changed))

    summary = {
        "act": info.act,
        "code": info.code,
        "articles": len(articles),
        "changed": len(changed),
        "chunks": len(chunks),
        "revision_date": fetched.revision_date,
    }

    if dry_run:
        log.info("dry-run: эмбеддинги и upsert пропущены")
        return summary
    if not chunks:
        log.info("Изменений нет — база актуальна")
        # редакцию всё равно фиксируем: иначе watch будет дёргать акт каждую ночь
        state.save_redaction(info.code, fetched.rdk, fetched.revision_date)
        return summary

    from .embed import embed_passages, embedding_dim  # тяжёлый импорт — только когда реально нужен
    from .upsert import ensure_collection, upsert_chunks

    ensure_collection(embedding_dim(), collection)
    vectors = embed_passages([c.text for c in chunks])
    upsert_chunks(chunks, vectors, collection)

    state.record_versions_pg(config.POSTGRES_DSN, changed, fetched.revision_date)
    state.save_hashes(info.code, articles)
    state.save_redaction(info.code, fetched.rdk, fetched.revision_date)
    log.info("Готово: %s -> %s", info.act, collection)
    return summary


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
    update_act(ACTS[args.act], collection=args.collection, force=args.force, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
