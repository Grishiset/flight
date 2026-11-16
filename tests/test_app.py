import json
from datetime import date, datetime, timedelta, timezone

from tracker.analyze import evaluate, pick_alerts
from tracker.app import run
from tracker.config import load_config
from tracker.models import Offer, SourceResult
from tracker.notify import alert_message, digest_message
from tracker.store import Store

NOW = datetime(2026, 11, 17, 8, 17, tzinfo=timezone.utc)   # вторник


def offer(route, price, dep=date(2027, 7, 1), days=14, source="travelpayouts", **kw):
    return Offer(route_id=route, source=source, price_rub=price, depart=dep, ret=dep + timedelta(days=days), **kw)


def test_window_filter_and_best():
    cfg = load_config("config.yaml")
    offers = [
        offer("SEL", 30000, dep=date(2027, 5, 25)),          # вылет до лета
        offer("SEL", 31000, dep=date(2027, 8, 25)),          # возврат после лета
        offer("SEL", 50000, dep=date(2027, 7, 1), days=2),   # слишком коротко
        offer("SEL", 41000, airline="CA"),
        offer("SEL", 45000, source="etihad"),
        offer("TYO", 60000),
    ]
    sts = {s.route_id: s for s in evaluate(cfg, offers, [], NOW)}
    assert sts["SEL"].best.price_rub == 41000
    assert set(sts["SEL"].by_source) == {"travelpayouts", "etihad"}
    assert sts["SEL"].is_deal and "порога" in sts["SEL"].reasons[0]
    assert sts["TYO"].best.price_rub == 60000 and not sts["TYO"].is_deal
    assert sts["NYC"].best is None


def test_baseline_drop():
    cfg = load_config("config.yaml")
    history = [{"at": (NOW - timedelta(hours=4 * i)).isoformat(), "routes": {"TYO": {"best": 60000}}} for i in range(1, 15)]
    sts = {s.route_id: s for s in evaluate(cfg, [offer("TYO", 50000)], history, NOW)}
    assert sts["TYO"].median == 60000
    assert any("ниже обычного" in r for r in sts["TYO"].reasons)
    sts = {s.route_id: s for s in evaluate(cfg, [offer("TYO", 55000)], history, NOW)}
    assert not sts["TYO"].is_deal


def test_google_typical():
    cfg = load_config("config.yaml")
    o = offer("NYC", 66000, source="google_flights", typical_range=[70000, 95000])
    st = {s.route_id: s for s in evaluate(cfg, [o], [], NOW)}["NYC"]
    assert any("Google" in r for r in st.reasons)


def test_alert_dedupe():
    cfg = load_config("config.yaml")
    state = {}
    s1 = evaluate(cfg, [offer("SEL", 41000)], [], NOW)
    assert [s.route_id for s in pick_alerts(s1, state, cfg, NOW)] == ["SEL"]
    # та же цена через 4 часа — молчим
    s2 = evaluate(cfg, [offer("SEL", 40800)], [], NOW + timedelta(hours=4))
    assert pick_alerts(s2, state, cfg, NOW + timedelta(hours=4)) == []
    # упала ещё на 1000+ — уведомляем
    s3 = evaluate(cfg, [offer("SEL", 39500)], [], NOW + timedelta(hours=8))
    assert len(pick_alerts(s3, state, cfg, NOW + timedelta(hours=8))) == 1
    # цена ушла выше порога — состояние сброшено, следующее падение снова придёт
    s4 = evaluate(cfg, [offer("SEL", 50000)], [], NOW + timedelta(hours=12))
    assert pick_alerts(s4, state, cfg, NOW + timedelta(hours=12)) == [] and "SEL" not in state["alerts"]
    s5 = evaluate(cfg, [offer("SEL", 42000)], [], NOW + timedelta(hours=16))
    assert len(pick_alerts(s5, state, cfg, NOW + timedelta(hours=16))) == 1
    # прошла неделя — напоминаем
    later = NOW + timedelta(days=8)
    s6 = evaluate(cfg, [offer("SEL", 42000)], [], later)
    assert len(pick_alerts(s6, state, cfg, later)) == 1


