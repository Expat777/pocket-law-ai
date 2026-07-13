"""Airflow DAG: ежедневная проверка новых редакций НПА и обновление изменившихся.

    check_redactions  → (fan-out) update_act[код] → report
    ЯРУС 1: дёшево         ЯРУС 2: дорого, только по факту изменения

Почему fan-out (dynamic task mapping), а не один таск на всё: ИПС нестабилен — рвёт
соединение и отдаёт 502 на частых запросах. При fan-out падение ОДНОГО акта ретраится
и не роняет остальные; в UI видно, какой именно закон не обновился.

Вся логика — в `pipeline.watch` (обычный CLI). DAG её только оркеструет, поэтому то же
самое работает и без Airflow:
    0 4 * * *  cd /app && python -m pipeline.watch >> /var/log/law_watch.log 2>&1

РАЗВЁРТЫВАНИЕ (Роль 4): контейнеру Airflow нужен доступ к коду репозитория (`pipeline/`),
к Qdrant и к тем же переменным окружения, что у бота (QDRANT_URL, EMBED_MODEL, POSTGRES_DSN).
Эмбеддинги считает bge-m3 на CPU — воркеру нужна память, поэтому обновление идёт
последовательно (max_active_tasks=1), а не веером по всем актам разом.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task

DEFAULT_ARGS = {
    "owner": "role3-pipeline",
    "retries": 3,
    "retry_delay": pendulum.duration(minutes=5),  # ИПС троттлит — пауза перед повтором
    "retry_exponential_backoff": True,
}


@dag(
    dag_id="law_update",
    description="Проверка новых редакций НПА в ИПС и инкрементальное обновление Qdrant",
    schedule="0 4 * * *",                                  # 04:00 — минимум нагрузки на бота
    start_date=pendulum.datetime(2026, 7, 1, tz="Europe/Moscow"),
    catchup=False,                                         # пропущенные дни не догоняем: нужна ТЕКУЩАЯ редакция
    max_active_runs=1,                                     # два прогона разом подрались бы за state и Qdrant
    max_active_tasks=1,                                    # эмбеддинги bge-m3 на CPU — не параллелим
    default_args=DEFAULT_ARGS,
    tags=["pipeline", "npa", "role3"],
)
def law_update():

    @task
    def check_redactions() -> list[str]:
        """ЯРУС 1: лёгкие карточки документов. Возвращает коды актов с новой редакцией."""
        from pipeline.acts import ACTS
        from pipeline.watch import watch

        r = watch(sorted(ACTS), check_only=True)
        if r["failed"]:
            # не роняем DAG из-за одного недоступного акта — но и не молчим
            print(f"⚠️ не удалось проверить: {r['failed']}")
        print(f"актуальны: {r['fresh']} | новые редакции: {r['changed']}")
        return r["changed"]

    @task
    def update_one(code: str) -> dict:
        """ЯРУС 2: полный fetch→parse→diff→embed→upsert одного акта."""
        from pipeline.acts import ACTS
        from pipeline.run import update_act

        s = update_act(ACTS[code])
        print(f"{s['act']}: обновлено {s['changed']} статей → {s['chunks']} чанков, ред. {s['revision_date']}")
        return s

    @task(trigger_rule="all_done")   # отчёт нужен, даже если часть актов упала
    def report(results: list[dict]) -> None:
        if not results:
            print("Новых редакций нет — база актуальна.")
            return
        total = sum(r["chunks"] for r in results)
        for r in results:
            print(f"✅ {r['act']}: {r['changed']} статей / {r['chunks']} чанков, ред. {r['revision_date']}")
        print(f"ИТОГО обновлено чанков: {total}")

    report(update_one.expand(code=check_redactions()))


law_update()
