"""Данные между запусками: история, состояние, последний результат. Хранятся в папке data/ репозитория."""
from __future__ import annotations

import json
from pathlib import Path

MAX_RUNS = 2500   # ≈ год при запуске каждые 4 часа


class Store:
    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _read(self, name: str, default):
        p = self.root / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _write(self, name: str, data) -> None:
        p = self.root / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def history(self) -> list[dict]:
        return self._read("history.json", [])

    def save_history(self, runs: list[dict]) -> None:
        self._write("history.json", runs[-MAX_RUNS:])

    def state(self) -> dict:
        return self._read("state.json", {})

    def save_state(self, state: dict) -> None:
        self._write("state.json", state)

    def save_latest(self, latest: dict) -> None:
        self._write("latest.json", latest)

    def latest(self) -> dict | None:
        return self._read("latest.json", None)
