"""Безопасное скачивание пользовательского URL (защита от SSRF).

URL приходит от пользователя, а сервер сидит в одной сети с Qdrant/Postgres/
прокси и облачными метаданными — поэтому ДО запроса проверяем, что хост
резолвится только в публичные адреса, и разрешаем лишь http/https и известные
типы контента. Есть лимит размера, таймаут и контроль редиректов.

Остаточный риск DNS-rebinding (хост меняет A-запись между проверкой и коннектом)
для MVP принят — блокировки приватных диапазонов достаточно против типовых атак.
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

MAX_BYTES = int(os.getenv("URL_MAX_BYTES", str(20 * 1024 * 1024)))  # 20 МБ
TIMEOUT = float(os.getenv("URL_FETCH_TIMEOUT", "15"))
MAX_REDIRECTS = 3
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "image/",
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/",
)


def _is_public_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_url_allowed(url: str) -> None:
    """Схема http/https и хост резолвится ТОЛЬКО в публичные IP. Иначе ValueError."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError("разрешены только http/https ссылки")
    host = parsed.hostname
    if not host:
        raise ValueError("некорректный URL (нет хоста)")
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except socket.gaierror:
        raise ValueError("не удалось разрешить хост") from None
    ips = {info[4][0] for info in infos}
    if not ips:
        raise ValueError("не удалось разрешить хост")
    for ip in ips:
        if not _is_public_ip(ip):
            raise ValueError("доступ к внутренним/приватным адресам запрещён")


async def fetch_url(url: str) -> tuple[bytes, str]:
    """Скачивает URL с SSRF-проверкой. Возвращает (данные, mime). Бросает ValueError."""
    import httpx  # ленивый импорт

    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_url_allowed(current)
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            async with client.stream(
                "GET", current, headers={"User-Agent": "pocket-law-ai/1.0"}
            ) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("редирект без Location")
                    current = str(httpx.URL(current).join(loc))
                    continue
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
                    raise ValueError(f"неподдерживаемый тип контента: {mime or 'неизвестно'}")
                data = b""
                async for part in resp.aiter_bytes():
                    data += part
                    if len(data) > MAX_BYTES:
                        raise ValueError("файл превышает лимит размера (20 МБ)")
                return data, mime
    raise ValueError("слишком много редиректов")