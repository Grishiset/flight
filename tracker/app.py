"""Один запуск трекера: собрать цены → проанализировать → уведомить → сохранить → собрать сайт."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .analyze import evaluate, pick_alerts
from .config import Config
from .fx import load_rates
from .http import Browser, client
from .models import Offer, SourceResult
from .notify import Telegram, alert_message, digest_message
from .providers import ALL_PROVIDERS
from .providers.base import Context
from .site import build_site
from .store import Store

log = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")


def report_due(alerts: dict, msk_now: datetime) -> bool:
    """Пора ли слать отчёт: подходящий день и время уже наступило (по Москве)."""
    days = alerts.get("digest_days", alerts.get("digest_weekday"))
    if days is None:
        return False
    if days != "daily":
        allowed = {int(d) for d in (days if isinstance(days, list) else [days])}
        if msk_now.weekday() not in allowed:
            return False
    hh, mm = (str(alerts.get("digest_time_msk") or f"{alerts.get('digest_hour_msk', 0)}:00").split(":") + ["0"])[:2]
    return (msk_now.hour, msk_now.minute) >= (int(hh), int(mm))


def collect(ctx: Context, only: list[str] | None = None) -> list[SourceResult]:
    results = []
    for cls in ALL_PROVIDERS:
        if only and cls.name not in only:
            continue
        if ctx.cfg.passengers > 1 and cls.name != "google_flights":
            results.append(SourceResult(cls.name, skipped="источник не проверяет наличие мест на всю группу"))
            continue
        log.info("Источник: %s", cls.title)
        res = cls(ctx).run()
        if res.skipped:
            log.info("  пропущен: %s", res.skipped)
        else:
            log.info("  билетов: %d, ошибок: %d", len(res.offers), len(res.errors))
            for e in res.errors[:10]:
                log.warning("  %s", e)
        results.append(res)
    return results


def sources_summary(results: list[SourceResult], cfg: Config) -> dict:
    out = {}
    for r in results:
        out[r.source] = {
            "ok": r.ok and not r.skipped,
            "skipped": r.skipped,
            "offers": len(r.offers),
            "summer": sum(1 for o in r.offers if cfg.window.contains(o.depart, o.ret)),
            "errors": r.errors[:20],
        }
    return out


def run(
    cfg: Config,
    store: Store,
    site_dir: str | Path | None = "public",
    *,
    dry_run: bool = False,
    use_browser: bool = True,
    only: list[str] | None = None,
    now: datetime | None = None,
    results: list[SourceResult] | None = None,
    env: dict | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    env = dict(os.environ if env is None else env)
    state = store.state()
    history = store.history()
    site_url = env.get("SITE_URL") or state.get("site_url")

    browser = Browser() if use_browser else None
    try:
        with client() as http:
            rates = load_rates(http, cfg.fallback_rates)
            ctx = Context(cfg=cfg, http=http, rates=rates, state=state, browser=browser, env=env)
            if results is None:
                results = collect(ctx, only)
    finally:
        if browser:
            browser.close()

    offers: list[Offer] = [o for r in results for o in r.offers]
    statuses = evaluate(cfg, offers, history, now)
    srcs = sources_summary(results, cfg)

    tg = Telegram(env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID"), dry_run=dry_run)
    sent = []

    # 1. Выгодные цены
    to_alert = pick_alerts(statuses, state, cfg, now)
    if to_alert:
        tg.send(alert_message(to_alert, site_url, passengers=cfg.passengers))
        sent.append("alert:" + ",".join(s.route_id for s in to_alert))

    # 2. Отчёт — в первую проверку после digest_time_msk в подходящий день (по Москве),
    #    либо сразу, если попросили (FORCE_REPORT=1 / кнопка в GitHub Actions)
    msk_now = now.astimezone(MSK)
    msk_day = msk_now.date()
    due = report_due(cfg.alerts, msk_now) and state.get("last_digest") != msk_day.isoformat()
    forced = env.get("FORCE_REPORT") in ("1", "true", "True")
    if due or forced:
        delivered = tg.send(digest_message(statuses, srcs, site_url, history=history, now=now,
                                           passengers=cfg.passengers))
        if due and delivered and not dry_run:
            state["last_digest"] = msk_day.isoformat()
        if not delivered and not dry_run:
            log.error("Ежедневный отчёт не доставлен; следующая проверка повторит попытку")
        sent.append("digest" if delivered or dry_run else "digest:not_delivered")

    # 3. Все источники падают несколько запусков подряд
    active = [v for v in srcs.values() if not v["skipped"]]
    all_failed = bool(active) and all(v["offers"] == 0 and v["errors"] for v in active)
    state["failing_runs"] = state.get("failing_runs", 0) + 1 if all_failed else 0
    limit = int(cfg.alerts.get("failing_runs_to_warn", 3))
    if state["failing_runs"] == limit:
        errs = "; ".join(e for v in active for e in v["errors"][:1])[:600]
        tg.send(f"⚠️ Трекер билетов: все источники не отвечают {limit} запуска подряд.\n{errs}")
        sent.append("health")

    # 4. Сохранить
    run_rec = {
        "at": now.isoformat(),
        "routes": {
            s.route_id: {
                "best": s.best.price_rub if s.best else None,
                "src": s.best.source if s.best else None,
                "by_source": {k: v.price_rub for k, v in s.by_source.items()},
            }
            for s in statuses
        },
        "sources": {k: {"ok": v["ok"], "offers": v["offers"], "skipped": v["skipped"]} for k, v in srcs.items()},
    }
    history.append(run_rec)
    latest = {
        "at": now.isoformat(),
        "window": {
            "start": cfg.window.start.isoformat(),
            "end": cfg.window.end.isoformat(),
            "min_days": cfg.window.min_days,
            "max_days": cfg.window.max_days,
        },
        "origin": cfg.origin_name,
        "passengers": cfg.passengers,
        "rates_source": rates.source,
        "routes": [s.to_dict() for s in statuses],
        "sources": srcs,
        "sent": sent,
    }
    if not dry_run:
        store.save_history(history)
        store.save_state(state)
        store.save_latest(latest)
    if site_dir:
        build_site(site_dir, latest, history)
    return latest
