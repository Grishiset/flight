"""Маршруты из отдельных билетов через хаб: Москва ⇄ Ташкент + Ташкент ⇄ Нью-Йорк и т. п.

Берём из Aviasales (Travelpayouts) календари самых дешёвых билетов в одну сторону
на каждый день для четырёх «ног»:

    Москва → хаб,   хаб → направление,   направление → хаб,   хаб → Москва

и складываем их, проверяя время на пересадку. Это самостоятельная пересадка:
билеты не связаны между собой, багаж нужно получать и сдавать заново, а за опоздание
на второй рейс авиакомпания не отвечает. Поэтому:
  • между прилётом и следующим вылетом не меньше min_connection_hours
    (+ airport_change_extra_hours, если прилёт и вылет из разных аэропортов);
  • если стыковка дольше overnight_after_hours — к цене добавляется overnight_cost_rub (ночёвка).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..airlines import airline_name
from ..config import Window
from ..models import Offer, SourceResult
from .base import Provider
from .travelpayouts import TokenError, month_pairs, route_dests, tp_request


@dataclass
class Leg:
    origin: str
    destination: str
    dep: datetime
    arr: datetime
    price: int
    airline: str | None
    transfers: int
    link: str | None

    def to_dict(self) -> dict:
        return {
            "from": self.origin,
            "to": self.destination,
            "dep": self.dep.isoformat(),
            "arr": self.arr.isoformat(),
            "price": self.price,
            "airline": self.airline,
            "transfers": self.transfers,
            "link": self.link,
        }


def parse_legs(items: list[dict]) -> list[Leg]:
    legs = []
    for it in items or []:
        try:
            dep = datetime.fromisoformat(it["departure_at"])
            price = int(it["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if dep.tzinfo is None:
            continue
        minutes = it.get("duration_to") or it.get("duration")
        # Нет длительности — считаем с запасом, чтобы не собрать невозможную стыковку
        arr = dep + timedelta(minutes=int(minutes)) if minutes else dep + timedelta(hours=14)
        link = it.get("link")
        legs.append(
            Leg(
                origin=it.get("origin_airport") or it.get("origin") or "",
                destination=it.get("destination_airport") or it.get("destination") or "",
                dep=dep,
                arr=arr,
                price=price,
                airline=airline_name(it.get("airline")),
                transfers=int(it.get("transfers") or 0),
                link=("https://www.aviasales.ru" + link) if link and link.startswith("/") else link,
            )
        )
    return legs


@dataclass
class Rules:
    min_connection_hours: float = 4
    airport_change_extra_hours: float = 3
    max_connection_hours: float = 30
    overnight_after_hours: float = 10
    overnight_cost_rub: int = 4000
    min_stay_days: int = 1

    @classmethod
    def from_opts(cls, o: dict) -> "Rules":
        r = cls()
        for k in r.__dataclass_fields__:
            if k in o and o[k] is not None:
                setattr(r, k, type(getattr(r, k))(o[k]))
        return r

    def connection(self, first: Leg, second: Leg) -> tuple[bool, float, int, bool]:
        """(можно ли, часов на стыковку, доплата за ночёвку, смена аэропорта)."""
        gap = (second.dep - first.arr).total_seconds() / 3600
        change = bool(first.destination and second.origin and first.destination != second.origin)
        need = self.min_connection_hours + (self.airport_change_extra_hours if change else 0)
        if gap < need or gap > self.max_connection_hours:
            return False, gap, 0, change
        extra = self.overnight_cost_rub if gap > self.overnight_after_hours else 0
        return True, gap, extra, change


@dataclass
class Half:
    """Половина маршрута: две ноги через хаб."""
    a: Leg
    b: Leg
    gap: float
    extra: int
    change: bool

    @property
    def cost(self) -> int:
        return self.a.price + self.b.price + self.extra


def best_halves(first: list[Leg], second: list[Leg], rules: Rules) -> list[Half]:
    """Для каждой второй ноги — самая дешёвая подходящая первая."""
    out = []
    for b in second:
        best: Half | None = None
        for a in first:
            ok, gap, extra, change = rules.connection(a, b)
            if not ok:
                continue
            h = Half(a, b, gap, extra, change)
            if best is None or h.cost < best.cost:
                best = h
        if best:
            out.append(best)
    return out


def combine(
    route_id: str,
    hub_name: str,
    out1: list[Leg], out2: list[Leg], back2: list[Leg], back1: list[Leg],
    window: Window, rules: Rules, keep: int = 5,
) -> list[Offer]:
    outs = best_halves(out1, out2, rules)
    ins = best_halves(back2, back1, rules)
    combos = []
    for o in outs:
        depart = o.a.dep.date()
        for i in ins:
            ret = i.b.dep.date()
            if not window.contains(depart, ret):
                continue
            # на месте нужно провести хотя бы min_stay_days
            if (i.a.dep - o.b.arr) < timedelta(days=rules.min_stay_days):
                continue
            combos.append((o.cost + i.cost, o, i))
    combos.sort(key=lambda x: x[0])
    offers: list[Offer] = []
    seen = set()
    for total, o, i in combos:
        k = (o.a.dep.date(), i.b.dep.date())
        if k in seen:
            continue
        seen.add(k)
        names = []
        for leg in (o.a, o.b, i.a, i.b):
            if leg.airline and leg.airline not in names:
                names.append(leg.airline)
        notes = [f"4 отдельных билета через {hub_name}",
                 f"стыковка туда {o.gap:.0f} ч, обратно {i.gap:.0f} ч"]
        if o.change or i.change:
            notes.append("со сменой аэропорта")
        extra = o.extra + i.extra
        if extra:
            notes.append(f"в цену заложена ночёвка {extra:,} ₽".replace(",", " "))
        notes.append("багаж — получать и сдавать заново")
        offers.append(
            Offer(
                route_id=route_id,
                source="self_transfer",
                price_rub=total,
                depart=o.a.dep.date(),
                ret=i.b.dep.date(),
                airline=" / ".join(names) or None,
                stops=max(o.a.transfers + o.b.transfers, i.a.transfers + i.b.transfers) + 1,
                origin=o.a.origin,
                destination=o.b.destination,
                link=o.a.link,
                price_orig=total - extra,
                currency_orig="RUB",
                note="; ".join(notes),
                via=hub_name,
                legs=[leg.to_dict() for leg in (o.a, o.b, i.a, i.b)],
                extra_rub=extra,
            )
        )
        if len(offers) >= keep:
            break
    return offers


class SelfTransferProvider(Provider):
    name = "self_transfer"
    title = "Свои пересадки"

    def enabled(self) -> str | None:
        reason = super().enabled()
        if reason:
            return reason
        if not self.ctx.env.get("TRAVELPAYOUTS_TOKEN"):
            return "нет секрета TRAVELPAYOUTS_TOKEN (данные берутся из Aviasales)"
        if not self.opts.get("hubs"):
            return "в config.yaml не указаны хабы"
        return None

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._cache: dict[tuple[str, str, str], list[Leg]] = {}
        self._calls = 0

    def one_way(self, origin: str, dest: str, res: SourceResult) -> list[Leg]:
        """Самые дешёвые билеты в одну сторону на каждый день окна (по месяцам)."""
        cfg = self.ctx.cfg
        legs: list[Leg] = []
        months = sorted({m for pair in month_pairs(cfg.window.start, cfg.window.end) for m in pair})
        for m in months:
            key = (origin, dest, m)
            if key not in self._cache:
                params = {
                    "origin": origin,
                    "destination": dest,
                    "departure_at": m,
                    "one_way": "true",
                    "currency": "rub",
                    "market": self.opts.get("market", "ru"),
                    "sorting": "price",
                    "limit": 1000,
                }
                if self._calls:
                    time.sleep(float(self.opts.get("pause_seconds", 0.2)))
                self._calls += 1
                try:
                    self._cache[key] = parse_legs(tp_request(self.ctx.http, self.ctx.env["TRAVELPAYOUTS_TOKEN"], params))
                except TokenError:
                    raise
                except Exception as e:  # noqa: BLE001
                    res.errors.append(f"{origin}→{dest} {m}: {e}")
                    self._cache[key] = []
            legs.extend(self._cache[key])
        return legs

    def collect(self, res: SourceResult) -> None:
        cfg = self.ctx.cfg
        rules = Rules.from_opts(self.opts)
        keep = int(self.opts.get("keep_per_hub", 5))
        home = cfg.origin_city
        try:
            for hub in self.opts["hubs"]:
                code, hub_name = str(hub["code"]), str(hub.get("name") or hub["code"])
                out1 = self.one_way(home, code, res)
                back1 = self.one_way(code, home, res)
                if not out1 or not back1:
                    continue
                for route in cfg.routes:
                    dests = [d for d in route_dests(route) if d != code]
                    if not dests or code in route.airports:
                        continue
                    out2 = [leg for d in dests for leg in self.one_way(code, d, res)]
                    back2 = [leg for d in dests for leg in self.one_way(d, code, res)]
                    if out2 and back2:
                        res.offers.extend(
                            combine(route.id, hub_name, out1, out2, back2, back1, cfg.window, rules, keep)
                        )
        except TokenError as e:
            res.errors.append(str(e))
