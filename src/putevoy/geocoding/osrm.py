"""Клиент OSRM (Open Source Routing Machine).

Публичный сервер: https://router.project-osrm.org
Документация: https://project-osrm.org/docs/v5.24.0/api/

Используется только для расчёта расстояния по дорогам между двумя точками
(geometry/маршрут не нужны).
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional


def route_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float,
    timeout: float = 15.0,
) -> Optional[float]:
    """Расстояние от (lat1,lon1) до (lat2,lon2) по дорогам в км."""
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "PutevoyAI/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") != "Ok":
        return None
    routes = data.get("routes") or []
    if not routes:
        return None
    meters = routes[0].get("distance")
    if meters is None:
        return None
    return float(meters) / 1000.0
