from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class Route:
    id: str
    name: str
    threshold: int
    city: str
    airports: list[str]
    etihad_pages: list[str] = field(default_factory=list)
    samokatus: str | None = None


@dataclass
class Window:
    start: date
    end: date
    min_days: int = 1
    max_days: int = 60

    def contains(self, depart: date, ret: date) -> bool:
        days = (ret - depart).days
        return (
            self.start <= depart <= self.end
            and self.start <= ret <= self.end
            and self.min_days <= days <= self.max_days
        )


@dataclass
class Config:
    origin_name: str
    origin_city: str
    origin_airports: list[str]
    window: Window
    routes: list[Route]
    baseline: dict
    alerts: dict
    sources: dict
    fallback_rates: dict
    passengers: int = 1

    def route(self, route_id: str) -> Route:
        for r in self.routes:
            if r.id == route_id:
                return r
        raise KeyError(route_id)

    def source(self, name: str) -> dict:
        return self.sources.get(name) or {}


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    w = raw["window"]
    window = Window(
        start=_as_date(w["start"]),
        end=_as_date(w["end"]),
        min_days=int(w.get("min_days", 1)),
        max_days=int(w.get("max_days", 60)),
    )
    if window.end < window.start:
        raise ValueError("window.end раньше window.start")
    routes = []
    for r in raw["routes"]:
        routes.append(
            Route(
                id=str(r["id"]),
                name=str(r["name"]),
                threshold=int(r["threshold"]),
                city=str(r.get("city") or r["airports"][0]),
                airports=[str(a) for a in r.get("airports") or [r.get("city")]],
                etihad_pages=[str(p) for p in r.get("etihad_pages") or []],
                samokatus=r.get("samokatus"),
            )
        )
    ids = [r.id for r in routes]
    if len(ids) != len(set(ids)):
        raise ValueError("id направлений должны быть уникальны")
    o = raw["origin"]
    return Config(
        origin_name=o.get("name", o["city"]),
        origin_city=o["city"],
        origin_airports=list(o.get("airports") or [o["city"]]),
        window=window,
        routes=routes,
        baseline=raw.get("baseline") or {},
        alerts=raw.get("alerts") or {},
        sources=raw.get("sources") or {},
        fallback_rates=raw.get("fallback_rates") or {},
        passengers=max(1, int(raw.get("passengers") or 1)),
    )
