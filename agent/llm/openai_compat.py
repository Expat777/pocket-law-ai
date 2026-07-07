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

import os

DEFAULT_BASE_URL = "https://api.polza.ai/api/v1"
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
        temperature: float = 0.2,  # низкая: юр. ответы, меньше галлюцинаций
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens or int(
            os.getenv("LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        )

    async def complete(self, system: str, user: str) -> str:
        import httpx  # ленивый импорт: нужен только при реальной генерации

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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]