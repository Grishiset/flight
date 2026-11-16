"""Сборка статического сайта для GitHub Pages: index.html + data.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

TEMPLATE = Path(__file__).parent / "site_template"
HISTORY_POINTS = 600   # последние ~100 дней при запуске каждые 4 часа


def compact_history(history: list[dict]) -> dict:
    """{route_id: [[iso, best|null], ...]} — для графиков."""
    out: dict[str, list] = {}
    for run in history[-HISTORY_POINTS:]:
        for rid, r in (run.get("routes") or {}).items():
            out.setdefault(rid, []).append([run["at"], r.get("best")])
    return out


def build_site(site_dir: str | Path, latest: dict, history: list[dict]) -> Path:
    site = Path(site_dir)
    site.mkdir(parents=True, exist_ok=True)
    for f in TEMPLATE.iterdir():
        if f.is_file():
            shutil.copy2(f, site / f.name)
    payload = {"latest": latest, "history": compact_history(history)}
    (site / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    return site
