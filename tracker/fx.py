"""Курсы валют ЦБ РФ (через cbr-xml-daily.ru) с запасными значениями из конфига."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


class Rates:
    def __init__(self, rates: dict[str, float], source: str) -> None:
        self.rates = {k.upper(): float(v) for k, v in rates.items()}
        self.rates["RUB"] = 1.0
        self.source = source

    def to_rub(self, amount: float, currency: str) -> int | None:
        rate = self.rates.get(currency.upper())
        if rate is None:
            return None
        return int(round(amount * rate))


def load_rates(c: httpx.Client, fallback: dict) -> Rates:
    try:
        r = c.get(CBR_URL, timeout=15)
        r.raise_for_status()
        valutes = r.json()["Valute"]
        rates = {code: v["Value"] / v["Nominal"] for code, v in valutes.items()}
        for k, v in fallback.items():
            rates.setdefault(k, v)
        return Rates(rates, "ЦБ РФ")
    except Exception as e:  # noqa: BLE001
        log.warning("Курсы ЦБ недоступны (%s), беру запасные из config.yaml", e)
        return Rates(fallback, "config.yaml")
