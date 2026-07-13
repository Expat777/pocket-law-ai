"""Абстракция LLM (решение команды: провайдер выбирается позже).

Граф зависит только от протокола LLMClient, а не от конкретного SDK. Это
позволяет тестировать граф на FakeLLMClient без сети и без ключа, а реального
провайдера (Anthropic/OpenAI) подключить в одном месте — agent/llm/__init__.py.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self, system: str, user: str, *, temperature: float | None = None
    ) -> str:
        """Один вызов LLM: системная инструкция + сообщение пользователя -> текст.

        temperature — необязательный per-call оверрайд (температура по узлам:
        intent/HyDE детерминированные, compose — дефолт клиента). None = дефолт.
        """
        ...