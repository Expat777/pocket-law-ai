# STATUS — живой журнал команды

> Единственный источник правды о том, кто что сделал. Тезисно. Подробная история — в git-логе.
> Сжат 2026-07-08 по общему согласию (было 551 строка поэтапного лога).

## Правила
1. **Начало сессии:** `git pull origin main`, дать Claude прочитать этот файл.
2. **Конец блока:** правишь **только свою** секцию (владение из TEAM_PLAN). Коммит `status: роль N` — **можно сразу в main без PR** (журнал, секции не пересекаются). Пуш отбило → `git pull --rebase origin main`.

---

## 🟢 Текущее состояние системы (MVP собран)
- **Бот ЖИВОЙ в Telegram** (@pocket_law_ai_bot) в docker, реальный агент, egress через xray-прокси Роли 4, `STORAGE_BACKEND=postgres`. И0–И3 закрыты.
- **Данные:** ТК РФ, `law_articles_dev` = 623 чанка / 1024-мер (`deepvk/USER-bge-m3`), `source_url` в payload → кликабельные цитаты.
- **LLM:** Polza.ai, `google/gemini-2.5-flash-lite` (быстрая/дешёвая), абстрагирована (смена = `LLM_MODEL`), ретраи на 503.
- **Итоговая метрика к защите: сквозной Recall@цитаты 95% (59/62)**, anti-hallucination подтверждён.

