# pocket-law-ai

RAG-агент по законам РФ: Telegram-бот, отвечающий на юридические вопросы строго по законам, с обязательной цитатой статьи-источника.

Полное описание архитектуры, ролей и контрактов — в [TEAM_PLAN.md](TEAM_PLAN.md). Правила работы с репозиторием — в [CLAUDE.md](CLAUDE.md).

## Структура репозитория

```
bot/                  # aiogram: handlers, FSM, форматирование (Роль 1)
agent/                # LangGraph: граф, инструменты, промпты (Роль 2)
pipeline/             # fetch/parse/chunk/embed/upsert законов (Роль 3)
infra/                # docker-compose, миграции, скрипты (Роль 4)
  migrations/          # SQL-миграции Postgres
  init_qdrant.py       # создание коллекций Qdrant
shared/               # общие контракты (Роль 4)
  contracts.py         # Pydantic-модели и сигнатуры между зонами
tests/legal_cases/    # эталонные юрвопросы для ручной сверки (Роль 2)
```

## Запуск

Требуется Python 3.11+, Docker и Docker Compose.

```bash
cp .env.example .env      # заполнить BOT_TOKEN, LLM_API_KEY и т.д.
pip install -e ".[dev]"
make up                   # поднять qdrant + postgres + bot
make migrate               # применить миграции Postgres и создать коллекции Qdrant
make fixtures               # загрузить тестовые статьи законов (Роль 2)
make test
```

## Стек

aiogram 3.x · LangGraph · Qdrant · PostgreSQL · облачный LLM API (генерация) · локальные эмбеддинги (sentence-transformers). Инструменты агента — обычные функции, без MCP.
