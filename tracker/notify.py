"""Уведомления в Telegram."""
from __future__ import annotations

import html
import logging
from datetime import datetime

import httpx

from .analyze import RouteStatus, fmt_rub
from .models import Offer

log = logging.getLogger(__name__)

SOURCE_TITLES = {
    "travelpayouts": "Aviasales",
    "google_flights": "Google Flights",
    "etihad": "Etihad",
    "samokatus": "Самокатус",
    "self_transfer": "Свои пересадки (Aviasales)",
}
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def fmt_date(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def stops_text(n: int | None) -> str:
    if n is None:
        return ""
    return {0: "без пересадок", 1: "1 пересадка"}.get(n, f"{n} пересадки" if n < 5 else f"{n} пересадок")


def _hm(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d:%H:%M}"


def legs_lines(o: Offer) -> list[str]:
    """Отдельные билеты маршрута — каждый со своей ссылкой."""
    lines = []
    for leg in o.legs or []:
        txt = (f"{html.escape(leg['from'])}→{html.escape(leg['to'])} {_hm(leg['dep'])}, "
               f"{html.escape(leg.get('airline') or '')} — {fmt_rub(leg['price'])}")
        if leg.get("link"):
            txt = f'<a href="{html.escape(leg["link"], quote=True)}">{txt}</a>'
        lines.append("  • " + txt)
    return lines


def offer_line(o: Offer) -> str:
    parts = [f"{fmt_date(o.depart)} → {fmt_date(o.ret)} ({o.days} дн.)"]
    if o.via:
        parts.append(f"через {html.escape(o.via)}")
    if o.airline:
        parts.append(html.escape(o.airline))
    if o.stops is not None:
        parts.append(stops_text(o.stops))
    return ", ".join(parts)


def alert_message(sts: list[RouteStatus], site_url: str | None = None) -> str:
    blocks = []
    for st in sts:
        o = st.best
        assert o is not None
        src = SOURCE_TITLES.get(o.source, o.source)
        lines = [
            f"✈️ <b>{html.escape(st.name)} — {fmt_rub(o.price_rub)}</b> туда-обратно",
            offer_line(o),
            f"Источник: {src}. " + "; ".join(html.escape(r) for r in st.reasons) + ".",
        ]
        if o.note and o.source in ("etihad", "self_transfer"):
            lines.append(html.escape(o.note))
        if o.legs:
            lines.extend(legs_lines(o))
            direct = [v for k, v in st.by_source.items() if k != "self_transfer"]
            if direct:
                d = min(direct, key=lambda x: x.price_rub)
                lines.append(f"Для сравнения, одним билетом: {fmt_rub(d.price_rub)} "
                             f"({SOURCE_TITLES.get(d.source, d.source)}, {fmt_date(d.depart)} → {fmt_date(d.ret)})")
        elif o.link:
            lines.append(f'<a href="{html.escape(o.link, quote=True)}">Открыть билет</a>')
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if site_url:
        text += f'\n\n<a href="{html.escape(site_url, quote=True)}">Все цены</a>'
    return text


def digest_message(sts: list[RouteStatus], sources: dict, site_url: str | None = None) -> str:
    lines = ["🗓 <b>Сводка по летним билетам</b>"]
    for st in sts:
        if st.best:
            diff = round((st.best.price_rub / st.threshold - 1) * 100)
            mark = "✅" if st.best.price_rub <= st.threshold else ("🔸" if diff <= 15 else "▫️")
            lines.append(
                f"{mark} {html.escape(st.name)}: {fmt_rub(st.best.price_rub)} "
                f"({'+' if diff > 0 else ''}{diff}% к порогу), {fmt_date(st.best.depart)}–{fmt_date(st.best.ret)}, "
                f"{SOURCE_TITLES.get(st.best.source, st.best.source)}"
            )
        else:
            lines.append(f"▫️ {html.escape(st.name)}: летних билетов в выдаче пока нет")
    bad = [SOURCE_TITLES.get(k, k) for k, v in sources.items() if not v.get("skipped") and not v.get("ok")]
    skipped = [f"{SOURCE_TITLES.get(k, k)} ({v['skipped']})" for k, v in sources.items() if v.get("skipped")]
    if bad:
        lines.append("\n⚠️ Ошибки источников: " + ", ".join(bad))
    if skipped:
        lines.append("Пропущены: " + html.escape(", ".join(skipped)))
    if site_url:
        lines.append(f'\n<a href="{html.escape(site_url, quote=True)}">Все цены и история</a>')
    return "\n".join(lines)


class Telegram:
    def __init__(self, token: str | None, chat_id: str | None, dry_run: bool = False) -> None:
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if self.dry_run or not self.configured:
            log.info("Telegram %s:\n%s", "(dry-run)" if self.dry_run else "(не настроен)", text)
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        # Telegram ограничивает сообщение 4096 символами
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [text]
        ok = True
        for chunk in chunks:
            try:
                r = httpx.post(url, json={
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }, timeout=30)
                if r.status_code != 200:
                    log.error("Telegram ответил %s: %s", r.status_code, r.text[:300])
                    ok = False
            except httpx.HTTPError as e:
                log.error("Telegram недоступен: %s", e)
                ok = False
        return ok
