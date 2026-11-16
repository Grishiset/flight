"""Командная строка.

    python -m tracker run               # обычный запуск (так его вызывает GitHub Actions)
    python -m tracker run --dry-run     # ничего не сохранять и не отправлять, только показать
    python -m tracker run --only etihad # проверить один источник
    python -m tracker test-telegram     # проверить, что бот пишет в Telegram
    python -m tracker show              # показать последний результат в консоли
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .analyze import fmt_rub
from .app import run
from .config import load_config
from .notify import SOURCE_TITLES, Telegram, fmt_date
from .store import Store


def print_latest(latest: dict) -> None:
    print(f"\nПроверка: {latest['at']}  (лето {latest['window']['start']} … {latest['window']['end']})")
    for r in latest["routes"]:
        b = r["best"]
        if b:
            flag = "✅" if r["is_deal"] else "  "
            from datetime import date
            d1, d2 = date.fromisoformat(b["depart"]), date.fromisoformat(b["ret"])
            print(f"{flag} {r['name']:<16} {fmt_rub(b['price_rub']):>12}  порог {fmt_rub(r['threshold']):>10}  "
                  f"{fmt_date(d1)}–{fmt_date(d2)}  {b.get('airline') or ''}  [{SOURCE_TITLES.get(b['source'], b['source'])}]")
            for reason in r["reasons"]:
                print(f"     → {reason}")
        else:
            print(f"   {r['name']:<16} летних билетов не найдено")
    print("\nИсточники:")
    for k, v in latest["sources"].items():
        state = "пропущен: " + v["skipped"] if v["skipped"] else ("ок" if v["ok"] else "ОШИБКА")
        print(f"  {SOURCE_TITLES.get(k, k):<15} {state}; билетов {v['offers']}, летних {v['summer']}")
        for e in v["errors"][:3]:
            print(f"      {e}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tracker", description="Трекер летних цен на авиабилеты")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--data", default="data", help="папка с историей и состоянием")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="проверить цены")
    pr.add_argument("--dry-run", action="store_true", help="не сохранять и не отправлять уведомления")
    pr.add_argument("--no-browser", action="store_true", help="не запускать Chromium для защищённых сайтов")
    pr.add_argument("--only", nargs="*", help="только эти источники: travelpayouts google_flights etihad samokatus")
    pr.add_argument("--site", default="public", help="куда собрать сайт ('' — не собирать)")

    sub.add_parser("test-telegram", help="отправить тестовое сообщение")
    sub.add_parser("show", help="показать последний результат")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")

    if a.cmd == "test-telegram":
        tg = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
        if not tg.configured:
            print("Не заданы TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID", file=sys.stderr)
            return 2
        ok = tg.send("✈️ Трекер билетов подключён. Сюда будут приходить выгодные цены.")
        print("Отправлено" if ok else "Не удалось отправить — смотри лог выше")
        return 0 if ok else 1

    store = Store(a.data)
    if a.cmd == "show":
        latest = store.latest()
        if not latest:
            print("Пока нет ни одной проверки")
            return 1
        print_latest(latest)
        return 0

    cfg = load_config(a.config)
    latest = run(cfg, store, a.site or None, dry_run=a.dry_run, use_browser=not a.no_browser, only=a.only)
    print_latest(latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
