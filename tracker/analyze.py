"""Отбор летних билетов, «обычная» цена по истории и решение, о чём уведомлять."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Config
from .models import Offer


@dataclass
class RouteStatus:
    route_id: str
    name: str
    threshold: int
    best: Offer | None = None
    top: list[Offer] = field(default_factory=list)
    by_source: dict[str, Offer] = field(default_factory=dict)
    median: int | None = None
    median_points: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def is_deal(self) -> bool:
        return bool(self.reasons)

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "name": self.name,
            "threshold": self.threshold,
            "best": self.best.to_dict() if self.best else None,
            "top": [o.to_dict() for o in self.top],
            "by_source": {k: v.to_dict() for k, v in self.by_source.items()},
            "median": self.median,
            "median_points": self.median_points,
            "reasons": self.reasons,
            "is_deal": self.is_deal,
        }


def summer_only(offers: list[Offer], cfg: Config) -> list[Offer]:
    return [o for o in offers if o.price_rub > 0 and cfg.window.contains(o.depart, o.ret)]


def dedupe(offers: list[Offer]) -> list[Offer]:
    best: dict[str, Offer] = {}
    for o in offers:
        k = o.key()
        if k not in best or o.price_rub < best[k].price_rub:
            best[k] = o
    return list(best.values())


def history_median(history: list[dict], route_id: str, now: datetime, days: int) -> tuple[int | None, int]:
    since = now - timedelta(days=days)
    vals = []
    for run in history:
        try:
            at = datetime.fromisoformat(run["at"])
        except (KeyError, ValueError):
            continue
        if at < since or at >= now:
            continue
        best = ((run.get("routes") or {}).get(route_id) or {}).get("best")
        if isinstance(best, (int, float)):
            vals.append(best)
    if not vals:
        return None, 0
    return int(statistics.median(vals)), len(vals)


def evaluate(cfg: Config, offers: list[Offer], history: list[dict], now: datetime, top_n: int = 15) -> list[RouteStatus]:
    summer = dedupe(summer_only(offers, cfg))
    b = cfg.baseline
    drop = float(b.get("drop_pct", 15))
    out = []
    for route in cfg.routes:
        mine = sorted((o for o in summer if o.route_id == route.id), key=lambda o: (o.price_rub, o.depart))
        st = RouteStatus(route.id, route.name, route.threshold, top=mine[:top_n])
        st.best = mine[0] if mine else None
        for o in mine:
            st.by_source.setdefault(o.source, o)
        st.median, st.median_points = history_median(history, route.id, now, int(b.get("history_days", 30)))
        if st.best:
            p = st.best.price_rub
            if p <= route.threshold:
                st.reasons.append(f"дешевле порога {fmt_rub(route.threshold)}")
            if st.median and st.median_points >= int(b.get("min_points", 10)) and p <= st.median * (1 - drop / 100):
                pct = round((1 - p / st.median) * 100)
                st.reasons.append(f"на {pct}% ниже обычного (медиана за {b.get('history_days', 30)} дн. — {fmt_rub(st.median)})")
            g = st.by_source.get("google_flights")
            if g and g.typical_range and g.price_rub < g.typical_range[0]:
                st.reasons.append(
                    f"Google Flights: ниже обычного диапазона {fmt_rub(g.typical_range[0])}–{fmt_rub(g.typical_range[1])}"
                )
        out.append(st)
    return out


def pick_alerts(statuses: list[RouteStatus], state: dict, cfg: Config, now: datetime) -> list[RouteStatus]:
    """Какие направления стоит прислать сейчас (без повторов одного и того же)."""
    alerts_state: dict = state.setdefault("alerts", {})
    cheaper_by = int(cfg.alerts.get("repeat_if_cheaper_by", 1000))
    after_days = int(cfg.alerts.get("repeat_after_days", 7))
    send = []
    for st in statuses:
        prev = alerts_state.get(st.route_id)
        if not st.is_deal or not st.best:
            # Выгодной цены больше нет — при следующем падении снова уведомим
            alerts_state.pop(st.route_id, None)
            continue
        price = st.best.price_rub
        if prev:
            prev_at = datetime.fromisoformat(prev["at"])
            if price > prev["price"] - cheaper_by and now - prev_at < timedelta(days=after_days):
                continue
        alerts_state[st.route_id] = {"price": price, "at": now.isoformat()}
        send.append(st)
    return send


def fmt_rub(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"{int(round(n)):,}".replace(",", " ") + " ₽"
