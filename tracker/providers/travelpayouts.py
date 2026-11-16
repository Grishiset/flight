"""Aviasales через официальный Travelpayouts Data API (кэш цен, найденных пользователями Aviasales).

Документация: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
"""
from __future__ import annotations

import re
from datetime import date, datetime

from ..airlines import airline_name
from ..http import get
from ..models import Offer, SourceResult
from .base import Provider

API = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def month_pairs(start: date, end: date) -> list[tuple[str, str]]:
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # Aviasales отвечает 400, если месяц возврата дальше следующего за месяцем вылета
    return [(a, b) for i, a in enumerate(months) for b in months[i:i + 2]]


_SEARCH_RE = re.compile(r"(/search/[A-Z]{3}\d{4}[A-Z]{3}(?:\d{4})?)\d(?=[?#]|$)")


def aviasales_link(link: str | None, passengers: int = 1) -> str | None:
    """Ссылка на поиск Aviasales с нужным числом взрослых.

    Формат пути: /search/MOW2307SEL06081 — последняя цифра = взрослых (здесь 1).
    """
    if not link:
        return None
    if link.startswith("/"):
        link = "https://www.aviasales.ru" + link
    return _SEARCH_RE.sub(lambda m: m.group(1) + str(min(9, max(1, passengers))), link, count=1)


def parse_items(items: list[dict], route_id: str, passengers: int = 1) -> list[Offer]:
    offers = []
    for it in items or []:
        try:
            dep = datetime.fromisoformat(it["departure_at"]).date()
            ret_raw = it.get("return_at")
            if not ret_raw:
                continue
            ret = datetime.fromisoformat(ret_raw).date()
            price = int(it["price"])
        except (KeyError, TypeError, ValueError):
            continue
        link = it.get("link")
        offers.append(
            Offer(
                route_id=route_id,
                source="travelpayouts",
                price_rub=price,
                depart=dep,
                ret=ret,
                airline=airline_name(it.get("airline")),
                stops=max(int(it.get("transfers") or 0), int(it.get("return_transfers") or 0)),
                origin=it.get("origin_airport") or it.get("origin"),
                destination=it.get("destination_airport") or it.get("destination"),
                link=aviasales_link(link, passengers),
                price_orig=price,
                currency_orig="RUB",
            )
        )
    return offers


def route_dests(route) -> list[str]:
    """Коды назначения для Aviasales.

    У Токио/Сеула/Нью-Йорка есть общий код города — его достаточно. Если код города
    совпадает с аэропортом (LAX, AKL в списке НЗ) — опрашиваем каждый аэропорт.
    """
    return list(route.airports) if route.city in route.airports else [route.city]


class TokenError(RuntimeError):
    pass


def tp_request(http, token: str, params: dict) -> list[dict]:
    """Один запрос prices_for_dates. Возвращает список предложений или бросает исключение."""
    r = get(http, API, params=params, headers={"X-Access-Token": token})
    if r.status_code == 401:
        raise TokenError("Travelpayouts: неверный токен (401)")
    r.raise_for_status()
    body = r.json()
    if not body.get("success", True):
        raise RuntimeError(str(body.get("error")))
    return body.get("data") or []


class TravelpayoutsProvider(Provider):
    name = "travelpayouts"
    title = "Aviasales"

    def enabled(self) -> str | None:
        reason = super().enabled()
        if reason:
            return reason
        if not self.ctx.env.get("TRAVELPAYOUTS_TOKEN"):
            return "нет секрета TRAVELPAYOUTS_TOKEN"
        return None

    def collect(self, res: SourceResult) -> None:
        cfg = self.ctx.cfg
        token = self.ctx.env["TRAVELPAYOUTS_TOKEN"]
        pairs = month_pairs(cfg.window.start, cfg.window.end)
        for route in cfg.routes:
            dests = route_dests(route)
            for dest in dests:
                for dep_m, ret_m in pairs:
                    params = {
                        "origin": cfg.origin_city,
                        "destination": dest,
                        "departure_at": dep_m,
                        "return_at": ret_m,
                        "one_way": "false",
                        "currency": "rub",
                        "market": self.opts.get("market", "ru"),
                        "sorting": "price",
                        "limit": 1000,
                    }
                    try:
                        items = tp_request(self.ctx.http, token, params)
                    except TokenError as e:
                        res.errors.append(str(e))
                        return
                    except Exception as e:  # noqa: BLE001
                        res.errors.append(f"{route.id} {dest} {dep_m}/{ret_m}: {e}")
                        continue
                    res.offers.extend(parse_items(items, route.id, cfg.passengers))
