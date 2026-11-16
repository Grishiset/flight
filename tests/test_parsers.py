from datetime import date

from tracker.providers.etihad import html_to_text, parse_cards as etihad_cards
from tracker.providers.google_flights import date_plan, parse_response
from tracker.providers.samokatus import parse_cards as samokatus_cards
from tracker.providers.travelpayouts import month_pairs, parse_items
from tracker.ru_dates import parse_ru_date

ETIHAD_HTML = """
<html><body><div class="card">
<span>Москва (SVO)</span><span>к</span>
<span>Токио (NRT)</span>
<span>25 нояб. 2026 - 10 дек. 2026</span>
<span>Туда - обратно</span><span>/</span><span>Экономкласс</span>
<span>От</span><span>EUR671*</span>
<span>Просмотрено: 3 ч. назад</span><a>Забронировать</a>
</div>
<div class="card">
Москва (SVO)к
Токио (NRT)
22 июн. 2027 - 6 июл. 2027
Туда - обратно
/
Экономкласс
От
EUR1,293*
Просмотрено: 5 ч. назад
</div>
<div class="card">
Казань (KZN)к
Токио (NRT)
22 июн. 2027 - 6 июл. 2027
Туда - обратно
/
Экономкласс
От
EUR500*
</div>
<div class="card">
Москва (SVO)к
Токио (NRT)
22 июн. 2027 - 6 июл. 2027
Туда - обратно
/
Экономкласс
От
EUR1,293*
</div>
<script>var x = "Москва (SVO) Токио (NRT) 1 мая 2027 - 2 мая 2027 Туда - обратно От EUR1";</script>
</body></html>
"""

SAMOKATUS_TEXT = """
Текущие цены (200)
Air China, 7 сен — 15 сен
45 139 ₽
одна пересадка
China Eastern Airlines, 24 июл — 7 авг
38 357 ₽
одна пересадка
13 ноя — 21 ноя
63 281 ₽
две пересадки
Sichuan Airlines, 15 дек — 23 янв
82 431 ₽
одна пересадка
"""


def test_ru_dates():
    assert parse_ru_date("25 нояб. 2026") == date(2026, 11, 25)
    assert parse_ru_date("1 июня 2027") == date(2027, 6, 1)
    assert parse_ru_date("7 сент. 2027") == date(2027, 9, 7)
    assert parse_ru_date("3 мая 2027") == date(2027, 5, 3)
    # без года — ближайшая будущая дата
    assert parse_ru_date("7 сен", today=date(2026, 11, 16)) == date(2027, 9, 7)
    assert parse_ru_date("20 ноя", today=date(2026, 11, 16)) == date(2026, 11, 20)
    # возврат после вылета через Новый год
    assert parse_ru_date("23 янв", after=date(2026, 12, 15)) == date(2027, 1, 23)
    assert parse_ru_date("бла-бла") is None


def test_etihad_cards():
    cards = etihad_cards(html_to_text(ETIHAD_HTML))
    keys = {(c["origin"], c["depart"], c["amount"]) for c in cards}
    assert ("SVO", date(2026, 11, 25), 671.0) in keys
    assert ("SVO", date(2027, 6, 22), 1293.0) in keys
    assert ("KZN", date(2027, 6, 22), 500.0) in keys
    # дубликат карточки и текст из <script> не учитываются
    assert len(cards) == 3
    summer = [c for c in cards if c["origin"] == "SVO" and c["depart"].year == 2027][0]
    assert summer["ret"] == date(2027, 7, 6)
    assert summer["currency"] == "EUR"
    assert summer["cabin"] == "economy"


def test_samokatus_cards():
    cards = samokatus_cards(SAMOKATUS_TEXT, today=date(2026, 11, 16))
    assert len(cards) == 4
    first = cards[0]
    assert first == {"airline": "Air China", "depart": date(2027, 9, 7), "ret": date(2027, 9, 15),
                     "price": 45139, "stops": 1}
    summer = [c for c in cards if c["depart"].month == 7][0]
    assert summer["price"] == 38357 and summer["airline"] == "China Eastern Airlines"
    assert summer["ret"] == date(2027, 8, 7)
    no_air = [c for c in cards if c["price"] == 63281][0]
    assert no_air["airline"] is None and no_air["stops"] == 2
    assert no_air["depart"] == date(2027, 11, 13)   # 13 ноября уже прошло → следующий год
    over_ny = [c for c in cards if c["price"] == 82431][0]
    assert over_ny["depart"] == date(2026, 12, 15) and over_ny["ret"] == date(2027, 1, 23)


