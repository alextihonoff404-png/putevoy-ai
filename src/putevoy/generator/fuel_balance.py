"""Алгоритм расчёта остатка топлива и подбора доп. поездок при переполнении бака.

Правило (см. инструкцию §4 шаг 3):
  Если (остаток_до + заправка − расход_основной) ≥ tank_capacity
  → добавить доп. поездки ПОСЛЕ основной в тот же день из крупных маршрутов так,
    чтобы итого ≤ 3 поездок и излишек ушёл.

Минимизируем число добавленных маршрутов.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Optional

from .models import Fueling, Route

MAX_EXTRA_TRIPS = 2  # основная + 2 доп = 3 (≤ 3 поездок «всего» в смысле выходов из базы)


@dataclass(frozen=True)
class DayPlan:
    """Маршруты дня. Поездка == round-trip из базы (туда+обратно)."""

    main: Route
    extras: tuple[Route, ...] = ()

    @property
    def trips_count(self) -> int:
        return 1 + len(self.extras)

    @property
    def total_consumption_l(self) -> float:
        return round((self.main.consumption_l_one_way * 2)
                     + sum(r.consumption_l_one_way * 2 for r in self.extras), 4)

    @property
    def total_km(self) -> float:
        return (self.main.km_one_way * 2) + sum(r.km_one_way * 2 for r in self.extras)


def _fueling_for_day(d: date, fuelings: list[Fueling]) -> Optional[Fueling]:
    for f in fuelings:
        if f.date == d:
            return f
    return None


def _pick_extras(
    overflow_l: float,
    large_routes: list[Route],
) -> tuple[Route, ...]:
    """Подобрать минимальное число крупных маршрутов так, чтобы сжечь > overflow_l.

    Перебор сочетаний от 1 до MAX_EXTRA_TRIPS. Среди вариантов, удовлетворяющих
    условию, берём с минимальным числом маршрутов, среди равных — с минимальным
    суммарным расходом (чтобы не пережечь сильно).
    """
    best: tuple[Route, ...] | None = None
    for k in range(1, MAX_EXTRA_TRIPS + 1):
        candidates: list[tuple[Route, ...]] = []
        for combo in combinations(large_routes, k):
            burn = sum(r.consumption_l_one_way * 2 for r in combo)
            if burn > overflow_l:
                candidates.append(combo)
        if candidates:
            candidates.sort(key=lambda c: sum(r.consumption_l_one_way * 2 for r in c))
            best = candidates[0]
            break
    if best is None:
        # Не нашлось подходящего набора — берём максимально жгущий
        best = tuple(sorted(large_routes,
                            key=lambda r: -r.consumption_l_one_way)[:MAX_EXTRA_TRIPS])
    return best


def plan_day(
    main: Route,
    prev_balance_l: float,
    fueling: Optional[Fueling],
    tank_capacity_l: float,
    large_routes: list[Route],
) -> DayPlan:
    """Решить, нужно ли добавлять доп. поездки, и подобрать их."""
    fueled = fueling.liters if fueling else 0.0
    main_burn = main.consumption_l_one_way * 2
    projected_balance = prev_balance_l + fueled - main_burn
    if projected_balance < tank_capacity_l:
        return DayPlan(main=main)
    overflow = projected_balance - tank_capacity_l
    extras = _pick_extras(overflow, large_routes)
    return DayPlan(main=main, extras=extras)
