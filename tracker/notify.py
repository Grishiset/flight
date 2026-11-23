"""Уведомления в Telegram."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta

import httpx

from .config import Config
from .airlines import airline_links, google_flights_url
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


def buy_links(o: Offer, passengers: int = 1) -> str:
    """«Aviasales (на 3) · China Southern · Google Flights» — где проверить и купить билет."""
    links = []
    if o.link and not o.legs:
        who = f" (на {passengers})" if passengers > 1 else ""
        links.append(f'<a href="{html.escape(o.link, quote=True)}">{SOURCE_TITLES.get(o.source, o.source)}{who}</a>')
    for name, url in airline_links(o.airline):
        links.append(f'<a href="{html.escape(url, quote=True)}">сайт {html.escape(name)}</a>')
    if not o.legs:
        g = google_flights_url(o.origin or "MOW", o.destination or "", o.depart, o.ret, passengers)
        links.append(f'<a href="{html.escape(g, quote=True)}">Google Flights{f" (на {passengers})" if passengers > 1 else ""}</a>')
    return " · ".join(links)


def offer_line(o: Offer) -> str:
    parts = [f"{fmt_date(o.depart)} → {fmt_date(o.ret)} ({o.days} дн.)"]
    if o.via:
        parts.append(f"через {html.escape(o.via)}")
    if o.airline:
        parts.append(html.escape(o.airline))
    if o.stops is not None:
        parts.append(stops_text(o.stops))
    return ", ".join(parts)


def group_price(o: Offer, passengers: int) -> int:
    if o.source == "google_flights" and o.price_orig is not None:
        return int(o.price_orig)
    return o.price_rub * passengers


def price_text(o: Offer, passengers: int) -> str:
    """«41 000 ₽ с человека, 123 000 ₽ на троих»."""
    per_person = o.price_rub
    if passengers <= 1:
        return fmt_rub(per_person)
    who = {2: "двоих", 3: "троих", 4: "четверых", 5: "пятерых"}.get(passengers, f"{passengers} чел.")
    return f"{fmt_rub(group_price(o, passengers))} на {who} ({fmt_rub(per_person)} с человека)"


def alert_message(sts: list[RouteStatus], site_url: str | None = None, passengers: int = 1) -> str:
    blocks = []
    for st in sts:
        o = st.best
        assert o is not None
        src = SOURCE_TITLES.get(o.source, o.source)
        lines = [
            f"✈️ <b>{html.escape(st.name)} — {price_text(o, passengers)}</b>, туда-обратно",
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
                lines.append(f"Для сравнения, одним билетом: {price_text(d, passengers)} "
                             f"({SOURCE_TITLES.get(d.source, d.source)}, {fmt_date(d.depart)} → {fmt_date(d.ret)})")
        links = buy_links(o, passengers)
        if links:
            lines.append("Проверить и купить: " + links)
        if passengers > 1:
            lines.append(f"⚠️ Поиск на {passengers} пассажиров. Наличие и цена могут измениться до оплаты.")
        blocks.append("\n".join(lines))
    text = "\n\n".join(blocks)
    if site_url:
        text += f'\n\n<a href="{html.escape(site_url, quote=True)}">Все цены</a>'
    return text


def week_min(history: list[dict], route_id: str, start, end) -> int | None:
    """Лучшая цена направления среди проверок в интервале [start, end)."""
    vals = []
    for run in history or []:
        try:
            at = datetime.fromisoformat(run["at"])
        except (KeyError, ValueError):
            continue
        if start <= at < end:
            v = ((run.get("routes") or {}).get(route_id) or {}).get("best")
            if isinstance(v, (int, float)):
                vals.append(int(v))
    return min(vals) if vals else None


def _pct(a: int, b: int) -> str:
    p = round((a / b - 1) * 100)
    return f"{'+' if p > 0 else '−' if p < 0 else '±'}{abs(p)}%"


def digest_message(sts: list[RouteStatus], sources: dict, site_url: str | None = None,
                   history: list[dict] | None = None, now: datetime | None = None,
                   passengers: int = 1, cfg: Config | None = None) -> str:
    """Отчёт: по каждому направлению — лучшая цена, лучшие варианты по каждому источнику,
    изменение за сутки и минимум за неделю."""
    now = now or datetime.now().astimezone()
    n = max(1, passengers)
    who = "1 взрослого" if n == 1 else f"{n} взрослых"
    lines = [f"🗓 <b>Отчёт по летним билетам</b> · {fmt_date(now.date())}\n"
             f"Туда-обратно на {who}; в скобках — цена с человека"
             + ("\n⚠️ Поиск на всю группу. Наличие и цена могут измениться до оплаты" if n > 1 else "")]
    lines.append('<a href="https://www.google.com/travel/flights?hl=ru&amp;curr=RUB">Открыть Google Flights</a>')
    for st in sts:
        lines.append("")
        if st.best:
            b = st.best
            diff = round((b.price_rub / st.threshold - 1) * 100)
            mark = "✅" if b.price_rub <= st.threshold else ("🔸" if diff <= 15 else "▫️")
            lines.append(f"{mark} <b>{html.escape(st.name)}: {fmt_rub(group_price(b, n))}</b> ({fmt_rub(b.price_rub)}, "
                         f"{'+' if diff > 0 else ''}{diff}% к порогу {fmt_rub(st.threshold)})")
            lines.append(f"   {offer_line(b)} — {SOURCE_TITLES.get(b.source, b.source)}")
            links = buy_links(b, n)
            if links:
                lines.append("   " + links)
        else:
            lines.append(f"▫️ <b>{html.escape(st.name)}</b>: нет свежей цены на всю группу (порог {fmt_rub(st.threshold)} с человека)")
            if cfg:
                dep = max(cfg.window.start, now.date())
                ret = dep + timedelta(days=cfg.window.min_days)
                if cfg.window.contains(dep, ret):
                    url = google_flights_url(cfg.origin_city, cfg.route(st.route_id).city, dep, ret, n)
                    lines.append(f'<a href="{html.escape(url, quote=True)}">Поиск на {n} чел. · {fmt_date(dep)} → {fmt_date(ret)}</a>')
        # по каждому источнику
        if st.by_source:
            parts = []
            for src, o in sorted(st.by_source.items(), key=lambda kv: kv[1].price_rub):
                title = SOURCE_TITLES.get(src, src).replace(" (Aviasales)", "")
                if o.via:
                    title += f" через {o.via}"
                parts.append(f"{html.escape(title)} {fmt_rub(group_price(o, n))}")
            lines.append("   Варианты: " + " · ".join(parts))
        # динамика (цены с человека)
        if history is not None:
            yday = week_min(history, st.route_id, now - timedelta(hours=48), now - timedelta(hours=20))
            week = week_min(history, st.route_id, now - timedelta(days=7), now + timedelta(seconds=1))
            bits = []
            if st.best and yday:
                bits.append(f"сутки назад {fmt_rub(yday)} ({_pct(st.best.price_rub, yday)})")
            if st.best and week:
                bits.append(f"минимум за неделю {fmt_rub(week)}")
            if bits:
                lines.append("   С человека: " + ", ".join(bits))
    bad = [SOURCE_TITLES.get(k, k) for k, v in sources.items() if not v.get("skipped") and not v.get("ok")]
    skipped = [f"{SOURCE_TITLES.get(k, k)} ({v['skipped']})" for k, v in sources.items() if v.get("skipped")]
    ok = [f"{SOURCE_TITLES.get(k, k)}: {v.get('summer', 0)} летних" for k, v in sources.items()
          if v.get("ok") and not v.get("skipped")]
    lines.append("")
    if ok:
        lines.append("Источники: " + html.escape(", ".join(ok)))
    if bad:
        lines.append("⚠️ Ошибки: " + html.escape(", ".join(bad)))
    if skipped:
        lines.append("Пропущены: " + html.escape(", ".join(skipped)))
    if site_url:
        lines.append(f'<a href="{html.escape(site_url, quote=True)}">Все цены и история</a>')
    return "\n".join(lines)


def message_chunks(text: str, limit: int = 3900) -> list[str]:
    """Разбивать по целым строкам: формирователи сообщений закрывают HTML-теги в каждой строке."""
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            # Не разрезаем длинный href или HTML-сущность. В исключительном случае
            # сохраняем видимый текст строки без форматирования.
            plain = html.unescape(re.sub(r"<[^>]*>", "", line))
            pieces = [html.escape(plain[i:i + limit // 5]) for i in range(0, len(plain), limit // 5)]
        else:
            pieces = [line]
        for piece in pieces:
            if len(current) + len(piece) > limit:
                chunks.append(current)
                current = ""
            current += piece
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


class Telegram:
    """Отправка в Telegram. chat_id — один или несколько через запятую: «111,222,-100333»."""

    def __init__(self, token: str | None, chat_id: str | None, dry_run: bool = False) -> None:
        self.token = (token or "").strip() or None
        self.chat_ids = [c.strip() for c in re.split(r"[,;\s]+", chat_id or "") if c.strip()]
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_ids)

    def send(self, text: str) -> bool:
        """True, если сообщение дошло хотя бы до одного получателя."""
        if self.dry_run or not self.configured:
            log.info("Telegram %s:\n%s", "(dry-run)" if self.dry_run else "(не настроен)", text)
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        # Telegram ограничивает сообщение 4096 символами
        chunks = message_chunks(text)
        if not chunks:
            return False
        delivered = 0
        for chat in self.chat_ids:
            ok = True
            for chunk in chunks:
                try:
                    r = httpx.post(url, json={
                        "chat_id": chat,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }, timeout=30)
                    if r.status_code != 200:
                        # Частая причина — получатель не нажал Start у бота
                        log.error("Telegram не доставил в чат %s (%s): %s", chat, r.status_code, r.text[:300])
                        ok = False
                        break
                except httpx.HTTPError as e:
                    log.error("Telegram недоступен: %s", type(e).__name__)
                    ok = False
                    break
            delivered += ok
        return delivered > 0
