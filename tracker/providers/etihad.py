"""Etihad: страницы «Авиабилеты из … в …» на etihad.com.

На них Etihad показывает тарифы, которые недавно видели пользователи его сайта
(карточка: «Москва (SVO) → Токио (NRT), 25 нояб. 2026 - 10 дек. 2026, Туда - обратно, От EUR671»).
Этих цен часто нет на агрегаторах. Цены в валюте — переводим в рубли по курсу ЦБ.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..http import get
from ..models import Offer, SourceResult
from ..ru_dates import parse_ru_date
from .base import Provider

CARD_RE = re.compile(
    r"\((?P<o>[A-Z]{3})\)\s*(?:к\s*)?"                       # Москва (SVO)к
    r"(?P<dname>[^\n()]{1,60}?)\s*\((?P<d>[A-Z]{3})\)\s*"   # Токио (NRT)
    r"(?P<d1>\d{1,2}\s+[А-Яа-яЁё]+\.?\s+\d{4})\s*[-–—]\s*"
    r"(?P<d2>\d{1,2}\s+[А-Яа-яЁё]+\.?\s+\d{4})\s*"
    r"Туда\s*[-–—]\s*обратно"
    r"(?P<mid>[\s\S]{0,120}?)"
    r"От\s*(?P<cur>[A-Z]{3})\s*(?P<amt>\d[\d,.   ]*)",
)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def _amount(raw: str) -> float | None:
    s = raw.strip().replace(" ", "").replace(" ", "").replace(" ", "")
    s = s.rstrip(".,")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        # «1,293» — разделитель тысяч; «12,5» в тарифах не встречается
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_cards(text: str) -> list[dict]:
    """Возвращает уникальные карточки тарифов «туда-обратно» из текста страницы."""
    text = re.sub(r"[ \t]+", " ", text)
    seen = set()
    cards = []
    for m in CARD_RE.finditer(text):
        dep = parse_ru_date(m.group("d1"))
        ret = parse_ru_date(m.group("d2"))
        amt = _amount(m.group("amt"))
        if not (dep and ret and amt):
            continue
        cabin = "economy" if "Эконом" in m.group("mid") else ("business" if "Бизнес" in m.group("mid") else None)
        card = {
            "origin": m.group("o"),
            "destination": m.group("d"),
            "dest_name": m.group("dname").strip(),
            "depart": dep,
            "ret": ret,
            "currency": m.group("cur"),
            "amount": amt,
            "cabin": cabin,
        }
        k = (card["origin"], card["destination"], dep, ret, card["currency"], amt)
        if k in seen:
            continue
        seen.add(k)
        cards.append(card)
    return cards


class EtihadProvider(Provider):
    name = "etihad"
    title = "Etihad (сайт авиакомпании)"

    def page_url(self, slug: str) -> str:
        base = self.opts.get("base_url", "https://www.etihad.com/ru/flights/")
        return base + quote(slug, safe="-")

    def fetch_text(self, url: str) -> tuple[str | None, str | None, bool]:
        """Возвращает (текст, ошибка, сайт_отказал).

        Обычный запрос, а если страница рисуется скриптами — браузер.
        Защиту от ботов не обходим: если сайт отказал, просто сообщаем об этом.
        """
        err = None
        refused = False
        try:
            r = get(self.ctx.http, url, tries=1)
            if r.status_code == 404:
                return None, "страница не найдена (404)", False
            if r.status_code == 200:
                text = html_to_text(r.text)
                if "обратно" in text:
                    return text, None, False
                err = "на странице нет тарифов"
            else:
                err = f"HTTP {r.status_code}"
                refused = r.status_code in (403, 429)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            refused = True
        if self.ctx.browser is None or refused:
            return None, err, refused
        try:
            return self.ctx.browser.text(url), None, False
        except Exception as e:  # noqa: BLE001
            return None, f"{err}; браузер: {str(e).splitlines()[0]}", True

    def collect(self, res: SourceResult) -> None:
        cfg = self.ctx.cfg
        origins = set(cfg.origin_airports)
        for route in cfg.routes:
            dests = set(route.airports)
            for slug in route.etihad_pages:
                url = self.page_url(slug)
                text, err, refused = self.fetch_text(url)
                if refused:
                    # Сайт не пускает автоматические запросы с этого адреса — не долбим остальные страницы
                    res.errors.append(
                        f"etihad.com не отвечает на автоматические запросы с этого сервера ({err}). "
                        "Тарифы Etihad приходят через Google Flights."
                    )
                    return
                if text is None:
                    if err and "404" not in err:
                        res.errors.append(f"{route.id} {slug}: {err}")
                    continue
                for c in parse_cards(text):
                    if c["origin"] not in origins or c["destination"] not in dests:
                        continue
                    if c["cabin"] == "business":
                        continue
                    rub = self.ctx.rates.to_rub(c["amount"], c["currency"])
                    if rub is None:
                        res.errors.append(f"нет курса для {c['currency']}")
                        continue
                    res.offers.append(
                        Offer(
                            route_id=route.id,
                            source="etihad",
                            price_rub=rub,
                            depart=c["depart"],
                            ret=c["ret"],
                            airline="Etihad",
                            origin=c["origin"],
                            destination=c["destination"],
                            link=url,
                            price_orig=c["amount"],
                            currency_orig=c["currency"],
                            note=f"{c['currency']} {c['amount']:,.0f} по курсу {self.ctx.rates.source}",
                        )
                    )
