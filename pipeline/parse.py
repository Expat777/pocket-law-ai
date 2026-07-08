"""parse: HTML ИПС -> структура «раздел -> глава -> статья».

Разметка ИПС (проверена в SOURCE.md):
  <p class="T">ЧАСТЬ ... / РАЗДЕЛ ...</p>
  <p class="H">ГЛАВА N. ... / Статья N. Заголовок</p>
  <p>текст статьи</p>            (класс отсутствует)
  <p class="I">, <p class="C">   (служебные — пропускаем)

Составные номера — надстрочными спанами: «Статья 181<span class="W9">1</span>.»
означает статью 181.1 (коллектор вставляет точку перед содержимым W9-спана).
"""

from __future__ import annotations

import hashlib
import html as html_mod
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

log = logging.getLogger(__name__)

_RE_CHAPTER = re.compile(r"^ГЛАВА\s+([\d.]+)[.\s]*(.*)", re.IGNORECASE)
_RE_ARTICLE = re.compile(r"^Статья\s+([\d.]+(?:-\d+)?)\.?\s*(.*)")  # бывает «348.11-1»
_RE_REPEALED = re.compile(r"утратил[аи]?\s+силу", re.IGNORECASE)
# сноски «(В редакции федерального закона …)» повторяются сотнями и шумят в поиске
_RE_FOOTNOTE = re.compile(r"\((?:В редакции|Наименование в редакции)[^()]*\)")


class ParseError(RuntimeError):
    pass


@dataclass
class Article:
    act: str
    article_no: str
    title: str
    chapter: str
    text: str = ""
    status: str = "active"  # active | repealed (amended — фаза 2, см. SOURCE.md)

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.strip().encode()).hexdigest()


class _ParagraphCollector(HTMLParser):
    """Собирает последовательность (класс, текст) всех <p> документа."""

    def __init__(self) -> None:
        super().__init__()
        self.paragraphs: list[tuple[str, str]] = []
        self._cls: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "p":
            self._cls = dict(attrs).get("class", "")
            self._buf = []
        elif tag == "span" and self._cls is not None and dict(attrs).get("class") == "W9":
            self._buf.append(".")  # надстрочный индекс: 181¹ -> 181.1

    def handle_data(self, data: str) -> None:
        if self._cls is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._cls is not None:
            text = html_mod.unescape("".join(self._buf))
            text = _RE_FOOTNOTE.sub("", text)
            text = re.sub(r"[\s\xa0]+", " ", text).strip()
            if text:
                self.paragraphs.append((self._cls, text))
            self._cls = None


def parse_ips_html(html: str, act: str, min_articles: int) -> list[Article]:
    collector = _ParagraphCollector()
    collector.feed(html)

    articles: list[Article] = []
    chapter = ""
    current: Article | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current
        if current is not None:
            text = "\n".join(body)
            # статус определяем ДО вычистки сносок: маркер «(Утратила силу — …)» — и есть сигнал
            if _RE_REPEALED.search(current.title) or _RE_REPEALED.search(text[:200]):
                current.status = "repealed"
            elif not text.strip() and not current.title.strip():
                # голый стаб «Статья N.» без заголовка и тела — в ФЗ так помечают утратившие
                # силу статьи (в ЗоЗПП: ст. 26/38/42), контент перенесён в N.1/N.2
                current.status = "repealed"
            current.text = re.sub(r" {2,}", " ", _RE_FOOTNOTE.sub("", text)).strip()
            articles.append(current)
            current = None

    for cls, text in collector.paragraphs:
        if cls in ("I", "C", "T"):
            continue
        if cls == "H":
            m = _RE_CHAPTER.match(text)
            if m:
                chapter = f"Глава {m.group(1).rstrip('.')}. {m.group(2)}".strip().rstrip(".")
                continue
            m = _RE_ARTICLE.match(text)
            if m:
                flush()
                body = []
                current = Article(act=act, article_no=m.group(1).rstrip("."), title=m.group(2), chapter=chapter)
                continue
            continue  # прочие H-заголовки (например, название кодекса)
        if cls == "" and current is not None:
            body.append(text)
    flush()

    # Строгие проверки: при поломке разметки падаем громко, а не портим базу молча
    if len(articles) < min_articles:
        raise ParseError(f"{act}: распарсено {len(articles)} статей, ожидалось >= {min_articles} — разметка источника изменилась?")
    empty = [a.article_no for a in articles if not a.text.strip() and a.status == "active"]
    if len(empty) > len(articles) * 0.05:
        raise ParseError(f"{act}: слишком много пустых действующих статей: {empty[:10]}...")
    seen: set[str] = set()
    dups = {a.article_no for a in articles if a.article_no in seen or seen.add(a.article_no)}
    if dups:
        raise ParseError(f"{act}: дубликаты номеров статей: {sorted(dups)[:10]}")

    log.info("parse %s: %d статей, %d глав, repealed: %d",
             act, len(articles), len({a.chapter for a in articles}),
             sum(a.status == "repealed" for a in articles))
    return articles
