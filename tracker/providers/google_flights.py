"""Google Flights через SerpAPI: тарифы почти всех авиакомпаний, включая продажи напрямую.

Один поиск = одна пара дат, поэтому даты перебираются по кругу между запусками.
Документация: https://serpapi.com/google-flights-api
"""
from __future__ import annotations

from datetime import date, timedelta

from ..models import Offer, SourceResult
from .base import Provider

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


def parse_response(body: dict, route_id: str, dep: date, ret: date, passengers: int = 1) -> list[Offer]:
    """Google отдаёт цену за всех пассажиров — переводим в цену с человека."""
    n = max(1, passengers)
    flights = (body.get("best_flights") or []) + (body.get("other_flights") or [])
    insights = body.get("price_insights") or {}
    typical = insights.get("typical_price_range")
    url = (body.get("search_metadata") or {}).get("google_flights_url")
    offers = []
    for f in flights:
        price = f.get("price")
        if not isinstance(price, (int, float)):
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
        if not self.ctx.env.get("SERPAPI_KEY"):
            return "нет секрета SERPAPI_KEY"
        return None

    def collect(self, res: SourceResult) -> None:
        cfg = self.ctx.cfg
        plan = date_plan(cfg, self.opts.get("trip_days") or [10, 14], int(self.opts.get("every_days", 7)))
        if not plan:
            res.errors.append("пустой план дат — проверь window и trip_days")
            return
        st = self.ctx.state.setdefault("google_flights", {})
        cursor = int(st.get("cursor", 0)) % len(plan)
        n = int(self.opts.get("searches_per_run", 1))
        for i in range(min(n, len(plan))):
            route_id, dep, ret = plan[(cursor + i) % len(plan)]
            route = cfg.route(route_id)
            params = {
                "engine": "google_flights",
                "departure_id": ",".join(cfg.origin_airports),
                "arrival_id": ",".join(route.airports),
                "outbound_date": dep.isoformat(),
                "return_date": ret.isoformat(),
                "type": 1,
                "currency": "RUB",
                "hl": "ru",
                "adults": cfg.passengers,
                "api_key": self.ctx.env["SERPAPI_KEY"],
            }
            try:
                r = self.ctx.http.get(API, params=params, timeout=90)
                body = r.json()
            except Exception as e:  # noqa: BLE001
                res.errors.append(f"{route_id} {dep}: {e}")
                continue
            err = body.get("error") or (body.get("search_metadata") or {}).get("error")
            if err and not (body.get("best_flights") or body.get("other_flights")):
                # «Google hasn't returned any results» — не ошибка, просто нет рейсов
                if "returned any results" not in str(err):
                    res.errors.append(f"{route_id} {dep}: {err}")
                continue
            res.offers.extend(parse_response(body, route_id, dep, ret, cfg.passengers))
        st["cursor"] = (cursor + n) % len(plan)
        st["plan_size"] = len(plan)
