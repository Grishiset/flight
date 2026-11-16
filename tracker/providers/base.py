from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Config
from ..fx import Rates
from ..http import Browser
from ..models import SourceResult


@dataclass
class Context:
    cfg: Config
    http: httpx.Client
    rates: Rates
    state: dict                                  # общее состояние между запусками (data/state.json)
    browser: Browser | None = None               # None — браузер запрещён (--no-browser)
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    extra: dict[str, Any] = field(default_factory=dict)


_SECRET_RE = re.compile(r"((?:api_key|token|key)=)[^&\s'\"]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Убирает ключи из текста ошибок: они попадают в публичный лог и на сайт."""
    return _SECRET_RE.sub(r"\1***", text)


class Provider:
    name: str = "base"
    title: str = "Источник"

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.opts = ctx.cfg.source(self.name)

    def enabled(self) -> str | None:
        """None — можно запускать; иначе причина пропуска."""
        if not self.opts.get("enabled", True):
            return "выключен в config.yaml"
        return None

    def run(self) -> SourceResult:
        reason = self.enabled()
        if reason:
            return SourceResult(self.name, ok=True, skipped=reason)
        res = SourceResult(self.name)
        try:
            self.collect(res)
        except Exception as e:  # noqa: BLE001 — один источник не должен ронять остальные
            res.errors.append(f"{type(e).__name__}: {e}")
        res.errors = [redact(e) for e in res.errors]
        res.ok = not res.errors or bool(res.offers)
        return res

    def collect(self, res: SourceResult) -> None:  # pragma: no cover — переопределяется
        raise NotImplementedError
