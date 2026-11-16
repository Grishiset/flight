"""HTTP-клиент: обычный запрос, а для сайтов с защитой от ботов — настоящий браузер (Playwright)."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}


def client(timeout: float = 30) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True, http2=False)


def get(c: httpx.Client, url: str, *, params: dict | None = None, headers: dict | None = None,
        tries: int = 3) -> httpx.Response:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = c.get(url, params=params, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            time.sleep(2 * (i + 1))
    assert last is not None
    raise last


class Browser:
    """Ленивая обёртка над Playwright Chromium: запускается, только если понадобилась."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None

    def text(self, url: str, wait_selector: str | None = None, timeout_ms: int = 45000) -> str:
        if self._ctx is None:
            from playwright.sync_api import sync_playwright  # импорт только при необходимости

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._ctx = self._browser.new_context(user_agent=UA, locale="ru-RU")
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:  # noqa: BLE001 — страница могла отрисоваться иначе
                    pass
            page.wait_for_timeout(4000)
            return page.inner_text("body")
        finally:
            page.close()

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            self._pw.stop()
