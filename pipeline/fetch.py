"""fetch: скачивание консолидированного текста акта из ИПС pravo.gov.ru.

Двухшаговая схема (подробности и грабли — в SOURCE.md):
1. страница документа ?docbody= -> выпадашка редакций -> номер (rdk) и дата последней;
2. экспорт ?savertf=&page=all&rdk=N -> MHTML, внутри text/html со всем текстом.

ВАЖНО: rdk=0 — это ПЕРВОНАЧАЛЬНАЯ редакция (для ТК РФ — 2001 год), не действующая!
"""

from __future__ import annotations

import email
import logging
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

from .acts import ActInfo

log = logging.getLogger(__name__)

_BASE = "http://pravo.gov.ru/proxy/ips/"
_HEADERS = {"User-Agent": "pocket-law-ai/0.1 (student project; contact in repo README)"}


class FetchError(RuntimeError):
    pass


@dataclass
class FetchedAct:
    html: str            # полный HTML тела документа, utf-8
    rdk: int             # номер редакции в ИПС
    revision_date: date | None  # дата последней редакции (из выпадашки)


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _latest_redaction(nd: str) -> tuple[int, date | None]:
    html = _get(f"{_BASE}?docbody=&nd={nd}").decode("cp1251", errors="replace")
    options = re.findall(rf"<option value='(\d+),{nd}'[^>]*>([^<]*)", html)
    if not options:
        raise FetchError(f"nd={nd}: не нашёл список редакций на странице документа")
    rdk, label = max(options, key=lambda o: int(o[0]))
    m = re.search(r"от\s+(\d{2}\.\d{2}\.\d{4})", label)
    rev_date = datetime.strptime(m.group(1), "%d.%m.%Y").date() if m else None
    log.info("nd=%s: редакций %d, беру rdk=%s (%s)", nd, len(options), rdk, label.strip())
    return int(rdk), rev_date


def _extract_html_from_mhtml(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("cp1251", errors="replace")
    raise FetchError("в экспорте ИПС не нашлось HTML-части (формат изменился?)")


def fetch_act(info: ActInfo, retries: int = 3) -> FetchedAct:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            rdk, rev_date = _latest_redaction(info.nd)
            raw = _get(f"{_BASE}?savertf=&nd={info.nd}&page=all&rdk={rdk}", timeout=300)
            html = _extract_html_from_mhtml(raw)
            if len(html) < 100_000:
                raise FetchError(f"{info.code}: подозрительно короткий экспорт ({len(html)} байт)")
            log.info("fetch %s: rdk=%d от %s, %d КБ", info.code, rdk, rev_date, len(html) // 1024)
            return FetchedAct(html=html, rdk=rdk, revision_date=rev_date)
        except FetchError:
            raise
        except Exception as e:  # сеть/5xx — ретраим с паузой
            last_err = e
            log.warning("fetch %s: попытка %d/%d не удалась: %s", info.code, attempt, retries, e)
            time.sleep(2 * attempt)
    raise FetchError(f"{info.code}: источник недоступен после {retries} попыток") from last_err
