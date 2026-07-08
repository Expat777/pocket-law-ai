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


def _rev_date(label: str) -> date | None:
    m = re.search(r"от\s+(\d{2}\.\d{2}\.\d{4})", label)
    return datetime.strptime(m.group(1), "%d.%m.%Y").date() if m else None


def _latest_redaction(nd: str) -> tuple[int, date | None]:
    html = _get(f"{_BASE}?docbody=&nd={nd}").decode("cp1251", errors="replace")
    options = re.findall(rf"<option value='(\d+),{nd}'[^>]*>([^<]*)", html)
    if not options:
        raise FetchError(f"nd={nd}: не нашёл список редакций на странице документа")
    # ВАЖНО: rdk НЕ монотонен по дате! У ГК ч.3 максимальный rdk (34) = ИСХОДНАЯ редакция
    # 2001 г., а действующая — rdk=32 (2024). Атрибут `selected` тоже ненадёжен (у ГК ч.3
    # помечает 2001-ю). Действующая редакция = с МАКСИМАЛЬНОЙ ДАТОЙ; при равных — макс. rdk.
    rdk, label = max(options, key=lambda o: (_rev_date(o[1]) or date.min, int(o[0])))
    rev_date = _rev_date(label)
    if rev_date is None:  # ни у одной опции нет даты — деградируем к прежнему (макс. rdk)
        rdk, label = max(options, key=lambda o: int(o[0]))
        rev_date = _rev_date(label)
    log.info("nd=%s: редакций %d, беру rdk=%s по дате (%s)", nd, len(options), rdk, label.strip())
    return int(rdk), rev_date


def _extract_html_from_mhtml(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("cp1251", errors="replace")
    raise FetchError("в экспорте ИПС не нашлось HTML-части (формат изменился?)")


def _fetch_body(nd: str, rdk: int) -> str:
    """Тело документа в HTML. Основной путь — экспорт savertf (MHTML).

    Для ОЧЕНЬ больших документов (НК ч.2, ~9 МБ) savertf валит шлюз ИПС
    (ConnectionReset/502 даже с page=all). Запасной путь — вьюер `doc_itself&fulltext=1`:
    отдаёт весь текст напрямую HTML-ом (проверено: НК ч.2 → textCompleted=True, 540 статей).
    Обычные акты как и раньше идут через savertf — их поведение не меняется.
    """
    try:
        raw = _get(f"{_BASE}?savertf=&nd={nd}&page=all&rdk={rdk}", timeout=300)
        html = _extract_html_from_mhtml(raw)
        if len(html) >= 100_000:
            return html
        log.warning("nd=%s: savertf дал короткий экспорт (%d) — пробую doc_itself&fulltext=1", nd, len(html))
    except FetchError:
        raise
    except Exception as e:
        log.warning("nd=%s: savertf не удался (%s) — пробую doc_itself&fulltext=1", nd, e)

    html = _get(f"{_BASE}?doc_itself=&nd={nd}&rdk={rdk}&fulltext=1", timeout=300).decode("cp1251", errors="replace")
    if len(html) < 100_000:
        raise FetchError(f"nd={nd}: и savertf, и fulltext дали слишком короткий текст ({len(html)} байт)")
    return html


def fetch_act(info: ActInfo, retries: int = 3) -> FetchedAct:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            rdk, rev_date = _latest_redaction(info.nd)
            html = _fetch_body(info.nd, rdk)
            log.info("fetch %s: rdk=%d от %s, %d КБ", info.code, rdk, rev_date, len(html) // 1024)
            return FetchedAct(html=html, rdk=rdk, revision_date=rev_date)
        except FetchError:
            raise
        except Exception as e:  # сеть/5xx — ретраим с паузой
            last_err = e
            log.warning("fetch %s: попытка %d/%d не удалась: %s", info.code, attempt, retries, e)
            time.sleep(2 * attempt)
    raise FetchError(f"{info.code}: источник недоступен после {retries} попыток") from last_err
