"""Регрессия chunk.py и реестра acts.py.

Ключевые инварианты, на которых держится идемпотентность заливки:
  - id детерминирован (uuid5 от act:article:i) → повторный прогон не плодит дубликатов;
  - заголовок статьи дублируется в КАЖДЫЙ чанк (иначе обрезок теряет контекст статьи);
  - act-строки уникальны по смыслу → нет коллизий id между разными законами.
"""

from pipeline.acts import ACTS
from pipeline.chunk import chunk_article
from pipeline.config import MAX_CHUNK_CHARS
from pipeline.parse import Article


def _article(text: str, act: str = "ТК РФ", no: str = "81") -> Article:
    return Article(act=act, article_no=no, title="Заголовок", chapter="Глава 1", text=text)


def test_short_article_is_one_chunk_with_header():
    chunks = chunk_article(_article("Короткий текст статьи."))
    assert len(chunks) == 1
    assert chunks[0].text.startswith("ТК РФ, статья 81. Заголовок")
    assert "Короткий текст статьи." in chunks[0].text


def test_id_is_deterministic():
    """Повторный прогон обязан дать тот же id — иначе delete+upsert плодит сирот."""
    a, b = chunk_article(_article("Текст.")), chunk_article(_article("Текст."))
    assert a[0].id == b[0].id


def test_id_differs_across_acts_same_article_no():
    """Ст. 81 есть и в ТК, и в УК — id не должны схлопнуться."""
    tk = chunk_article(_article("Текст.", act="ТК РФ", no="81"))
    uk = chunk_article(_article("Текст.", act="УК РФ", no="81"))
    assert tk[0].id != uk[0].id


def test_long_article_splits_and_every_chunk_keeps_header():
    para = "А" * 900
    long_text = "\n".join([para] * 6)  # ~5400 симв > MAX_CHUNK_CHARS
    chunks = chunk_article(_article(long_text))
    assert len(chunks) > 1, "длинная статья должна дорезаться по абзацам"
    for c in chunks:
        assert c.text.startswith("ТК РФ, статья 81. Заголовок"), "чанк потерял заголовок статьи"
        assert c.payload["article_no"] == "81"
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "id чанков одной статьи не уникальны"


def test_chunk_respects_limit_when_paragraphs_allow():
    chunks = chunk_article(_article("\n".join(["Б" * 500] * 10)))
    for c in chunks:
        # заголовок добавляется сверх лимита, но тело не должно кратно его превышать
        assert len(c.text) < MAX_CHUNK_CHARS + 600


def test_payload_schema():
    c = chunk_article(_article("Текст."), source_url="http://example/x")[0]
    for key in ("act", "article_no", "chapter", "status", "effective_date", "source_url", "text"):
        assert key in c.payload, f"в payload нет поля {key}"
    assert c.payload["source_url"] == "http://example/x"


def test_empty_article_still_produces_chunk():
    """Утратившая силу статья с пустым телом не должна ронять чанкер."""
    chunks = chunk_article(_article(""))
    assert len(chunks) == 1


# --- реестр актов ---

def test_acts_registry_is_consistent():
    assert all(k == v.code for k, v in ACTS.items()), "ключ словаря != code"
    nds = [v.nd for v in ACTS.values()]
    assert len(nds) == len(set(nds)), "один и тот же nd заведён дважды"
    assert all(v.min_articles > 0 for v in ACTS.values())
    assert all(v.nd.isdigit() for v in ACTS.values()), "nd должен быть числовым id ИПС"


def test_number_collisions_are_distinct_laws():
    """115-ФЗ и 218-ФЗ — по ДВА разных закона под одним номером.

    Ровно та грабля, на которой мы взяли утративший силу 62-ФЗ вместо 138-ФЗ.
    """
    assert ACTS["aml_115"].nd != ACTS["inostr_115"].nd
    assert ACTS["bki_218"].nd != ACTS["regned_218"].nd


def test_multipart_codes_share_one_act_string():
    """ГК ч.1-4 и НК ч.1-2 залиты под одним act — так работает роутинг Роли 2."""
    assert {ACTS[c].act for c in ("gk_rf_1", "gk_rf_2", "gk_rf_3", "gk_rf_4")} == {"ГК РФ"}
    assert {ACTS[c].act for c in ("nk_rf_1", "nk_rf_2")} == {"НК РФ"}
