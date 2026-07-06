# bot/ — Bot Layer (Роль 1)

Telegram-бот на **aiogram 3.x**: принимает вопросы и файлы, зовёт агента через
контракт 3.1, форматирует ответ (MarkdownV2, цитата, дисклеймер), ведёт FSM,
согласие 152-ФЗ и rate-limit. Оркестратор пока — мок (`mock_agent.py`);
реальный `agent/` подключается в точке И1 без правок хендлеров.

## Запуск (long polling)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r bot/requirements.txt          # до И0; после — общий pyproject Роли 4
export BOT_TOKEN=123456:ABC...                # токен от @BotFather
python -m bot.main
```

Опциональные переменные: `RATE_LIMIT_PER_HOUR` (20), `MAX_FILE_BYTES` (20 МБ),
`STORAGE_BACKEND` (`memory` по умолчанию; `postgres` — после И0).

## Тесты (без Telegram и без сети)

```bash
PYTHONPATH=. .venv/bin/python -m pytest -c bot/pytest.ini bot/tests -q
```

## Структура

| Файл | Роль |
|---|---|
| `main.py` | точка входа: DI, middlewares, роутеры, polling |
| `config.py` | конфиг из окружения |
| `contracts.py` | **временное** зеркало раздела 3.1 (→ `shared/contracts.py` после И0) |
| `agent_client.py` | `Protocol` агента, который потребляет бот |
| `mock_agent.py` | фикстуры трёх веток (ответ+цитата / отказ / уточнение) |
| `formatter.py` | MarkdownV2, экранирование, формат 3.5 |
| `states.py` | FSM: normal / awaiting_clarification / uploading_file |
| `repository.py` | users, согласие, `dialog_history`, rate-limit (in-memory; Postgres после И0) |
| `middlewares.py` | гейт согласия 152-ФЗ + rate-limit |
| `handlers/commands.py` | `/start` (согласие), `/help`, `/delete_my_data` |
| `handlers/content.py` | текстовые вопросы + файлы (валидация до обработки) |

## Границы (из TEAM_PLAN раздел 4)

Не трогаем `agent/`, схемы БД и docker-compose. Изменения у соседей — запросом
владельцу. Контракты меняются только PR с тегом всех четверых.

## Долги к точкам интеграции

- **И0 (Роль 4):** заменить `bot/contracts.py` → `from shared.contracts import ...`;
  консолидировать зависимости в корневой `pyproject.toml`; подключить
  `PostgresRepository` (нужна колонка `users.consent_at` — **запрос к Роли 4**,
  в схеме 3.4 её нет).
- **И1 (Роль 2):** в `main.build_dispatcher` заменить `MockAgent()` на реальный
  клиент из `agent/` (интерфейс `agent_client.AgentClient`).
