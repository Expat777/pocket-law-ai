"""Детерминированный LLM для тестов и локальной разработки без сети/ключа."""

from collections.abc import Callable


class FakeLLMClient:
    """Замена LLMClient без сети.

    handler(system, user) -> str задаёт ответ; если не задан — возвращает
    заглушку. Все вызовы пишутся в self.calls для проверок в тестах.
    """

    def __init__(self, handler: Callable[[str, str], str] | None = None) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._handler is not None:
            return self._handler(system, user)
        return "Ответ подготовлен на основании переданных статей."