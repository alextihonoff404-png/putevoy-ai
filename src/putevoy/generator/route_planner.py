"""Назначение маршрутов на рабочие дни (псевдослучайно, с фиксированным seed)."""
from __future__ import annotations

import random
from datetime import date

from .models import Fueling, Route


def assign_main_routes(
    days: list[date],
    routes: list[Route],
    seed: int,
) -> dict[date, Route]:
    """Простое назначение по весам без учёта баланса топлива.

    Воспроизводимо: один и тот же `seed` всегда даёт одно и то же распределение.
    Для UX обычно стоит использовать `assign_main_routes_budget_aware`.
    """
    if not routes:
        raise ValueError("Каталог маршрутов пуст")
    rng = random.Random(seed)
    weights = [r.weight for r in routes]
    return {d: rng.choices(routes, weights=weights, k=1)[0] for d in days}


SEGMENT_MIN_TARGET_END_L = 1.0  # минимальный остаток на конец каждого сегмента (кроме последнего)


def assign_main_routes_budget_aware(
    days: list[date],
    routes: list[Route],
    fuelings: list[Fueling],
    start_balance_l: float,
    target_end_balance_l: float,
    seed: int,
) -> dict[date, Route]:
    """Бюджетно-осведомлённое назначение с учётом сегментов между заправками
    + сглаживание расхода по дням сегмента.

    Алгоритм:
    1. Разбиваем дни на сегменты, где каждый сегмент начинается с дня заправки
       (первый сегмент может начинаться без заправки — со стартового остатка).
    2. Для каждого сегмента считаем локальный бюджет = balance_at_start + заправка
       − target_end. Target_end: 1 л для промежуточных сегментов,
       target_end_balance_l для последнего.
    3. Внутри сегмента для каждого дня вычисляем `target_today = remaining / remaining_days`
       и выбираем маршрут так, чтобы его расход за круг был близок к target_today.
       Это даёт равномерное распределение расхода (не «мелочи всю неделю → одна крупная»).

    Веса маршрутов учитываются как дополнительный множитель — пользователь может задать
    «как часто ездите», и при равном bias-весе предпочтение отдаётся более частым.
    """
    if not routes:
        raise ValueError("Каталог маршрутов пуст")
    rng = random.Random(seed)

    fueling_by_date = {f.date: f for f in fuelings}
    routes_sorted = sorted(routes, key=lambda r: r.consumption_l_one_way)
    min_burn = routes_sorted[0].consumption_l_one_way * 2

    # Разбиение на сегменты
    segments: list[list[date]] = []
    current: list[date] = []
    for d in days:
        if d in fueling_by_date and current:
            segments.append(current)
            current = []
        current.append(d)
    if current:
        segments.append(current)

    assignments: dict[date, Route] = {}
    balance = start_balance_l

    for seg_idx, seg in enumerate(segments):
        first_day = seg[0]
        if first_day in fueling_by_date:
            balance += fueling_by_date[first_day].liters

        is_last = seg_idx == len(segments) - 1
        target_end = target_end_balance_l if is_last else SEGMENT_MIN_TARGET_END_L

        remaining = balance - target_end  # бюджет сегмента

        for i, d in enumerate(seg):
            remaining_days = len(seg) - i

            # Цель на сегодня — равномерная доля от оставшегося бюджета
            target_today = remaining / remaining_days if remaining_days > 0 else min_burn

            # Не выходим за рамки: max не больше бюджета и не больше текущего балланса
            max_today = remaining - min_burn * (remaining_days - 1)
            max_today = min(max_today, balance)

            # Список доступных маршрутов (с burn ≤ max_today)
            candidates = [r for r in routes if r.consumption_l_one_way * 2 <= max_today + 0.5]
            if not candidates:
                candidates = [routes_sorted[0]]

            # Веса: близость к target_today × пользовательский weight × штраф за повторение
            last_route = assignments[seg[i - 1]] if i > 0 else None
            chosen = _pick_route_near_target(candidates, target_today, rng, last_route)
            assignments[d] = chosen

            burn = chosen.consumption_l_one_way * 2
            balance -= burn
            remaining -= burn

    return assignments


REPEAT_PENALTY = 0.3  # множитель веса для маршрута, который был выбран вчера


def _pick_route_near_target(routes: list[Route], target_l: float,
                            rng: random.Random,
                            last_route: Route | None = None) -> Route:
    """Выбрать маршрут, чей круговой расход близок к target_l.

    Веса собираются из трёх множителей:
    1. closeness = 1 / (1 + |burn − target|) — близость к среднему дневному расходу
    2. r.weight — пользовательское «как часто ездите»
    3. repeat_penalty — снижение веса для маршрута, выбранного вчера (для разнообразия)

    Это даёт картину: мелкие маршруты при низком бюджете чередуются между собой,
    а не повторяются подряд.
    """
    weights: list[float] = []
    for r in routes:
        burn = r.consumption_l_one_way * 2
        closeness = 1.0 / (1.0 + abs(burn - target_l))
        repeat = REPEAT_PENALTY if (last_route and r.address == last_route.address) else 1.0
        weights.append(closeness * r.weight * repeat)
    return rng.choices(routes, weights=weights, k=1)[0]
