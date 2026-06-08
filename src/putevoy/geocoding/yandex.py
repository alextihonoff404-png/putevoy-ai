"""Клиент Яндекс HTTP Геокодера.

Документация: https://yandex.ru/dev/maps/geocoder/
Endpoint: https://geocode-maps.yandex.ru/1.x/?apikey=KEY&geocode=ADDR&format=json
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

from .preprocess import expand_abbreviations


def _query(address: str, api_key: str, timeout: float) -> Optional[tuple[float, float, str]]:
    params = {
        "apikey": api_key, "geocode": address, "format": "json",
        "results": "1", "lang": "ru_RU",
    }
    url = "https://geocode-maps.yandex.ru/1.x/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "PutevoyAI/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        feature = data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
        lon_str, lat_str = feature["Point"]["pos"].split()
        normalized = feature["metaDataProperty"]["GeocoderMetaData"]["text"]
        return float(lat_str), float(lon_str), normalized
    except (KeyError, IndexError, ValueError):
        return None


def geocode(address: str, api_key: str, timeout: float = 10.0) -> Optional[tuple[float, float, str]]:
    """Адрес → (lat, lon, normalized). Пробуем оригинал и развёрнутые сокращения."""
    r = _query(address, api_key, timeout)
    if r is not None:
        return r
    expanded = expand_abbreviations(address)
    if expanded != address:
        r = _query(expanded, api_key, timeout)
        if r is not None:
            return r
    return None
