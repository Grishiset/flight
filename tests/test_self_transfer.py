from datetime import date

import httpx

from tracker.config import Window, load_config
from tracker.fx import Rates
from tracker.models import Offer
from tracker.notify import alert_message
from tracker.providers.base import Context
from tracker.providers.self_transfer import Rules, SelfTransferProvider, combine, parse_legs

W = Window(date(2027, 6, 1), date(2027, 8, 31), 5, 30)


def item(o, d, dep, minutes, price, airline="HY", oa=None, da=None):
    return {"origin": o, "destination": d, "origin_airport": oa or o, "destination_airport": da or d,
            "departure_at": dep, "duration_to": minutes, "price": price, "airline": airline,
            "transfers": 0, "link": f"/search/{o}{d}"}


# Москва → Ташкент (4 ч), Ташкент → Нью-Йорк (12 ч)
OUT1 = parse_legs([
    item("MOW", "TAS", "2027-07-01T09:00:00+03:00", 240, 9000, oa="SVO"),    # прилёт 15:00 TAS (+5)
    item("MOW", "TAS", "2027-07-01T20:00:00+03:00", 240, 6000, oa="SVO"),    # прилёт 02:00 TAS следующего дня
    item("MOW", "TAS", "2027-06-29T09:00:00+03:00", 240, 5000, oa="SVO"),    # за 2 дня — стыковка > 30 ч
])
OUT2 = parse_legs([item("TAS", "NYC", "2027-07-02T08:00:00+05:00", 720, 30000, da="JFK")])
BACK2 = parse_legs([item("NYC", "TAS", "2027-07-15T22:00:00-04:00", 720, 31000, oa="JFK")])  # прилёт 19:00 TAS 16.07
BACK1 = parse_legs([
    item("TAS", "MOW", "2027-07-16T21:00:00+05:00", 240, 7000, da="SVO"),    # 2 ч — мало
    item("TAS", "MOW", "2027-07-17T07:00:00+05:00", 240, 6500, da="SVO"),    # 12 ч — с ночёвкой
    item("TAS", "MOW", "2027-07-17T01:00:00+05:00", 240, 8000, da="SVO"),    # 6 ч — без ночёвки
])


def test_parse_and_arrival():
    leg = OUT1[0]
    assert leg.arr.isoformat() == "2027-07-01T13:00:00+03:00"
    assert leg.airline == "Uzbekistan Airways"
    assert leg.link == "https://www.aviasales.ru/search/MOWTAS"


def test_connection_rules():
    r = Rules()
    ok, gap, extra, change = r.connection(OUT1[0], OUT2[0])   # 15:00 → 08:00 следующего дня = 17 ч
    assert ok and round(gap) == 17 and extra == 4000 and not change
    ok, gap, extra, _ = r.connection(OUT1[1], OUT2[0])        # 02:00 → 08:00 = 6 ч
    assert ok and round(gap) == 6 and extra == 0
    ok, *_ = r.connection(OUT1[2], OUT2[0])                   # 65 ч — слишком долго
    assert not ok
    ok, *_ = r.connection(BACK2[0], BACK1[0])                 # 2 ч — мало
    assert not ok


def test_airport_change_needs_more_time():
    r = Rules()
    a = parse_legs([item("MOW", "IST", "2027-07-01T09:00:00+03:00", 240, 1, da="IST")])[0]
    b = parse_legs([item("IST", "NYC", "2027-07-01T18:00:00+03:00", 600, 1, oa="SAW")])[0]   # 5 ч, другой аэропорт
    ok, _, _, change = r.connection(a, b)
    assert change and not ok   # нужно 4 + 3 = 7 ч