def test_travelpayouts():
    assert month_pairs(date(2027, 6, 1), date(2027, 8, 31)) == [
        ("2027-06", "2027-06"), ("2027-06", "2027-07"), ("2027-06", "2027-08"),
        ("2027-07", "2027-07"), ("2027-07", "2027-08"), ("2027-08", "2027-08"),
    ]
    items = [
        {"origin": "MOW", "destination": "SEL", "origin_airport": "SVO", "destination_airport": "ICN",
         "price": 39873, "airline": "CA", "flight_number": "910", "departure_at": "2027-07-23T01:30:00+03:00",
         "return_at": "2027-08-06T12:00:00+09:00", "transfers": 1, "return_transfers": 2, "duration": 1600,
         "link": "/search/MOW2307SEL06081?t=CA"},
        {"origin": "MOW", "destination": "SEL", "price": 30000, "departure_at": "2027-07-01T01:30:00+03:00"},  # без return_at
        {"bad": True},
    ]
    offers = parse_items(items, "SEL")
    assert len(offers) == 1
    o = offers[0]
    assert o.price_rub == 39873 and o.stops == 2 and o.depart == date(2027, 7, 23) and o.ret == date(2027, 8, 6)
    assert o.link.startswith("https://www.aviasales.ru/search/MOW2307SEL06081")


def test_google_flights():
    body = {
        "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?x"},
        "best_flights": [{
            "price": 61234,
            "flights": [
                {"airline": "Etihad", "departure_airport": {"id": "SVO"}, "arrival_airport": {"id": "AUH"}},
                {"airline": "Etihad", "departure_airport": {"id": "AUH"}, "arrival_airport": {"id": "JFK"}},
            ],
            "layovers": [{"id": "AUH"}],
        }],
        "other_flights": [{"price": 70000, "flights": [{"airline": "Turkish Airlines"}], "layovers": [{}, {}]}],
        "price_insights": {"lowest_price": 61234, "price_level": "low", "typical_price_range": [65000, 90000]},
    }
    offers = parse_response(body, "NYC", date(2027, 6, 10), date(2027, 6, 24))
    assert [o.price_rub for o in offers] == [61234, 70000]
    assert offers[0].airline == "Etihad" and offers[0].stops == 1
    assert offers[0].origin == "SVO" and offers[0].destination == "JFK"
    assert offers[0].typical_range == [65000, 90000]


def test_date_plan():
    from tracker.config import load_config
    cfg = load_config("config.yaml")
    plan = date_plan(cfg, [10, 14], 7)
    assert plan
    for rid, dep, ret in plan:
        assert cfg.window.contains(dep, ret)
    assert {p[0] for p in plan} == {r.id for r in cfg.routes}


def test_etihad_stops_when_refused():
    import httpx

    from tracker.config import load_config
    from tracker.fx import Rates
    from tracker.models import SourceResult
    from tracker.providers.base import Context
    from tracker.providers.etihad import EtihadProvider

    calls = []

    def handler(request):
        calls.append(str(request.url))
        raise httpx.ReadTimeout("The read operation timed out")

    cfg = load_config("config.yaml")
    cfg.sources["etihad"]["enabled"] = True
    ctx = Context(cfg=cfg, http=httpx.Client(transport=httpx.MockTransport(handler)),
                  rates=Rates({"EUR": 100}, "test"), state={}, browser=None, env={})
    res = EtihadProvider(ctx).run()
    assert isinstance(res, SourceResult)
    assert len(calls) == 1                       # после первого отказа остальные страницы не трогаем
    assert len(res.errors) == 1 and "Google Flights" in res.errors[0]
