"""Регрессия parse.py: по одному тесту на КАЖДЫЙ баг источника, который мы чинили.

Все фикстуры — синтетическая разметка ИПС (офлайн, без сети): тесты гоняются за
миллисекунды и ловят регрессию до того, как она уедет в боевую базу.
История багов — в STATUS.md, секция Роли 3.
"""

import pytest

from pipeline.parse import ParseError, parse_ips_html


def _html(body: str) -> str:
    return f'<html><body>{body}</body></html>'


def _art(no: str, title: str, *paras: str, cls: str = "H") -> str:
    head = f'<p class="{cls}">Статья {no}. {title}</p>'
    return head + "".join(f"<p>{p}</p>" for p in paras)


def test_basic_article_and_chapter():
    html = _html(
        '<p class="H">ГЛАВА 1. Общие положения</p>'
        + _art("1", "Предмет", "Текст первой статьи.")
        + _art("2", "Сфера", "Текст второй статьи.")
    )
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert [a.article_no for a in arts] == ["1", "2"]
    assert arts[0].title == "Предмет"
    assert arts[0].chapter == "Глава 1. Общие положения"
    assert arts[0].status == "active"


def test_superscript_w9_becomes_dotted_number():
    """«Статья 181<span class=W9>1</span>.» — надстрочный индекс → номер 181.1."""
    html = _html(_art("1", "A", "x") + '<p class="H">Статья 181<span class="W9">1</span>. Заголовок</p><p>Тело.</p>')
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert arts[1].article_no == "181.1"


def test_double_dash_numbering():
    """Баг 127-ФЗ (банкротство): номера вида 201.15-2-1 — двойной дефис.

    Раньше regex ловил только один дефисный суффикс → «201.15-2» и «201.15-2-1»
    схлопывались в один номер → ParseError «дубликаты».
    """
    html = _html(
        _art("201.15-1", "A", "Текст.")
        + _art("201.15-2", "B", "Текст.")
        + _art("201.15-2-1", "C", "Текст.")
        + _art("201.15-2-2", "D", "Текст.")
    )
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=4)
    assert [a.article_no for a in arts] == ["201.15-1", "201.15-2", "201.15-2-1", "201.15-2-2"]


def test_part_repeal_keeps_article_active():
    """Баг КоАП 12.9: «(Часть утратила силу)» у ОДНОЙ части гасила ВСЮ статью.

    ~49 действующих статей КоАП молча исчезали из цитат (12.9 — превышение скорости).
    Статья жива, пока после удаления скобочных пометок остаётся осмысленный текст.
    """
    html = _html(
        _art("1", "A", "Текст.")
        + _art(
            "12.9",
            "Превышение установленной скорости движения",
            "1. (Часть утратила силу — Федеральный закон от 23.07.2013 № 196-ФЗ)",
            "2. Превышение скорости на величину более 20, но не более 40 км/ч — "
            "влечёт наложение административного штрафа в размере пятисот рублей.",
        )
    )
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    a = {x.article_no: x for x in arts}["12.9"]
    assert a.status == "active", "живая статья с одной мёртвой частью помечена repealed"
    assert "пятисот рублей" in a.text


def test_fully_repealed_article_is_marked():
    """Обратная сторона: если ВЕСЬ текст — только пометка об утрате силы, статья мертва."""
    html = _html(
        _art("1", "A", "Текст.")
        + _art("2", "", "(Статья утратила силу — Федеральный закон от 01.01.2020 № 1-ФЗ)")
    )
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert {x.article_no: x for x in arts}["2"].status == "repealed"


def test_bare_stub_is_repealed():
    """ЗоЗПП ст.26/38/42: голый стаб «Статья N.» без заголовка и тела = утратила силу."""
    html = _html(_art("1", "A", "Текст.") + '<p class="H">Статья 26.</p>')
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert {x.article_no: x for x in arts}["26"].status == "repealed"


def test_repeal_in_title_marks_repealed():
    html = _html(_art("1", "A", "Текст.") + _art("2", "Утратила силу", "остаточный текст"))
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert {x.article_no: x for x in arts}["2"].status == "repealed"


def test_old_format_headers_without_class_h():
    """Закон РФ 1991 (приватизация жилья): заголовки статей в голых <p> без class=H.

    Основной проход находит < min_articles → включается двухпроходный фолбэк,
    контент старого формата идёт в ТЕЛО статьи, а не в заголовок.
    """
    html = _html(
        '<p>Статья 1. Приватизация жилых помещений — бесплатная передача в собственность.</p>'
        '<p>Дополнительный абзац.</p>'
        '<p>Статья 2. Граждане вправе приобрести жилые помещения в собственность.</p>'
    )
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=2)
    assert [a.article_no for a in arts] == ["1", "2"]
    assert "бесплатная передача" in arts[0].text
    assert arts[0].status == "active"


def test_footnotes_are_stripped():
    """Сноски «(В редакции федерального закона …)» повторяются сотнями и шумят в поиске."""
    html = _html(_art("1", "A", "Основной текст. (В редакции федерального закона от 01.01.2020 № 1-ФЗ)"))
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=1)
    assert "В редакции" not in arts[0].text
    assert "Основной текст." in arts[0].text


def test_service_paragraphs_ignored():
    html = _html('<p class="I">служебное</p><p class="C">служебное</p><p class="T">РАЗДЕЛ I</p>' + _art("1", "A", "Текст."))
    arts = parse_ips_html(html, act="ТЕСТ", min_articles=1)
    assert len(arts) == 1


# --- строгие гейты: при поломке источника падаем громко, а не портим базу молча ---

def test_raises_on_too_few_articles():
    with pytest.raises(ParseError, match="ожидалось"):
        parse_ips_html(_html(_art("1", "A", "Текст.")), act="ТЕСТ", min_articles=50)


def test_raises_on_duplicate_numbers():
    html = _html(_art("1", "A", "Текст.") + _art("1", "B", "Текст.") + _art("2", "C", "Текст."))
    with pytest.raises(ParseError, match="[Дд]убликаты"):
        parse_ips_html(html, act="ТЕСТ", min_articles=2)
