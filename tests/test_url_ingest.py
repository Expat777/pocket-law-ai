"""Тесты загрузки по URL: SSRF-гард, извлечение текста, ingest_url (без сети)."""

import pytest

from agent.tools.extract import _html_to_text, extract_document  # noqa: F401
from agent.ingest import ingest_url
from agent.tools.fetch_url import assert_url_allowed


def test_ssrf_blocks_loopback():
    with pytest.raises(ValueError):
        assert_url_allowed("http://127.0.0.1/x")


def test_ssrf_blocks_metadata_ip():
    with pytest.raises(ValueError):
        assert_url_allowed("http://169.254.169.254/latest/meta-data")


def test_ssrf_blocks_private_range():
    with pytest.raises(ValueError):
        assert_url_allowed("http://10.0.0.5/internal")


def test_ssrf_blocks_nonhttp_scheme():
    with pytest.raises(ValueError):
        assert_url_allowed("file:///etc/passwd")


def test_extract_html_strips_tags_and_scripts():
    html = (
        "<html><body><script>evil()</script>"
        "<h1>Договор</h1><p>Пункт 1.</p></body></html>"
    ).encode()
    doc = extract_document(html, "text/html")
    assert "Договор" in doc.text and "Пункт 1." in doc.text
    assert "<h1>" not in doc.text and "evil()" not in doc.text


def test_extract_plain_text():
    doc = extract_document("простой текст".encode(), "text/plain")
    assert doc.text == "простой текст"


def test_extract_unsupported_type_raises():
    with pytest.raises(ValueError):
        extract_document(b"\x00\x01", "application/octet-stream")


async def test_ingest_url_happy_with_fake_fetch():
    """ingest_url скачивает (мок), извлекает текст HTML и индексирует с изоляцией."""
    captured = {}

    async def fake_fetch(url):
        body = "<html><body>Договор аренды. Плата 5000 рублей.</body></html>".encode()
        return body, "text/html"

    def fake_embed(chunks):
        return [[0.1, 0.2, 0.3] for _ in chunks]

    async def fake_upsert(user_id, doc_id, chunks, vectors):
        captured["user_id"] = user_id
        captured["chunks"] = chunks

    res = await ingest_url(
        42, "https://example.com/doc", fetch=fake_fetch, embed=fake_embed, upsert=fake_upsert
    )

    assert res.ok is True
    assert captured["user_id"] == 42
    assert any("Договор" in c for c in captured["chunks"])


async def test_ingest_url_fetch_error_is_graceful():
    async def bad_fetch(url):
        raise ValueError("доступ к внутренним/приватным адресам запрещён")

    res = await ingest_url(1, "http://127.0.0.1/", fetch=bad_fetch)
    assert res.ok is False
    assert "fetch" in (res.error or "")


def test_security_rules_mention_url():
    """Канарейка: правила безопасности явно упоминают контент по ссылке/URL."""
    from agent.prompts import COMPOSE_SYSTEM

    low = COMPOSE_SYSTEM.lower()
    assert "по ссылке" in low or "url" in low