"""Инструмент transcribe_audio (Роль 2): голосовое сообщение -> текст (STT).

Пользователь наговаривает юр-вопрос голосом вместо печати; мы распознаём его в
текст и дальше идём ОБЫЧНЫМ потоком answer_question (бот отвечает текстом, как и
раньше). Канал — OpenAI-совместимый /audio/transcriptions нашего LLM-провайдера
(Polza, модель Whisper): тот же ключ/база, что и для LLM, — отдельного провайдера/
инфраструктуры не нужно, а граница доверия ПДн не расширяется (текст вопроса и так
уходит в Polza для генерации ответа).

⚠️ Распознанный текст ОБЯЗАТЕЛЬНО показывать пользователю обратно (это делает бот,
Роль 1): для юр-бота ошибка STT («ст. 158»->«ст. 150», «развод»->«провод») меняет
весь ответ, поэтому пользователь должен видеть, что именно распозналось.
"""

import os

from agent.config import STT_LANGUAGE, STT_MAX_BYTES, STT_MODEL, STT_TIMEOUT
from agent.tracing import tool_span

# Расширение -> MIME для multipart. Telegram voice = OGG/Opus.
_MIME = {
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".wav": "audio/wav", ".webm": "audio/webm", ".flac": "audio/flac",
}


def _mime(filename: str) -> str:
    return _MIME.get(os.path.splitext(filename or "")[1].lower(), "application/octet-stream")


async def _default_post(audio_bytes: bytes, filename: str, model: str, language: str) -> str:
    """Боевой вызов STT-эндпоинта (ленивый httpx — как в openai_compat)."""
    import httpx

    base = os.getenv("LLM_BASE_URL", "https://api.polza.ai/api/v1").rstrip("/")
    key = os.getenv("LLM_API_KEY", "")
    files = {"file": (filename, audio_bytes, _mime(filename))}
    data = {"model": model, "language": language}
    async with httpx.AsyncClient(timeout=STT_TIMEOUT) as client:
        r = await client.post(
            f"{base}/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
        )
    r.raise_for_status()
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return (body or {}).get("text", "") if isinstance(body, dict) else ""


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "voice.ogg",
    *,
    model: str | None = None,
    language: str | None = None,
    post=None,
) -> str:
    """Голосовое (bytes) -> распознанный текст. Пусто -> "". post внедряем для тестов.

    Кидает ValueError на слишком большой файл (защита бюджета/лимит провайдера).
    """
    if not audio_bytes:
        return ""
    if len(audio_bytes) > STT_MAX_BYTES:
        raise ValueError(f"аудио слишком большое: {len(audio_bytes)} > {STT_MAX_BYTES} байт")

    model = model or STT_MODEL
    language = language or STT_LANGUAGE
    post = post or _default_post
    # В span НЕ кладём аудио/ключ — только модель, имя и размер.
    with tool_span(
        "transcribe_audio", {"model": model, "filename": filename, "bytes": len(audio_bytes)}
    ) as record:
        text = (await post(audio_bytes, filename, model, language)).strip()
        record({"chars": len(text)})
    return text