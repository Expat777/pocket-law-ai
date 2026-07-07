# pipeline/ — Роль 3 · Data Pipeline

Настоящие тексты законов автоматически попадают в Qdrant с метаданными.
Источник и его проверка — в [SOURCE.md](SOURCE.md).

## Запуск

```bash
pip install -r pipeline/requirements.txt

# быстрая проверка источника и парсера, без Qdrant и эмбеддингов (~5 сек):
python -m pipeline.run --act tk_rf --dry-run

# полная загрузка ТК РФ в песочницу law_articles_dev
# (нужен Qdrant: docker compose Роли 4 или `docker run -p 6333:6333 qdrant/qdrant`):
python -m pipeline.run --act tk_rf
```

Первый полный запуск скачает веса модели эмбеддингов (~1 ГБ) и посчитает векторы
на CPU (несколько минут). Повторный прогон обновляет **только изменившиеся статьи**
(hash-состояние в `pipeline/.state/`, не в git) и не плодит дубликатов
(детерминированные id точек).

## Переменные окружения (все со значениями по умолчанию)

| Переменная | Default | Что это |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | адрес Qdrant |
| `PIPELINE_COLLECTION` | `law_articles_dev` | песочница; боевая `law_articles` — только в точке И2 |
| `EMBED_MODEL` | `intfloat/multilingual-e5-base` | локальная модель эмбеддингов |
| `POSTGRES_DSN` | пусто | если задан — версии статей дублируются в `law_versions` |

## Для Роли 2 и Роли 4 (кто пишет search_law) — ВАЖНО

Модель **e5** требует префиксы: документы уже закодированы как `passage: <текст>`,
поэтому запросы надо кодировать как **`query: <вопрос>`** и с
`normalize_embeddings=True` — иначе качество поиска заметно упадёт.

Payload точек — строго по контракту TEAM_PLAN 3.3:
`act, article_no, chapter, status, effective_date, text`
(`effective_date` — ISO-дата последней редакции документа, `status` ∈ `active|repealed` —
подробности и ограничения в SOURCE.md).
