"""Высокоуровневый сервис: адрес → координаты → расстояние по дорогам.

Геокодер выбирается автоматически:
  - Если задан YANDEX_GEOCODER_KEY → Яндекс (лучше для адресов в РФ)
  - Иначе → Nominatim (OpenStreetMap, бесплатно без ключа)

Расстояние по дорогам считается через OSRM (router.project-osrm.org, бесплатно).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from . import nominatim, osrm, yandex


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    normalized_address: str


@dataclass
class DistanceResult:
    km: float
    normalized_from: str
    normalized_to: str
    source: str  # "yandex+osrm" | "nominatim+osrm"


@dataclass
class DistanceError:
    code: str  # "geocode_from_failed" | "geocode_to_failed" | "route_failed"
    message: str


def _geocode(address: str) -> Optional[GeocodeResult]:
    key = os.environ.get("YANDEX_GEOCODER_KEY", "").strip()
    if key:
        try:
            r = yandex.geocode(address, key)
            if r:
                return GeocodeResult(lat=r[0], lon=r[1], normalized_address=r[2])
        except Exception:
            pass  # упадём к Nominatim
    try:
        r = nominatim.geocode(address)
        if r:
            return GeocodeResult(lat=r[0], lon=r[1], normalized_address=r[2])
    except Exception:
        return None
    return None


def calc_distance(from_address: str, to_address: str):
    """Вернёт DistanceResult при успехе или DistanceError с конкретной причиной."""
    src_geocoder = "yandex" if os.environ.get("YANDEX_GEOCODER_KEY", "").strip() else "nominatim"

    a = _geocode(from_address)
    if not a:
        return DistanceError(
            code="geocode_from_failed",
            message=f"Не удалось найти базовый адрес «{from_address}». "
                    "Проверьте его в настройках профиля.",
        )
    b = _geocode(to_address)
    if not b:
        return DistanceError(
            code="geocode_to_failed",
            message=f"Не удалось найти адрес «{to_address}». "
                    "Попробуйте более полную форму: «Город, улица, дом».",
        )

    try:
        km = osrm.route_distance_km(a.lat, a.lon, b.lat, b.lon)
    except Exception as e:
        return DistanceError(
            code="route_failed",
            message=f"Не удалось построить маршрут: {e}",
        )
    if km is None:
        return DistanceError(
            code="route_failed",
            message="Маршрут между точками не построен (возможно, нет дороги).",
        )

    return DistanceResult(
        km=round(km, 1),
        normalized_from=a.normalized_address,
        normalized_to=b.normalized_address,
        source=f"{src_geocoder}+osrm",
    )