### Открытые хвосты (не блокируют MVP)
- **Роль 4:** пересобрать образ бота (`docker compose build bot && up -d bot`) — забрать последние фиксы Роли 2 из `main` (PR #21 смержен). Branch protection на `main` (задача 10). Постоянное egress-решение вместо личного VPN.
- **Роль 1:** финальная проверка в живом Telegram после свежей пересборки.
- **Пользователь:** лимит трат на аккаунте Polza (только владелец ключа).
- **Фаза 2 (вне MVP):** LLM query expansion уже сделан; тезаурус/граф статей, другие кодексы, `law_versions`.

---

## Роль 1 · Bot Layer (`bot/`) — ветка `Dordzhi-Msk` · **DoD закрыт**
- aiogram 3.x (long polling): `/start` (обяз. согласие 152-ФЗ, без него бот молчит), `/help`, `/delete_my_data`. FSM + 3 ветки контракта (ответ с цитатой / уточнение / отказ).
- Приём **PDF/фото** (валидация по magic-bytes, ≤20 МБ) → `ingest_document`; **детект URL** → `ingest_url`; ссылка+вопрос в одном сообщении.
- Форматтер 3.5: MarkdownV2 с экранированием, «Основание: ст. N», дисклеймер, разбивка >4096, кликабельные `source_url`, мягкая деградация на плохой разметке.
- **`PostgresRepository`** (`STORAGE_BACKEND=postgres`): согласие/история/документы переживают рестарт (критично для 152-ФЗ); rate-limit поверх `dialog_history`; глобальный `@dp.errors`; edited_message; идемпотентное согласие.
- Бот подтверждён live в Telegram на реальном агенте. Правок под баг «документ не доходил до ответа» в `bot/` не потребовалось (баг был в агенте).

## Роль 2 · Agent Orchestrator (`agent/`) — ветка `Roman_SPT` · **функционально завершена**
- Граф LangGraph `intent → retrieve → verify → {compose | clarify | refuse}`, API 3.1 (`Agent()` — drop-in для бота).
- **LLM абстрагирован** (Polza.ai, httpx, без новых зависимостей); модель `gemini-2.5-flash-lite` (замер: 4.8с vs 12.7с deepseek); **ретраи на транзиентный 503/сеть** (до 3 попыток, 4xx — наружу).
- **Anti-hallucination:** цитаты только из `verify`; `INSUFFICIENT` → честный отказ; неюр. вопрос → уточнение. **Безопасность промптов** (инъекции через файл/URL, социнженерия «создатель/президент») — проверено на живом LLM, не течёт.
- `ingest_document` (PyMuPDF + OCR tesseract rus), `ingest_url` (**SSRF-защита**: http/https, блок приватных/loopback IP, лимит 20 МБ); изоляция `user_documents` по `user_id`; `source_url` → `Citation`.
- **Переформулировка «житейский → юридический»** перед ретривом (без доп. вызова LLM): живой R@5 **84→91%**, R@1 56→66%.
- Лимиты бюджета: `max_tokens=900`, `recursion_limit=8`, обрезка вопроса 4000, guard пустого ввода. `confidence_log` в Postgres (graceful).
- **Фикс (PR #21, смержен):** загруженный документ/URL не доходил до ответа — причины: `embed_passages` индексировал старой e5 (768) в коллекцию bge-m3 (1024) → upsert падал; `retrieve` срезал `user_doc`-чанки; мета-фраза «в этом документе» сбивала intent. Исправлено (embed из `shared.embeddings`, retrieve не режет документ, intent чистит мета-отсылку) — проверено вживую (PDF и реальный URL).
- **Полная сквозная проверка ✅** (все ветки графа, инъекции, изоляция, пустой ввод) + **итоговый Recall 95% (59/62)** на боевом стеке. 28 юнит-тестов зелёные.

## Роль 3 · Data Pipeline (`pipeline/`) — ветка `Roma_MSK` · **DoD закрыт**
- `fetch → parse → chunk → embed → upsert`, версионирование по hash (без дублей), CLI `python -m pipeline.run`. Источник — ИПС pravo.gov.ru (двухшаговый экспорт последней редакции). ТК РФ: 538 статей → 623 чанка.
- **Бенчмарк эмбеддингов → базовая модель `deepvk/USER-bge-m3`** (1024, без префикса): R@5 «книжный» **0.97**, «живой» **0.84** (лексический разрыв — люди не пишут юр-терминами). e5-base/large отмели по цифрам.
- **reranker (bge-reranker-v2-m3) и гибрид BM25+dense измерены — оба НЕ помогают** (reranker ронял ст. 81; гибрид MRR 0.89→0.70). Для MVP — чистый dense. Обоснованный негативный результат для защиты.
- `source_url` в payload (устойчивая ссылка на акт целиком; анкоров на статью у ИПС нет). Принцип юр-eval: метка = **множество** приемлемых статей.
- Рычаг на оставшийся зазор — **LLM query expansion** (зона Роли 2, реализован). Наборы `eval_extended.json` (156) / `eval_colloquial.json` (32) — в `pipeline/`.

## Роль 4 · Инфраструктура (`infra/`, `shared/`, корень) — ветка `Vitaliy_Svs`
- Скелет репо, `shared/contracts.py` (раздел 3 TEAM_PLAN 1-в-1), `docker-compose` (qdrant + postgres:16 + bot), миграции 3.4, `init_qdrant.py`, `Dockerfile` (tesseract-ocr-rus), `pyproject.toml` (pymupdf/pytesseract/pillow/aiohttp-socks). Фикс flat-layout сборки.
- `search_law()` (гибрид: `law_articles`/`_dev` + `user_documents` по `user_id`, `TOP_K_LAW=10`); `shared/embeddings.py` — префикс по модели (bge-m3 без префикса), `EMBED_DIM=1024`; `init_qdrant` пересоздаёт коллекцию при несовпадении размерности. `source_url` в `RetrievedChunk`/`search_law`.
- **Telegram-egress:** блок хостера (Selectel/РФ) обойдён контейнером `xray-proxy` (порты на `127.0.0.1` для всех dev-пользователей). ⚠️ Личная VPN-подписка, не командная инфра — нужно постоянное решение.
- **Докер-бот поднят и стабилен** (`STORAGE_BACKEND=postgres`, прокси, LLM-ключ в общем `.env`); реиндекс `--force` → `law_articles_dev` 623/1024 с `source_url`. И3 закрыта.
- Прод-`.env`: `LLM_API_KEY` + `LLM_BASE_URL=https://api.polza.ai/api/v1` + `LLM_MODEL` + `EMBED_MODEL=deepvk/USER-bge-m3`/`EMBED_DIM=1024` заданы. Секреты — только на сервере (не в git).