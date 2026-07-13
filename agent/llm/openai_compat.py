"""LLMClient поверх OpenAI-совместимого API (Polza.ai и любой другой такой шлюз).

Провайдер задаётся окружением — граф от него не зависит (решение команды об
абстракции LLM). httpx уже в зависимостях (тянет qdrant-client), поэтому новый
пакет в pyproject не нужен.

ENV:
  LLM_API_KEY    — ключ (Bearer). Если пусто — build_llm() вернёт заглушку.
  LLM_BASE_URL   — базовый URL, по умолчанию https://api.polza.ai/api/v1
  LLM_MODEL      — модель в формате provider/model, напр. anthropic/claude-sonnet-5
  LLM_MAX_TOKENS — жёсткий потолок длины ответа (защита бюджета), по умолчанию 900
"""

import asyncio
import os

DEFAULT_BASE_URL = "https://api.polza.ai/api/v1"
# Транзиентные ошибки апстрима (Polza периодически отдаёт 503) — ретраим.
# 4xx (400/401/403 — наш payload/ключ) НЕ ретраим: летят наружу сразу.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3  # бюджет-безопасно: 503/таймаут = токены не потрачены
_BACKOFF = (0.6, 1.5)  # сек между попытками (длина = _MAX_ATTEMPTS - 1)
# Быстрая дешёвая модель (Flash-Lite): ~4.8с/ответ, вход 10₽/1M на Polza: для grounded-ответа по переданным статьям её
# хватает, держит INSUFFICIENT и защиту от инъекций (проверено на сервере).
# Меняется LLM_MODEL без правок кода.
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
# Потолок токенов на ответ. Юр. ответ 2–5 предложений укладывается с запасом;
# защищает от «раздутого» ответа, который бил бы по бюджету. Меняется LLM_MAX_TOKENS.
DEFAULT_MAX_TOKENS = 900


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        temperature: float | None = None,  # None -> LLM_TEMPERATURE (по умолч. 0.2)
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        # Низкая температура: юр. ответы, меньше галлюцинаций/вариативности. Настраиваемо
        # env (LLM_TEMPERATURE), чтобы A/B-ить стабильность композиции судьёй. Явный
        # аргумент (напр. судья temperature=0.0) имеет приоритет над env.
        self.temperature = (
            temperature if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", "0.2"))
        )
        self.max_tokens = max_tokens or int(
            os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        )

    async def complete(self, system: str, user: str) -> str:
        import httpx  # ленивый импорт: нужен только при реальной генерации

        from agent.tracing import llm_span

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,  # потолок стоимости ответа
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        # отдельный LLM-спан в трейсе: в inputs только messages (без self/ключа)
        with llm_span(self.model, payload["messages"]) as record:
            last_exc: Exception | None = None
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    # content может прийти null (фильтр/пустой ответ провайдера) —
                    # отдаём "", а не None: выше по стеку зовут .strip() (аудит зоны).
                    out = data["choices"][0]["message"]["content"] or ""
                    record(out)
                    return out
                except httpx.HTTPStatusError as e:
                    # только транзиентные статусы ретраим; прочие 4xx — сразу наружу
                    if e.response.status_code not in _TRANSIENT_STATUS:
                        raise
                    last_exc = e
                except httpx.TransportError as e:  # connect/read timeout, обрыв сети
                    last_exc = e
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(_BACKOFF[attempt])
            assert last_exc is not None  # цикл вышел только после исключения
            raise last_exc