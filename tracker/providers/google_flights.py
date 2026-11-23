"""Поиск Google Flights на заданное число взрослых, напрямую или через SerpApi."""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite

from ..models import Offer, SourceResult
from .base import Provider
from .google_direct import GoogleDirect

API = "https://serpapi.com/search.json"


def date_plan(cfg, trip_days: list[int], every_days: int) -> list[tuple[str, date, date]]:
    """Все комбинации (направление, вылет, возврат), которые трекер проверяет по очереди."""
    plan = []
    dep = cfg.window.start
    while dep <= cfg.window.end:
        for length in trip_days:
            ret = dep + timedelta(days=int(length))
            if cfg.window.contains(dep, ret):
                for route in cfg.routes:
                    plan.append((route.id, dep, ret))
        dep += timedelta(days=max(1, int(every_days)))
    # Перемешиваем по направлениям, чтобы каждое проверялось равномерно
    plan.sort(key=lambda x: (x[1], x[2], x[0]))
    return plan


def flight_rows(body: dict) -> list[dict]:
    return (body.get("best_flights") or []) + (body.get("other_flights") or [])


def parse_response(body: dict, route_id: str, dep: date, ret: date, passengers: int = 1) -> list[Offer]:
    """Google отдаёт цену за всех пассажиров — переводим в цену с человека."""
    n = max(1, passengers)
    flights = flight_rows(body)
    insights = body.get("price_insights") or {}
    typical = insights.get("typical_price_range")
    url = (body.get("search_metadata") or {}).get("google_flights_url")
    offers = []
    for f in flights:
        price = f.get("price")
        if type(price) not in (int, float) or not isfinite(price) or price <= 0:
            continue
        legs = f.get("flights") or []
        airlines = []
        for leg in legs:
            a = leg.get("airline")
            if a and a not in airlines:
                airlines.append(a)
        first = legs[0] if legs else {}
        last = legs[-1] if legs else {}
        offers.append(
            Offer(
                quoted_passengers=n,
                total_price_rub=round(price),
                route_id=route_id,
                source="google_flights",
                price_rub=int(round(price / n)),
                depart=dep,
                ret=ret,
                airline=", ".join(airlines) or None,
                stops=len(f.get("layovers") or []),
                origin=(first.get("departure_airport") or {}).get("id"),
                destination=(last.get("arrival_airport") or {}).get("id"),
                link=url,
                price_orig=price,
                currency_orig="RUB",
                typical_range=[int(round(x / n)) for x in typical] if typical else None,
                note=f"Google: цена {insights.get('price_level')}" if insights.get("price_level") else None,
            )
        )
    return offers


class GoogleFlightsProvider(Provider):
    name = "google_flights"
    title = "Google Flights"

    def enabled(self) -> str | None:
        reason = super().enabled()
        if reason:
            return reason
        if self.opts.get("backend", "direct") == "serpapi" and not self.ctx.env.get("SERPAPI_KEY"):
            return "нет секрета SERPAPI_KEY"
        return None

    def collect(self, res: SourceResult) -> None:
        cfg = self.ctx.cfg
        plan = date_plan(cfg, self.opts.get("trip_days") or [10, 14], int(self.opts.get("every_days", 7)))
        today = date.today()
        plan = [(rid, dep, ret) for rid, dep, ret in plan if dep >= today]
        if not plan:
            if cfg.window.end >= today:
                res.errors.append("пустой план дат — проверь window и trip_days")
            return
        state = self.ctx.state.setdefault(self.name, {})
        backend = self.opts.get("backend", "direct")
        if backend == "direct":
            direct = GoogleDirect(self.ctx)
            dates = list(dict.fromkeys((dep, ret) for _, dep, ret in plan))
            cursor = int(state.get("direct_cursor", 0)) % len(dates)
            count = min(max(1, int(self.opts.get("dates_per_route", 2))), len(dates))
            # За один запуск проверяем все направления на датах из разных частей окна.
            batch = [dates[(cursor + i * len(dates) // count) % len(dates)] for i in range(count)]
            valid_dates = {(dep.isoformat(), ret.isoformat()): (dep, ret) for dep, ret in dates}
            previous = state.get("direct_last_dates", {}) if state.get("direct_passengers") == cfg.passengers else {}
            last_dates = {}
            for route in cfg.routes:
                last = valid_dates.get(tuple(previous.get(route.id, ())))
                pairs = [last, *batch] if last and last not in batch else batch
                start = len(res.offers)
                for dep, ret in pairs:
                    self.search_date(res, direct.offers, route.id, dep, ret)
                best = min(res.offers[start:], key=lambda o: o.price_rub, default=None)
                if best:
                    last = (best.depart, best.ret)
                if last:
                    last_dates[route.id] = [d.isoformat() for d in last]
            state["direct_passengers"] = cfg.passengers
            state["direct_last_dates"] = last_dates
            state["direct_cursor"] = (cursor + 1) % len(dates)
        elif backend == "serpapi":
            cursor = int(state.get("cursor", 0)) % len(plan)
            count = min(max(1, int(self.opts.get("searches_per_run", 1))), len(plan))
            for i in range(count):
                self.search_date(res, self.serpapi_offers, *plan[(cursor + i) % len(plan)])
            state["cursor"] = (cursor + count) % len(plan)
        else:
            res.errors.append(f"неизвестный backend Google Flights: {backend}")

    @staticmethod
    def search_date(res, search, route_id, dep, ret) -> None:
        try:
            res.offers.extend(search(route_id, dep, ret))
        except Exception as e:  # noqa: BLE001 — продолжаем с другими датами и направлениями
            res.errors.append(f"{route_id} {dep} → {ret}: {e}")

    def serpapi_offers(self, route_id: str, dep: date, ret: date) -> list[Offer]:
        cfg = self.ctx.cfg
        params = {
            "engine": "google_flights",
            "departure_id": ",".join(cfg.origin_airports),
            "arrival_id": ",".join(cfg.route(route_id).airports),
            "outbound_date": dep.isoformat(),
            "return_date": ret.isoformat(),
            "type": 1,
            "currency": "RUB",
            "hl": "ru",
            "adults": cfg.passengers,
            "no_cache": "true",
            "api_key": self.ctx.env["SERPAPI_KEY"],
        }
        outgoing = self.serpapi_search(params)
        start = min((f for f in flight_rows(outgoing) if f.get("departure_token") and f.get("flights")),
                    key=lambda f: f.get("price") or float("inf"), default=None)
        if not start:
            return []
        returning = self.serpapi_search({**params, "departure_token": start["departure_token"]})
        offers = []
        for end in flight_rows(returning):
            if not end.get("flights"):
                continue
            # Цена из списка обратных рейсов уже включает выбранный рейс туда.
            body = {
                "best_flights": [{**start, "price": end.get("price")}],
                "price_insights": outgoing.get("price_insights"),
            }
            for offer in parse_response(body, route_id, dep, ret, cfg.passengers):
                names = dict.fromkeys(leg["airline"] for leg in start["flights"] + end["flights"] if leg.get("airline"))
                offer.airline = ", ".join(names) or None
                offer.stops = max(offer.stops or 0, len(end["flights"]) - 1)
                offers.append(offer)
        return offers

    def serpapi_search(self, params: dict) -> dict:
        r = self.ctx.http.get(API, params=params, timeout=45)
        r.raise_for_status()
        body = r.json()
        error = body.get("error") or (body.get("search_metadata") or {}).get("error")
        if error and not flight_rows(body) and "returned any results" not in str(error):
            raise ValueError(error)
        return body
