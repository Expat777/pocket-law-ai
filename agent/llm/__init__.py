"""LLM-слой Роли 2: протокол + фабрика реального клиента.

Боевой провайдер — любой OpenAI-совместимый шлюз (сейчас Polza.ai, см.
openai_compat.py): build_llm() поднимает его при заданном LLM_API_KEY, без ключа
возвращает ленивую заглушку. Граф зависит только от протокола LLMClient, конкретный
клиент внедряется извне (agent/deps.py -> Deps.llm), тесты — FakeLLMClient.
"""

import os

from .base import LLMClient
from .fake import FakeLLMClient


class _UnconfiguredLLM:
    """Заглушка боевого LLM, пока провайдер не подключён.

    Позволяет собрать граф и Agent без ключа/сети: ветки clarify/refuse и узлы
    retrieve/verify работают, а ошибка возникает только при реальной генерации
    (узел compose). Так И1 (подключение бота) не требует ждать LLM.
    """

    async def complete(self, system: str, user: str) -> str:
        raise NotImplementedError(
            "Боевой LLM-клиент ещё не подключён. Передайте конкретный LLMClient "
            "через Deps (FakeLLMClient для тестов) или добавьте провайдера в "
            "agent/llm/__init__.py после согласования зависимости с Ролью 4."
        )


def build_llm() -> LLMClient:
    """Фабрика боевого LLM-клиента.

    Если задан LLM_API_KEY — поднимаем OpenAI-совместимый клиент (по умолчанию
    Polza.ai, см. openai_compat.py). Иначе — ленивая заглушка (ошибка только при
    генерации), чтобы граф/Agent собирались без ключа.
    """
    if os.getenv("LLM_API_KEY"):
        from .openai_compat import OpenAICompatLLM

        return OpenAICompatLLM()
    return _UnconfiguredLLM()


__all__ = ["LLMClient", "FakeLLMClient", "build_llm"]