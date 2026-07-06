"""LLM-слой Роли 2: протокол + фабрика реального клиента.

Реальный провайдер намеренно ещё не подключён — граф работает через протокол
LLMClient, а конкретный клиент внедряется извне (agent/deps.py -> Deps.llm).
"""

from .base import LLMClient
from .fake import FakeLLMClient


def build_llm() -> LLMClient:
    """Фабрика боевого LLM-клиента.

    Пока провайдер (anthropic/openai) не добавлен в pyproject.toml — поднимаем
    явную ошибку. Для тестов и локальных прогонов передавайте FakeLLMClient
    через Deps. Когда Роль 4 добавит зависимость, здесь появится клиент,
    читающий LLM_API_KEY / LLM_MODEL (и HTTPS_PROXY при необходимости).
    """
    raise NotImplementedError(
        "Боевой LLM-клиент ещё не подключён. Передайте конкретный LLMClient "
        "через Deps (FakeLLMClient для тестов) или добавьте провайдера в "
        "agent/llm/__init__.py после согласования зависимости с Ролью 4."
    )


__all__ = ["LLMClient", "FakeLLMClient", "build_llm"]