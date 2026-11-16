"""Разбор русских дат вида «25 нояб. 2026», «7 сен», «1 июня»."""
from __future__ import annotations

import re
from datetime import date

# Порядок важен: «мар» раньше «май»/«мая» не пересекается, но «июн»/«июл» различаем по 3-й букве.
_MONTHS = [
    ("янв", 1), ("фев", 2), ("мар", 3), ("апр", 4), ("мая", 5), ("май", 5),
    ("июн", 6), ("июл", 7), ("авг", 8), ("сен", 9), ("окт", 10), ("ноя", 11), ("дек", 12),
]

_DATE_RE = re.compile(r"(\d{1,2})\s+([А-Яа-яЁё]+)\.?(?:\s+(\d{4}))?")


def month_from_word(word: str) -> int | None:
    w = word.lower().strip(".")
    for prefix, num in _MONTHS:
        if w.startswith(prefix):
            return num
    return None


def parse_ru_date(text: str, today: date | None = None, after: date | None = None) -> date | None:
    """Разбирает первую дату в тексте.

    Если год не указан, берётся ближайший год, при котором дата не раньше `after`
    (или сегодняшнего дня минус 1 день).
    """
    m = _DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month = month_from_word(m.group(2))
    if not month:
        return None
    if m.group(3):
        try:
            return date(int(m.group(3)), month, day)
        except ValueError:
            return None
    ref = after or (today or date.today())
    for year in (ref.year, ref.year + 1, ref.year + 2):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= ref or (after is None and (ref - d).days <= 1):
            return d
    return None
