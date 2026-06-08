"""Клиент Nominatim (OpenStreetMap геокодер, без ключей).

https://nominatim.org/release-docs/develop/api/Search/
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

from .preprocess import compact_for_nominatim, expand_abbreviations


def _query(address: str, timeout: float) -> Optional[tuple[float, float, str]]:
    params = {
        "q": address, "format": "json", "limit": "1", "accept-language": "ru",
    }
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PutevoyAI/0.1 (https://github.com/example/putevoy)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        return None
    item = data[0]
    return float(item["lat"]), float(item["lon"]), item.get("display_name", address)


def geocode(address: str, timeout: float = 10.0) -> Optional[tuple[float, float, str]]:
    """Адрес → (lat, lon, normalized).

    Три попытки в порядке возрастания агрессивности предобработки:
      1. Оригинальный текст пользователя.
      2. С раскрытыми сокращениями («ул.» → «улица» и т.п.).
      3. Компактный формат для OSM («улица Репищева, дом 10, корпус 3»
         → «Репищева 10к3») — Nominatim в РФ хорошо понимает именно его.
    """
    r = _query(address, timeout)
    if r is not None:
        return r
    expanded = expand_abbreviations(address)
    if expanded != address:
        r = _query(expanded, timeout)
        if r is not None:
            return r
    compact = compact_for_nominatim(address)
    if compact and compact != address and compact != expanded:
        r = _query(compact, timeout)
        if r is not None:
            return r
    return None
