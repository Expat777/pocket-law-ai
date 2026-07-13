"""Регрессия pipeline/watch.py — автообновление НПА.

Сеть не трогаем: подменяем _latest_redaction. Проверяем ровно то, ради чего watch и писался:
дешёвый ярус не должен качать документ, а дорогой — запускаться только по факту изменения.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipeline import watch as W
from pipeline.acts import ACTS


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(W.time, "sleep", lambda *_: None)


def _fake_redaction(monkeypatch, rdk: int, rev: date | None):
    monkeypatch.setattr(W, "_latest_redaction", lambda nd: (rdk, rev))


def test_unchanged_redaction_does_not_trigger_update(monkeypatch, no_sleep):
    """Главный смысл watch: редакция та же → документ НЕ качаем, эмбеддинги НЕ считаем."""
    _fake_redaction(monkeypatch, 10, date(2026, 1, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {"tk_rf": "10:2026-01-01"})
    called = []
    monkeypatch.setattr(W, "update_act", lambda *a, **k: called.append(1))

    r = W.watch(["tk_rf"])
    assert r["fresh"] == 1
    assert r["changed"] == []
    assert called == [], "запустил дорогой пайплайн, хотя редакция не менялась"


def test_new_redaction_triggers_update(monkeypatch, no_sleep):
    _fake_redaction(monkeypatch, 11, date(2026, 2, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {"tk_rf": "10:2026-01-01"})
    called = []
    monkeypatch.setattr(W, "update_act", lambda info, **k: called.append(info.code) or {"chunks": 5})

    r = W.watch(["tk_rf"])
    assert r["changed"] == ["tk_rf"]
    assert called == ["tk_rf"]


def test_unknown_act_is_treated_as_changed(monkeypatch, no_sleep):
    """Акта нет в state (первый прогон / state потерян) → обязан залиться."""
    _fake_redaction(monkeypatch, 1, date(2026, 1, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {})
    monkeypatch.setattr(W, "update_act", lambda info, **k: {"chunks": 1})
    assert W.watch(["tk_rf"])["changed"] == ["tk_rf"]


def test_future_redaction_is_skipped(monkeypatch, no_sleep):
    """GUARD: редакция ещё не вступила в силу — заливать её нельзя.

    Иначе бот начнёт цитировать норму, которой на сегодня не существует.
    """
    future = date.today() + timedelta(days=30)
    _fake_redaction(monkeypatch, 99, future)
    monkeypatch.setattr(W, "load_redactions", lambda: {"tk_rf": "10:2026-01-01"})
    called = []
    monkeypatch.setattr(W, "update_act", lambda *a, **k: called.append(1))

    r = W.watch(["tk_rf"])
    assert r["changed"] == []
    assert called == [], "залил не вступившую в силу редакцию"
    assert r["skipped"] and "не вступила" in r["skipped"][0][1]


def test_check_only_never_updates(monkeypatch, no_sleep):
    _fake_redaction(monkeypatch, 11, date(2026, 2, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {})
    called = []
    monkeypatch.setattr(W, "update_act", lambda *a, **k: called.append(1))

    r = W.watch(["tk_rf"], check_only=True)
    assert r["changed"] == ["tk_rf"] and called == []


def test_ips_throttle_is_retried_then_reported(monkeypatch, no_sleep):
    """ИПС на троттлинге кидает FetchError; fetch_act его НЕ ретраит — ретраим здесь."""
    attempts = []

    def flaky(nd):
        attempts.append(nd)
        raise RuntimeError("Connection reset by peer")

    monkeypatch.setattr(W, "_latest_redaction", flaky)
    monkeypatch.setattr(W, "load_redactions", lambda: {})
    r = W.watch(["tk_rf"])

    assert len(attempts) == W.RETRIES, "не отретраил проверку"
    assert r["failed"] and r["changed"] == []


def test_one_bad_act_does_not_stop_the_rest(monkeypatch, no_sleep):
    """Падение одного акта не должно ронять ночной прогон целиком."""
    def per_act(nd):
        if nd == ACTS["uk_rf"].nd:
            raise RuntimeError("502")
        return 5, date(2026, 3, 1)

    monkeypatch.setattr(W, "_latest_redaction", per_act)
    monkeypatch.setattr(W, "load_redactions", lambda: {})
    monkeypatch.setattr(W, "update_act", lambda info, **k: {"chunks": 1})

    r = W.watch(["tk_rf", "uk_rf", "sk_rf"])
    assert set(r["changed"]) == {"tk_rf", "sk_rf"}
    assert [c for c, _ in r["failed"]] == ["uk_rf"]


def test_seed_records_baseline_without_indexing(monkeypatch, no_sleep):
    """--seed на уже актуальной базе: записать редакции, НЕ трогая Qdrant.

    Без seed первый ночной прогон на чистом state счёл бы все 57 актов изменившимися
    и устроил полный ре-индекс — часы эмбеддингов впустую.
    """
    _fake_redaction(monkeypatch, 7, date(2026, 5, 1))
    saved = {}
    monkeypatch.setattr("pipeline.state.save_raw_redaction", lambda c, m: saved.__setitem__(c, m))
    called = []
    monkeypatch.setattr(W, "update_act", lambda *a, **k: called.append(1))

    s = W.seed(["tk_rf", "uk_rf"])
    assert s["seeded"] == ["tk_rf", "uk_rf"]
    assert saved == {"tk_rf": "7:2026-05-01", "uk_rf": "7:2026-05-01"}
    assert called == [], "seed не должен ничего индексировать"


def test_seed_then_watch_is_quiet(monkeypatch, no_sleep):
    """После seed обычный прогон обязан молчать — ради этого всё и затевалось."""
    _fake_redaction(monkeypatch, 7, date(2026, 5, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {"tk_rf": "7:2026-05-01"})
    called = []
    monkeypatch.setattr(W, "update_act", lambda *a, **k: called.append(1))

    r = W.watch(["tk_rf"])
    assert r["fresh"] == 1 and r["changed"] == [] and called == []


def test_update_failure_is_reported_not_swallowed(monkeypatch, no_sleep):
    _fake_redaction(monkeypatch, 11, date(2026, 2, 1))
    monkeypatch.setattr(W, "load_redactions", lambda: {})

    def boom(info, **k):
        raise RuntimeError("Qdrant недоступен")

    monkeypatch.setattr(W, "update_act", boom)
    r = W.watch(["tk_rf"])
    assert r["failed"] and "Qdrant" in r["failed"][0][1]
