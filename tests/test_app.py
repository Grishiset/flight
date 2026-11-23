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
    assert "Ошибки: Etihad" in dig and "Google Flights (нет ключа)" in dig
    assert "Варианты: Aviasales 41" in dig


def test_full_run(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    cfg.passengers = 1
    cfg.alerts["digest_days"] = None   # отчёт проверяется отдельно
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

    # по кнопке — в любой момент
    forced = run(cfg, store, None, use_browser=False, now=NOW + timedelta(days=1), results=results,
                 env={"FORCE_REPORT": "1"})
    assert "digest" in forced["sent"]


def test_daily_report_at_900(tmp_path, monkeypatch):
    from tracker.app import MSK, report_due
    cfg = load_config("config.yaml")
    assert cfg.alerts["digest_days"] == "daily" and cfg.alerts["digest_time_msk"] == "09:00"
    at = lambda h, m, day=18: datetime(2026, 11, day, h, m, tzinfo=MSK)  # noqa: E731
    assert not report_due(cfg.alerts, at(8, 59))
    assert report_due(cfg.alerts, at(9, 0)) and report_due(cfg.alerts, at(11, 17))
    assert not report_due({"digest_days": [6], "digest_time_msk": "18:00"}, at(19, 0, day=18))   # среда
    assert report_due({"digest_days": [6], "digest_time_msk": "18:00"}, at(19, 0, day=22))       # воскресенье
    assert not report_due({"digest_days": None}, at(12, 0))

    store = Store(tmp_path / "data")
    monkeypatch.setattr("tracker.app.load_rates", lambda http, fb: __import__("tracker.fx", fromlist=["Rates"]).Rates(fb, "test"))
    results = [SourceResult("travelpayouts", offers=[offer("TYO", 60000)])]
    monkeypatch.setattr("tracker.notify.Telegram.send", lambda self, text: True)
    kinds = []
    for h, m in [(7, 17), (9, 1), (11, 17), (15, 17)]:          # МСК 18 ноября, затем утро 19-го
        kinds.append("digest" in run(cfg, store, None, use_browser=False, now=at(h, m), results=results, env={})["sent"])
    kinds.append("digest" in run(cfg, store, None, use_browser=False, now=at(9, 40, day=19), results=results, env={})["sent"])
    assert kinds == [False, True, False, False, True]


def test_report_dynamics():
    from tracker.notify import digest_message
    cfg = load_config("config.yaml")
    hist = [
        {"at": (NOW - timedelta(days=10)).isoformat(), "routes": {"SEL": {"best": 50000}}},
        {"at": (NOW - timedelta(days=3)).isoformat(), "routes": {"SEL": {"best": 45000}}},
    ]
    sts = evaluate(cfg, [offer("SEL", 46000, airline="CA"), offer("SEL", 47000, source="self_transfer", via="Ташкент")], hist, NOW)
    msg = digest_message(sts, {}, None, history=hist, now=NOW)
    assert "Отчёт по летним билетам" in msg
    assert "минимум за неделю 45" in msg
    assert "Свои пересадки через Ташкент 47" in msg
    hist.append({"at": (NOW - timedelta(hours=30)).isoformat(), "routes": {"SEL": {"best": 50000}}})
    msg3 = digest_message(sts, {}, None, history=hist, now=NOW, passengers=3)
    assert "сутки назад 50" in msg3 and "−8%" in msg3          # 46 000 против 50 000
    assert "Сеул: 138\u202f000\u00a0₽" in msg3                   # 46 000 × 3
    assert "3 взрослых" in msg3
    assert "Нью-Йорк</b>: нет свежей цены на всю группу" in msg


def test_health_warning(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    cfg.alerts["digest_days"] = None
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


def test_passengers_everywhere():
    from tracker.notify import alert_message
    from tracker.providers.google_flights import parse_response
    cfg = load_config("config.yaml")
    assert cfg.passengers == 3
    sts = evaluate(cfg, [offer("SEL", 41000)], [], NOW)
    msg = alert_message([s for s in sts if s.is_deal], None, passengers=3)
    assert "123\u202f000\u00a0₽ на троих (41\u202f000\u00a0₽ с человека)" in msg
    body = {"other_flights": [{"price": 150001, "flights": [{"airline": "Etihad"}], "layovers": []}],
            "price_insights": {"typical_price_range": [180000, 240000]}}
    o = parse_response(body, "NYC", date(2027, 6, 1), date(2027, 6, 15), passengers=3)[0]
    from tracker.notify import group_price
    assert group_price(o, 3) == 150001
    assert o.price_rub == 50000 and o.typical_range == [60000, 80000]


def test_buy_links():
    from tracker.notify import buy_links, digest_message
    o = offer("SEL", 52955, airline="China Southern", link="https://www.aviasales.ru/search/MOW0406SEL11063",
              origin="SVO", destination="ICN")
    links = buy_links(o, 3)
    assert "Aviasales (на 3)" in links
    assert 'href="https://www.csair.com/ru/ru/"' in links and "сайт China Southern" in links
    assert "travel/flights" in links and "for%203%20adults" in links and "Google Flights (на 3)" in links
    # маршрут из отдельных билетов: сайты всех авиакомпаний, без общей ссылки Google
    st = offer("NYC", 75000, source="self_transfer", airline="Uzbekistan Airways / Turkish Airlines", legs=[{}])
    lk = buy_links(st, 3)
    assert "uzairways" in lk and "turkishairlines" in lk and "Google" not in lk
    cfg = load_config("config.yaml")
    msg = digest_message(evaluate(cfg, [o], [], NOW), {}, None, passengers=3)
    assert "csair.com" in msg and "Поиск на всю группу" in msg
    assert o.to_dict()["airline_sites"] == [{"name": "China Southern", "url": "https://www.csair.com/ru/ru/"}]


def test_failed_digest_retries(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    store = Store(tmp_path / "data")
    monkeypatch.setattr("tracker.app.load_rates", lambda http, fb: __import__("tracker.fx", fromlist=["Rates"]).Rates(fb, "test"))
    attempts = iter([False, True])
    monkeypatch.setattr("tracker.notify.Telegram.send", lambda self, text: next(attempts))
    for offset, expected in [(0, ["digest:not_delivered"]), (1, ["digest"]), (2, [])]:
        latest = run(cfg, store, None, use_browser=False, now=NOW + timedelta(hours=offset),
                     results=[], env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
        assert latest["sent"] == expected
        assert bool(store.state().get("last_digest")) == (offset > 0)


def test_telegram_chunks_preserve_html(monkeypatch):
    import httpx
    from tracker.notify import Telegram
    from html.parser import HTMLParser

    line = '<a href="https://example.com/?a=1&amp;b=2">Билет</a>\n'
    message = line * 100
    sent = []

    def fake_post(url, json, timeout):
        chunk = json["text"]
        assert len(chunk) <= 3900
        assert chunk.count("<a ") == chunk.count("</a>")
        assert chunk.endswith("</a>\n")
        HTMLParser().feed(chunk)
        sent.append(chunk)
        return httpx.Response(200, text="{}")

    monkeypatch.setattr("tracker.notify.httpx.post", fake_post)
    assert Telegram("token", "1").send(message)
    assert len(sent) > 1 and "".join(sent) == message


def test_digest_without_price_sources():
    cfg = load_config("config.yaml")
    msg = digest_message(evaluate(cfg, [], [], NOW), {}, now=NOW, passengers=3, cfg=cfg)
    assert "Открыть Google Flights" in msg
    assert msg.count("for%203%20adults") == len(cfg.routes)
    assert msg.count("нет свежей цены на всю группу") == len(cfg.routes)


def test_group_run_excludes_estimates_and_other_party_sizes(tmp_path, monkeypatch):
    cfg = load_config("config.yaml")
    store = Store(tmp_path / "data")
    store.save_history([{"at": (NOW - timedelta(days=1)).isoformat(), "routes": {"SEL": {"best": 20000}}}])
    monkeypatch.setattr("tracker.app.load_rates", lambda http, fb: __import__("tracker.fx", fromlist=["Rates"]).Rates(fb, "test"))
    sent = []
    monkeypatch.setattr("tracker.notify.Telegram.send", lambda self, text: sent.append(text) or True)
    results = [
        SourceResult("travelpayouts", offers=[offer("SEL", 32000)]),
        SourceResult("google_flights", offers=[
            offer("SEL", 35000, source="google_flights", quoted_passengers=2, total_price_rub=70000),
            offer("SEL", 36000, source="google_flights", quoted_passengers=3),
            offer("SEL", 50000, source="google_flights", quoted_passengers=3, total_price_rub=150001),
        ]),
    ]
    latest = run(cfg, store, tmp_path / "public", use_browser=False, now=NOW, results=results, env={})
    seoul = latest["routes"][0]
    assert [o["total_price_rub"] for o in seoul["top"]] == [150001]
    assert latest["sent"] == ["digest"]
    assert "150\u202f001\u00a0₽" in sent[0] and "минимум за неделю" not in sent[0]
    data = json.loads((tmp_path / "public" / "data.json").read_text())
    assert data["history"]["SEL"] == [[NOW.isoformat(), 50000]]
