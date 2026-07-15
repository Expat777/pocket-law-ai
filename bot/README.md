# bot/ — Bot Layer (Роль 1)

Telegram-бот на **aiogram 3.x**: принимает вопросы и файлы, зовёт агента через
контракт 3.1 (`shared.contracts`), форматирует ответ (MarkdownV2, цитата,
дисклеймер), ведёт FSM, согласие 152-ФЗ и rate-limit. С точки И1 подключён
реальный оркестратор Роли 2 — `agent.Agent()` в `main.py` (без правок хендлеров).

## Запуск (long polling)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                          # общие зависимости из pyproject
export BOT_TOKEN=123456:ABC...                   # токен от @BotFather (в проде — из .env)
export LLM_BASE_URL=https://api.polza.ai/api/v1
export LLM_MODEL=google/gemini-2.5-flash-lite
export LLM_API_KEY=...                            # ключ Polza.ai
python -m bot.main
```

Реальный агент требует доступного **Qdrant** (наполненного `law_articles_dev`) и
**LLM-ключа** — на сервере они есть. `pymupdf`/`pytesseract`/`pillow` уже в
`pyproject`; для OCR фото/сканов на хосте нужен системный `tesseract-ocr` (с
`rus`+`eng`). Голосовой ввод дополнительных пакетов на стороне бота не требует —
STT выполняет агент (`transcribe_voice`), бот лишь скачивает OGG.

Опциональные переменные: `RATE_LIMIT_PER_HOUR` (20), `MAX_FILE_BYTES` (20 МБ),
`STORAGE_BACKEND` (`memory` по умолчанию; `postgres` — после подключения
`PostgresRepository`).

## Тесты (без Telegram и без сети)

```bash
python -m pytest bot/tests -q     # asyncio_mode=auto берётся из корневого pyproject
```

## Структура

| Файл | Роль |
|---|---|
| `main.py` | точка входа: DI, middlewares, роутеры, polling |
| `config.py` | конфиг из окружения |
| `agent_client.py` | `Protocol` агента (6 методов), который потребляет бот (модели — из `shared.contracts`) |
| `mock_agent.py` | фикстуры веток: ответ+цитата / отказ / уточнение / STT (`transcribe_voice`) |
| `formatter.py` | MarkdownV2, экранирование, формат 3.5 + дословная выдержка `Citation.text` |
| `states.py` | FSM: normal / awaiting_clarification / uploading_file |
| `repository.py` | users, согласие, `dialog_history`, rate-limit (in-memory; Postgres — TODO) |
| `middlewares.py` | гейт согласия 152-ФЗ + rate-limit |
| `handlers/commands.py` | `/start` (согласие), `/help`, `/delete` |
| `handlers/content.py` | текст + файлы/фото (`F.document \| F.photo` → `ingest_document`) + ссылки (`ingest_url`) + голос (`F.voice` → `transcribe_voice`); контекст уточнения переносится в переспрос |

## Границы (из TEAM_PLAN раздел 4)

Не трогаем `agent/`, схемы БД и docker-compose. Изменения у соседей — запросом
владельцу. Контракты (`shared/contracts.py`) меняются только PR с тегом всех четверых.

## Открытые долги

- **И1 — выполнено:** `bot/main.build_dispatcher` использует `agent.Agent()`
  (интерфейс `agent_client.AgentClient`). Осталась live-проверка сквозняка через
  Telegram на сервере (полный стек + LLM-ключ).
- **PostgresRepository — готов:** бэкенд на asyncpg поверх схемы 3.4
  (`users.consent_at`, `dialog_history`; rate-limit — счётчик поверх `dialog_history`).
  Включается `STORAGE_BACKEND=postgres` (+ `POSTGRES_*` в `.env`); тогда согласие,
  история и лимиты переживают рестарт контейнера. Дефолт — in-memory (для тестов).
