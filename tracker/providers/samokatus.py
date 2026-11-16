"""Самокатус: самые дешёвые билеты туда-обратно (данные Aviasales и Trip.com) + распродажи из их канала.

Карточка на странице: «Air China, 7 сен — 15 сен / 45 139 ₽ / одна пересадка».
Год в датах не указан — берём ближайшую будущую дату.
"""
from __future__ import annotations

import re
from datetime import date

from ..http import get
from ..models import Offer, SourceResult
from ..ru_dates import parse_ru_date
from .base import Provider
from .etihad import html_to_text

CARD_RE = re.compile(
    r"(?:(?P<air>[^\n,—–]{2,40}),\s*)?"
    r"(?P<d1>\d{1,2}\s+[а-яё]{3,6})\.?\s*[—–-]\s*(?P<d2>\d{1,2}\s+[а-яё]{3,6})\.?\s*\n\s*"
    r"(?P<price>\d{1,3}(?:[\s  ]\d{3})+|\d{4,7})\s*₽"
    r"(?:\s*\n\s*(?P<stops>прямой рейс|одна пересадка|две пересадки|три пересадки|четыре пересадки))?",
    re.IGNORECASE,
)

STOPS = {"прямой рейс": 0, "одна пересадка": 1, "две пересадки": 2, "три пересадки": 3, "четыре пересадки": 4}


def parse_cards(text: str, today: date | None = None) -> list[dict]:
    text = re.sub(r"[ \t]+", " ", text)
    today = today or date.today()
    seen = set()
    out = []
    for m in CARD_RE.finditer(text):
        dep = parse_ru_date(m.group("d1"), today=today)
        if not dep:
            continue
        ret = parse_ru_date(m.group("d2"), after=dep)
        if not ret:
            continue
        price = int(re.sub(r"\D", "", m.group("price")))
        air = (m.group("air") or "").strip() or None
        if air and (air[0].isdigit() or "₽" in air):
            air = None
        stops = STOPS.get((m.group("stops") or "").lower())
        k = (dep, ret, price, air)
        if k in seen:
            continue
        seen.add(k)
        out.append({"airline": air, "depart": dep, "ret": ret, "price": price, "stops": stops})
    return out


class SamokatusProvider(Provider):
    name = "samokatus"
    title = "Самокатус"

    def collect(self, res: SourceResult) -> None:
        base = self.opts.get("base_url", "https://samokatus.ru/flights/")
        for route in self.ctx.cfg.routes:
            if not route.samokatus:
                continue
            url = f"{base}{route.samokatus}/rt"
            text = None
            try:
                r = get(self.ctx.http, url, tries=2)
                if r.status_code == 200:
                    text = html_to_text(r.text)
                else:
                    res.errors.append(f"{route.id}: HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                res.errors.append(f"{route.id}: {e}")
            if (not text or "₽" not in text) and self.ctx.browser is not None:
                try:
                    text = self.ctx.browser.text(url)
                except Exception as e:  # noqa: BLE001
                    res.errors.append(f"{route.id} браузер: {e}")
            if not text:
                continue
            for c in parse_cards(text):
                res.offers.append(
                    Offer(
                        route_id=route.id,
                        source="samokatus",
                        price_rub=c["price"],
                        depart=c["depart"],
                        ret=c["ret"],
                        airline=c["airline"],
                        stops=c["stops"],
                        link=url,
                        price_orig=c["price"],
                        currency_orig="RUB",
                    )
                )
