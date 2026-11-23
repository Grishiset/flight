from datetime import date, timedelta
from types import SimpleNamespace

import httpx
from fli.models import Airport, TripType

from tracker.config import load_config
from tracker.fx import Rates
from tracker.providers.base import Context
from tracker.providers.google_flights import GoogleFlightsProvider


def test_direct_prices_full_round_trip_without_key(monkeypatch):
    cfg = load_config("config.yaml")
    cfg.window.start = date.today() + timedelta(days=30)
    cfg.window.end = cfg.window.start + timedelta(days=90)
    ctx = Context(cfg, None, Rates({"USD": 90}, "test"), {}, env={})
    seen = []

    def search(self, filters, **options):
        assert filters.trip_type == TripType.ROUND_TRIP
        assert filters.passenger_info.adults == 3 and options["currency"] == "RUB"
        first, second = filters.flight_segments
        assert first.departure_airport == second.arrival_airport
        assert first.arrival_airport == second.departure_airport
        seen.append((first.travel_date, second.travel_date))
        leg = SimpleNamespace(departure_airport=Airport.SVO, arrival_airport=Airport.ICN)
        outbound = SimpleNamespace(price=1500, legs=[leg], stops=0, primary_airline_name="Туда")
        unavailable = SimpleNamespace(price=None, currency="USD", legs=[leg], stops=1, primary_airline_name="Обратно")
        inbound = SimpleNamespace(price=1800.01, currency="USD", legs=[leg], stops=1, primary_airline_name="Обратно")
        return [outbound, (outbound, unavailable), (outbound, inbound)]

    def booking_url(self, pair, *, passenger_info, **locale):
        assert passenger_info.adults == 3
        return "https://www.google.com/travel/flights/booking?tfs=test"

    monkeypatch.setattr("fli.search.SearchFlights.search", search)
    monkeypatch.setattr("fli.search.SearchFlights.build_flight_booking_url", booking_url)
    res = GoogleFlightsProvider(ctx).run()
    assert res.ok and not res.skipped and not res.errors
    assert len(res.offers) == len(cfg.routes) * cfg.sources["google_flights"]["dates_per_route"]
    assert {o.route_id for o in res.offers} == {r.id for r in cfg.routes}
    assert {o.quoted_passengers for o in res.offers} == {3}
    assert {o.total_price_rub for o in res.offers} == {162001}
    assert {o.price_rub for o in res.offers} == {54000}
    assert all(o.stops == 1 for o in res.offers)
    first_dates = set(seen)
    first_checked = seen[0]
    seen.clear()
    GoogleFlightsProvider(ctx).run()
    assert first_dates & set(seen) == {first_checked}
    assert len(set(seen) - first_dates) == cfg.sources["google_flights"]["dates_per_route"]


def test_serpapi_prices_only_after_selecting_return():
    cfg = load_config("config.yaml")
    cfg.window.start = date.today() + timedelta(days=30)
    cfg.window.end = cfg.window.start + timedelta(days=90)
    cfg.sources["google_flights"]["backend"] = "serpapi"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        calls.append(params)
        assert params["adults"] == "3" and params["no_cache"] == "true"
        flight = {"flights": [{"airline": "Etihad"}], "price": 180001}
        if "departure_token" not in params:
            flight.update(price=150000, departure_token="outbound")
        return httpx.Response(200, json={"best_flights": [flight]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        ctx = Context(cfg, http, Rates({}, "test"), {}, env={"SERPAPI_KEY": "test"})
        res = GoogleFlightsProvider(ctx).run()
    assert len(calls) == 2 and calls[1]["departure_token"] == "outbound"
    assert [o.total_price_rub for o in res.offers] == [180001]
    assert [o.quoted_passengers for o in res.offers] == [3]
