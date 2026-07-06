# bot/ — Bot Layer (Роль 1)

Telegram-бот на **aiogram 3.x**: принимает вопросы и файлы, зовёт агента через
контракт 3.1 (`shared.contracts`), форматирует ответ (MarkdownV2, цитата,
дисклеймер), ведёт FSM, согласие 152-ФЗ и rate-limit. Оркестратор пока — мок
(`mock_agent.py`); реальный `agent/` подключается в точке И1 без правок хендлеров.

## Запуск (long polling)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # общие зависимости из корневого pyproject.toml
export BOT_TOKEN=123456:ABC...   # токен от @BotFather (в проде — из .env Роли 4)
python -m bot.main
```

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
| `agent_client.py` | `Protocol` агента, который потребляет бот (модели — из `shared.contracts`) |
| `mock_agent.py` | фикстуры трёх веток (ответ+цитата / отказ / уточнение) |
| `formatter.py` | MarkdownV2, экранирование, формат 3.5 |
| `states.py` | FSM: normal / awaiting_clarification / uploading_file |
| `repository.py` | users, согласие, `dialog_history`, rate-limit (in-memory; Postgres — TODO) |
| `middlewares.py` | гейт согласия 152-ФЗ + rate-limit |
| `handlers/commands.py` | `/start` (согласие), `/help`, `/delete_my_data` |
| `handlers/content.py` | текстовые вопросы + файлы (валидация до обработки) |

## Границы (из TEAM_PLAN раздел 4)

Не трогаем `agent/`, схемы БД и docker-compose. Изменения у соседей — запросом
владельцу. Контракты (`shared/contracts.py`) меняются только PR с тегом всех четверых.

## Открытые долги

- **И1 (Роль 2):** в `main.build_dispatcher` заменить `MockAgent()` на реальный
  клиент из `agent/` (интерфейс `agent_client.AgentClient`).
- **PostgresRepository:** реализовать бэкенд на asyncpg поверх схемы 3.4
  (`users.consent_at`, `dialog_history`) и включить его через `STORAGE_BACKEND=postgres`.
  Сейчас по умолчанию — in-memory, данные не переживают рестарт.
