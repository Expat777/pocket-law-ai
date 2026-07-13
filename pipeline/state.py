"""Версионирование: hash текста статьи -> повторный прогон обновляет только изменившееся.

Локальный state-файл pipeline/.state/{act}.json — источник истины для инкрементальности
(работает без Postgres). Если задан POSTGRES_DSN — версии дополнительно пишутся в
law_versions (схема TEAM_PLAN 3.4, владелец схемы — Роль 4), best-effort.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from .parse import Article

log = logging.getLogger(__name__)

_STATE_DIR = Path(__file__).parent / ".state"


def load_hashes(act_code: str) -> dict[str, str]:
    path = _STATE_DIR / f"{act_code}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_hashes(act_code: str, articles: list[Article]) -> None:
    _STATE_DIR.mkdir(exist_ok=True)
    path = _STATE_DIR / f"{act_code}.json"
    path.write_text(json.dumps({a.article_no: a.text_hash for a in articles}, ensure_ascii=False, indent=0))


def diff_changed(articles: list[Article], known: dict[str, str]) -> list[Article]:
    changed = [a for a in articles if known.get(a.article_no) != a.text_hash]
    log.info("Версионирование: %d изменившихся/новых статей из %d", len(changed), len(articles))
    return changed


# --- редакции: дешёвый ярус автообновления (pipeline.watch) -------------------
# Хэши статей (выше) требуют СКАЧАТЬ и распарсить документ целиком (до 9 МБ у НК ч.2).
# Для ночной проверки «а не вышло ли чего» это расточительно: ИПС отдаёт номер и дату
# последней редакции с лёгкой карточки документа. Храним увиденную редакцию — если она
# не изменилась, документ не качаем вообще.

_RED_FILE = _STATE_DIR / "redactions.json"


def _redaction_marker(rdk: int, revision_date: date | None) -> str:
    return f"{rdk}:{revision_date.isoformat() if revision_date else '?'}"


def load_redactions() -> dict[str, str]:
    """{act_code: "rdk:YYYY-MM-DD"} последних залитых редакций."""
    if _RED_FILE.exists():
        return json.loads(_RED_FILE.read_text())
    return {}


def save_raw_redaction(act_code: str, marker: str) -> None:
    _STATE_DIR.mkdir(exist_ok=True)
    data = load_redactions()
    data[act_code] = marker
    _RED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True))


def save_redaction(act_code: str, rdk: int, revision_date: date | None) -> None:
    save_raw_redaction(act_code, _redaction_marker(rdk, revision_date))


def record_versions_pg(dsn: str, changed: list[Article], revision_date: date | None) -> None:
    """Best-effort запись в law_versions; отсутствие таблицы/БД не валит пайплайн."""
    if not dsn or not changed:
        return
    try:
        import psycopg
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO law_versions (act, article_no, revision_date, hash, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(a.act, a.article_no, revision_date or date.today(), a.text_hash, a.status) for a in changed],
            )
        log.info("law_versions: записано %d версий", len(changed))
    except Exception as e:
        log.warning("law_versions недоступна (%s) — пропускаю, инкрементальность работает через .state", e)