def test_combine_picks_cheapest_valid():
    offers = combine("NYC", "Ташкент", OUT1, OUT2, BACK2, BACK1, W, Rules(), keep=5)
    assert offers, "должна найтись хотя бы одна комбинация"
    best = offers[0]
    # туда: вечерний рейс 6000 + 30000 (стыковка 6 ч, без ночёвки)
    # обратно: 31000 + 01:00 за 8000 (6 ч) = 39000  дешевле, чем 31000 + 6500 + 4000 ночёвка = 41500
    assert best.price_rub == 6000 + 30000 + 31000 + 8000
    assert best.extra_rub == 0
    assert best.depart == date(2027, 7, 1) and best.ret == date(2027, 7, 17)
    assert best.via == "Ташкент" and best.source == "self_transfer"
    assert len(best.legs) == 4 and best.legs[1]["to"] == "JFK"
    assert "4 отдельных билета через Ташкент" in best.note
    assert best.stops == 1


def test_combine_respects_window():
    narrow = Window(date(2027, 7, 2), date(2027, 8, 31), 5, 30)   # вылет 1 июля уже вне окна
    assert combine("NYC", "Ташкент", OUT1, OUT2, BACK2, BACK1, narrow, Rules()) == []


def test_alert_shows_legs_and_direct_comparison():
    from datetime import datetime, timezone

    from tracker.analyze import evaluate
    cfg = load_config("config.yaml")
    st_offer = combine("NYC", "Ташкент", OUT1, OUT2, BACK2, BACK1, W, Rules())[0]
    direct = Offer("NYC", "travelpayouts", 80000, date(2027, 7, 1), date(2027, 7, 15), airline="Turkish Airlines")
    sts = evaluate(cfg, [st_offer, direct], [], datetime(2026, 11, 17, tzinfo=timezone.utc))
    nyc = [s for s in sts if s.route_id == "NYC"][0]
    assert nyc.best.source == "self_transfer"   # 75 000 через Ташкент дешевле 80 000 одним билетом
    nyc.reasons.append("тест")
    msg = alert_message([nyc])
    assert "через Ташкент" in msg
    assert msg.count("aviasales.ru/search/") == 4
    assert "одним билетом" in msg and "80" in msg


def test_provider_uses_cache_and_combines():
    calls = []

    def handler(request):
        p = dict(request.url.params)
        calls.append((p["origin"], p["destination"], p["departure_at"]))
        assert p["one_way"] == "true"
        data = []
        if p["departure_at"] == "2027-07":
            key = (p["origin"], p["destination"])
            src = {("MOW", "TAS"): OUT1, ("TAS", "NYC"): OUT2, ("NYC", "TAS"): BACK2, ("TAS", "MOW"): BACK1}
            for leg in src.get(key, []):
                data.append({"origin": leg.origin, "destination": leg.destination,
                             "origin_airport": leg.origin, "destination_airport": leg.destination,
                             "departure_at": leg.dep.isoformat(),
                             "duration_to": int((leg.arr - leg.dep).total_seconds() // 60),
                             "price": leg.price, "airline": "HY", "transfers": 0, "link": "/search/x"})
        return httpx.Response(200, json={"success": True, "data": data})

    cfg = load_config("config.yaml")
    cfg.sources["self_transfer"]["hubs"] = [{"code": "TAS", "name": "Ташкент"}]
    cfg.sources["self_transfer"]["pause_seconds"] = 0
    ctx = Context(cfg=cfg, http=httpx.Client(transport=httpx.MockTransport(handler)),
                  rates=Rates({}, "test"), state={}, browser=None, env={"TRAVELPAYOUTS_TOKEN": "x"})
    res = SelfTransferProvider(ctx).run()
    assert not res.errors
    nyc = [o for o in res.offers if o.route_id == "NYC"]
    assert nyc and nyc[0].price_rub == 75000
    # MOW⇄TAS запрошены один раз на месяц, несмотря на 5 направлений
    assert calls.count(("MOW", "TAS", "2027-07")) == 1


def test_provider_skipped_without_token():
    cfg = load_config("config.yaml")
    ctx = Context(cfg=cfg, http=httpx.Client(), rates=Rates({}, "t"), state={}, browser=None, env={})
    assert SelfTransferProvider(ctx).run().skipped
