"""LLM-слой Роли 2: протокол + фабрика реального клиента.

Реальный провайдер намеренно ещё не подключён — граф работает через протокол
LLMClient, а конкретный клиент внедряется извне (agent/deps.py -> Deps.llm).
"""

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

    Пока провайдер (anthropic/openai) не добавлен в pyproject.toml — возвращаем
    ленивую заглушку (ошибка только при вызове). Когда Роль 4 добавит
    зависимость, здесь появится клиент, читающий LLM_API_KEY / LLM_MODEL
    (и HTTPS_PROXY при необходимости).
    """
    return _UnconfiguredLLM()


__all__ = ["LLMClient", "FakeLLMClient", "build_llm"]