def test_messages_escape_html():
    cfg = load_config("config.yaml")
    sts = evaluate(cfg, [offer("SEL", 41000, airline="A&B <Air>", link="https://x.ru/?a=1&b=2")], [], NOW)
    msg = alert_message([s for s in sts if s.is_deal], "https://me.github.io/flight-tracker/")
    assert "A&amp;B &lt;Air&gt;" in msg and "a=1&amp;b=2" in msg and "Сеул" in msg
    dig = digest_message(sts, {"etihad": {"ok": False, "skipped": None}, "google_flights": {"ok": True, "skipped": "нет ключа"}})
    assert "Ошибки источников: Etihad" in dig and "Google Flights (нет ключа)" in dig


def test_full_run(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    store = Store(tmp_path / "data")
    results = [
        SourceResult("travelpayouts", offers=[offer("SEL", 39900, airline="CA", link="https://www.aviasales.ru/search/x")]),
        SourceResult("etihad", offers=[offer("TYO", 70000, source="etihad", airline="Etihad", currency_orig="EUR", price_orig=700)]),
        SourceResult("samokatus", ok=False, errors=["HTTP 403"]),
        SourceResult("google_flights", skipped="нет секрета SERPAPI_KEY"),
    ]
    sent = []
    monkeypatch.setattr("tracker.notify.Telegram.send", lambda self, text: sent.append(text) or True)
    monkeypatch.setattr("tracker.app.load_rates", lambda http, fb: __import__("tracker.fx", fromlist=["Rates"]).Rates(fb, "test"))
    latest = run(cfg, store, tmp_path / "public", use_browser=False, now=NOW, results=results,
                 env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    assert latest["sent"] == ["alert:SEL"]
    assert "39" in sent[0] and "Сеул" in sent[0]
    assert (tmp_path / "data" / "history.json").exists()
    data = json.loads((tmp_path / "public" / "data.json").read_text())
    assert data["history"]["SEL"][0][1] == 39900
    assert (tmp_path / "public" / "index.html").exists() and (tmp_path / "public" / "app.js").exists()

    # второй запуск с той же ценой — без повторного уведомления
    latest2 = run(cfg, store, tmp_path / "public", use_browser=False, now=NOW + timedelta(hours=4), results=results,
                  env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    assert latest2["sent"] == []
    assert len(store.history()) == 2

    # понедельник — еженедельная сводка, один раз за день
    monday = datetime(2026, 11, 23, 4, 17, tzinfo=timezone.utc)
    latest3 = run(cfg, store, None, use_browser=False, now=monday, results=results, env={})
    assert "digest" in latest3["sent"]
    latest4 = run(cfg, store, None, use_browser=False, now=monday + timedelta(hours=4), results=results, env={})
    assert "digest" not in latest4["sent"]


def test_health_warning(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    store = Store(tmp_path / "data")
    monkeypatch.setattr("tracker.app.load_rates", lambda http, fb: __import__("tracker.fx", fromlist=["Rates"]).Rates(fb, "test"))
    bad = [SourceResult("travelpayouts", ok=False, errors=["timeout"]), SourceResult("etihad", ok=False, errors=["403"])]
    sent_kinds = []
    for i in range(4):
        latest = run(cfg, store, None, use_browser=False, now=NOW + timedelta(hours=4 * i), results=bad, env={})
        sent_kinds.append(latest["sent"])
    assert sent_kinds == [[], [], ["health"], []]


def test_telegram_many_recipients(monkeypatch):
    import httpx

    from tracker.notify import Telegram

    sent = []

    def fake_post(url, json, timeout):
        sent.append(json["chat_id"])
        code = 403 if json["chat_id"] == "222" else 200   # второй не нажал Start
        return httpx.Response(code, text="{}")

    monkeypatch.setattr("tracker.notify.httpx.post", fake_post)
    tg = Telegram("token", " 111, 222 ;-100333 ")
    assert tg.chat_ids == ["111", "222", "-100333"]
    assert tg.send("привет") is True
    assert sent == ["111", "222", "-100333"]
    assert Telegram("token", "").configured is False
