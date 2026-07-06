"""LLMClient поверх OpenAI-совместимого API (Polza.ai и любой другой такой шлюз).

Провайдер задаётся окружением — граф от него не зависит (решение команды об
абстракции LLM). httpx уже в зависимостях (тянет qdrant-client), поэтому новый
пакет в pyproject не нужен.

ENV:
  LLM_API_KEY   — ключ (Bearer). Если пусто — build_llm() вернёт заглушку.
  LLM_BASE_URL  — базовый URL, по умолчанию https://api.polza.ai/api/v1
  LLM_MODEL     — модель в формате provider/model, напр. anthropic/claude-3.7-sonnet
"""

import os

DEFAULT_BASE_URL = "https://api.polza.ai/api/v1"
# Актуальная модель в каталоге Polza (проверено GET /models). Меняется через LLM_MODEL.
DEFAULT_MODEL = "anthropic/claude-sonnet-5"


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        temperature: float = 0.2,  # низкая: юр. ответы, меньше галлюцинаций
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.temperature = temperature

    async def complete(self, system: str, user: str) -> str:
        import httpx  # ленивый импорт: нужен только при реальной генерации

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]