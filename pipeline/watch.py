"""Автообновление НПА: проверить, не вышла ли новая редакция, и обновить только её.

    python -m pipeline.watch              # проверить все акты и обновить изменившиеся
    python -m pipeline.watch --check-only # только проверить (ничего не заливать)
    python -m pipeline.watch --acts tk_rf,uk_rf

ЗАЧЕМ ДВА ЯРУСА. `pipeline.run` качает документ ЦЕЛИКОМ (до 9 МБ у НК ч.2) и только потом,
по хэшам статей, понимает, что менять нечего. Гонять это по 57 актам каждую ночь —
часы впустую и гарантированный троттлинг ИПС. Но номер и дата последней редакции видны
на ЛЁГКОЙ карточке документа (`_latest_redaction`). Поэтому:

    ЯРУС 1 (дёшево, всегда):  57 карточек → сравнить редакцию с последней залитой
    ЯРУС 2 (дорого, редко):   полный pipeline.run — только для изменившихся актов

В обычную ночь это ~2-3 минуты и ноль эмбеддингов.

GUARD НА БУДУЩИЕ РЕДАКЦИИ. `_latest_redaction` берёт редакцию с МАКСИМАЛЬНОЙ датой. Если
ИПС выложит редакцию, которая ещё не вступила в силу, автомат зальёт недействующий текст —
и бот начнёт цитировать норму, которой пока нет. Такие редакции пропускаем.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

from .acts import ACTS, ActInfo
from .fetch import _latest_redaction
from .run import update_act
from .state import _redaction_marker, load_redactions

log = logging.getLogger("pipeline.watch")

CHECK_PAUSE_SEC = 2.0   # ИПС троттлит при частых запросах
RETRIES = 3


def check_act(info: ActInfo) -> tuple[str | None, str]:
    """Вернёт (маркер редакции, причина-если-пропускаем).

    ИПС на троттлинге отвечает FetchError («не нашёл список редакций») — это НЕ поломка
    источника, а сорванный ответ. fetch_act такие не ретраит by design (FetchError = «формат
    изменился, падай громко»), поэтому ретраим здесь, на уровне акта.
    """
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            rdk, rev_date = _latest_redaction(info.nd)
            if rev_date and rev_date > date.today():
                return None, f"редакция от {rev_date} ещё не вступила в силу — пропускаю"
            return _redaction_marker(rdk, rev_date), ""
        except Exception as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(5 * attempt)
    return None, f"проверка не удалась: {type(last_err).__name__}: {last_err}"


def seed(codes: list[str]) -> dict:
    """Записать ТЕКУЩИЕ редакции как базовую линию, ничего не заливая.

    Нужен ровно один раз — сразу после того, как база залита и актуальна. Иначе первый
    же ночной прогон на чистом state сочтёт ВСЕ 57 актов изменившимися и устроит полный
    ре-индекс (часы эмбеддингов впустую).

    ⚠️ Звать только когда база ТОЧНО соответствует источнику. Если сомневаешься —
    сначала `--check-only` и обычный прогон изменившихся, и лишь потом seed.
    """
    from .state import save_raw_redaction

    marked, failed = [], []
    for code in codes:
        info = ACTS[code]
        marker, reason = check_act(info)  # один запрос к ИПС на акт, не два
        if marker is None:
            failed.append((code, reason))
            log.warning("%s: %s", code, reason)
        else:
            save_raw_redaction(code, marker)
            marked.append(code)
            log.info("%s: базовая линия = %s", code, marker)
        time.sleep(CHECK_PAUSE_SEC)
    return {"seeded": marked, "failed": failed}


def watch(codes: list[str], check_only: bool = False, collection: str | None = None) -> dict:
    known = load_redactions()
    changed: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    fresh = 0

    log.info("Проверяю редакции: %d актов", len(codes))
    for code in codes:
        info = ACTS[code]
        marker, reason = check_act(info)
        if marker is None:
            (skipped if "не вступила" in reason else failed).append((code, reason))
            log.warning("%s: %s", code, reason)
        elif known.get(code) != marker:
            was = known.get(code, "—")
            log.info("%s: НОВАЯ РЕДАКЦИЯ %s (было %s)", code, marker, was)
            changed.append(code)
        else:
            fresh += 1
        time.sleep(CHECK_PAUSE_SEC)

    log.info("Итог проверки: актуальны %d, изменились %d, пропущены %d, ошибки %d",
             fresh, len(changed), len(skipped), len(failed))

    updated: list[dict] = []
    if changed and not check_only:
        for code in changed:
            log.info("Обновляю %s …", code)
            try:
                updated.append(update_act(ACTS[code], collection=collection))
            except Exception as e:
                failed.append((code, f"обновление не удалось: {type(e).__name__}: {e}"))
                log.error("%s: обновление не удалось: %s", code, e)

    return {
        "checked": len(codes), "fresh": fresh, "changed": changed,
        "updated": updated, "skipped": skipped, "failed": failed,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Проверить новые редакции НПА и обновить изменившиеся")
    p.add_argument("--acts", help="список кодов через запятую (по умолчанию — все)")
    p.add_argument("--check-only", action="store_true", help="только проверить, не заливать")
    p.add_argument("--seed", action="store_true",
                   help="записать текущие редакции как базовую линию (один раз, когда база уже актуальна)")
    p.add_argument("--collection", default=None)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    codes = [c.strip() for c in args.acts.split(",")] if args.acts else sorted(ACTS)
    unknown = [c for c in codes if c not in ACTS]
    if unknown:
        p.error(f"неизвестные коды актов: {unknown}")

    if args.seed:
        s = seed(codes)
        print(f"\n=== БАЗОВАЯ ЛИНИЯ ===\nзаписано: {len(s['seeded'])} актов")
        for code, why in s["failed"]:
            print(f"  ❌ {code}: {why}")
        return 1 if s["failed"] else 0

    r = watch(codes, check_only=args.check_only, collection=args.collection)

    print("\n=== АВТООБНОВЛЕНИЕ НПА ===")
    print(f"проверено: {r['checked']} | актуальны: {r['fresh']} | изменились: {len(r['changed'])}")
    for u in r["updated"]:
        print(f"  ✅ {u['act']}: {u['changed']} статей обновлено ({u['chunks']} чанков), ред. {u['revision_date']}")
    for code, why in r["skipped"]:
        print(f"  ⏭  {code}: {why}")
    for code, why in r["failed"]:
        print(f"  ❌ {code}: {why}")

    # ненулевой код = алерт для Airflow/cron. Пропуск будущей редакции — не ошибка.
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
