from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Offer:
    """Один найденный билет туда-обратно."""

    route_id: str
    source: str                 # travelpayouts | google_flights | etihad | samokatus
    price_rub: int
    depart: date
    ret: date
    airline: str | None = None
    stops: int | None = None    # пересадок в одну сторону (максимум из двух направлений)
    origin: str | None = None
    destination: str | None = None
    link: str | None = None
    price_orig: float | None = None
    currency_orig: str | None = None
    note: str | None = None
    typical_range: list[int] | None = None   # «обычные» цены по Google Flights, ₽
    via: str | None = None                   # хаб самостоятельной пересадки (Ташкент, Стамбул…)
    legs: list[dict] | None = None           # отдельные билеты маршрута (для self_transfer)
    extra_rub: int = 0                       # сколько в цене — оценка ночёвки, не билеты

    @property
    def days(self) -> int:
        return (self.ret - self.depart).days

    def key(self) -> str:
        return f"{self.route_id}|{self.source}|{self.depart}|{self.ret}|{self.airline or ''}|{self.via or ''}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["depart"] = self.depart.isoformat()
        d["ret"] = self.ret.isoformat()
        d["days"] = self.days
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Offer":
        d = dict(d)
        d.pop("days", None)
        d["depart"] = date.fromisoformat(d["depart"])
        d["ret"] = date.fromisoformat(d["ret"])
        return cls(**d)


@dataclass
class SourceResult:
    source: str
    ok: bool = True
    offers: list[Offer] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None   # причина, если источник выключен/нет ключа
