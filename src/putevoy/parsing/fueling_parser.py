"""Парсер строк-заправок из свободного текста (без LLM, на regex).

Поддерживает:
  Заправка 05.03.2026 количество 47.50 цена 69.20 сумма 3286.00
  Заправка 05.03 47.50 л 69.20 руб
  15.04 47.5л по 69.20
  15.04.2026 - 47,63л x 69,37 = 3303,79
  23 апреля 45,69л 69,26 ₽

Не справится с очень нестандартными форматами — для них fallback на LLM (V2).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..generator.models import Fueling

MONTHS_RU = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def _parse_number(s: str) -> Optional[float]:
    s = s.replace(",", ".").replace(" ", "").replace("\xa0", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(text: str, default_year: Optional[int] = None) -> Optional[date]:
    """Распарсить дату из фрагмента: dd.mm.yyyy / dd.mm / dd месяц / dd месяц yyyy."""
    text = text.strip()

    # dd.mm.yyyy или dd.mm.yy
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})$", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None

    # dd.mm (без года)
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})$", text)
    if m and default_year:
        d, mo = int(m.group(1)), int(m.group(2))
        try:
            return date(default_year, mo, d)
        except ValueError:
            return None

    # dd месяц [yyyy]
    m = re.match(r"^(\d{1,2})\s+([А-Яа-я]+)\s*(\d{4})?$", text)
    if m:
        d = int(m.group(1))
        mo_word = m.group(2).lower()[:3]
        y = int(m.group(3)) if m.group(3) else default_year
        if mo_word in MONTHS_RU and y:
            try:
                return date(y, MONTHS_RU[mo_word], d)
            except ValueError:
                return None

    return None


# Универсальный регекс: вытаскиваем дату + 2-3 числа из строки
_DATE_RE = (
    r"(?P<date>\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?"
    r"|\d{1,2}\s+[А-Яа-я]+(?:\s+\d{4})?)"
)
_NUM_RE = r"\d+(?:[.,]\d+)?"
_LITERS_RE = rf"(?P<liters>{_NUM_RE})\s*(?:л|литр)?"
_PRICE_RE = rf"(?:по|x|×|\*|за|цена)?\s*(?P<price>{_NUM_RE})\s*(?:руб|₽|р|р\.|руб\.|/л)?"
_SUM_RE = rf"(?:=|сумма|итого|на)?\s*(?P<sum>{_NUM_RE})\s*(?:руб|₽)?"

# Общая стратегия: ищем строку, в которой есть дата и хотя бы 2 числа
_LINE_RE = re.compile(
    rf"{_DATE_RE}.*?{_LITERS_RE}.*?{_PRICE_RE}(?:.*?{_SUM_RE})?",
    re.IGNORECASE,
)


def parse_fuelings(text: str, default_year: Optional[int] = None) -> list[Fueling]:
    """Извлечь все заправки из произвольного текста (по одной на строку)."""
    result: list[Fueling] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_clean = re.sub(r"(?i)\bзаправка\b\s*", "", line)
        line_clean = re.sub(r"(?i)\bколичество\b", "", line_clean)
        line_clean = re.sub(r"(?i)\bцена\b", "", line_clean)
        line_clean = re.sub(r"(?i)\bсумма\b", "", line_clean)

        m = _LINE_RE.search(line_clean)
        if not m:
            continue
        d = _parse_date(m.group("date"), default_year=default_year)
        if not d:
            continue
        liters = _parse_number(m.group("liters"))
        price = _parse_number(m.group("price"))
        sum_val = _parse_number(m.group("sum")) if m.group("sum") else None
        if not liters or not price or liters <= 0 or price <= 0:
            continue
        # Sanity: цена обычно 30..150 ₽/л, литры 5..70.
        # Если price выглядит как сумма (> 200) — переинтерпретируем
        if price > 200 and (sum_val is None or sum_val < price):
            sum_val, price = price, sum_val if sum_val and sum_val < 200 else None
        result.append(Fueling(date=d, liters=liters, price_per_l=price, sum=sum_val))
    return result
