"""Расписание поездок: 09:00, шаг 3 ч, до 4 поездок в день.

Каждая поездка занимает 3 часа: 1 ч туда + 1 ч на месте + 1 ч обратно.
В путевом листе одна поездка = 2 строки (туда и обратно).
"""
from __future__ import annotations

from datetime import time

WORK_DAY_START_HOUR = 9
TRIP_DURATION_HOURS = 3
ONE_WAY_HOURS = 1
AT_DESTINATION_HOURS = 1
MAX_TRIPS_PER_DAY = 4


def trip_times(trip_index: int) -> tuple[time, time, time, time]:
    """Вернуть (выезд_с_базы, прибытие_в_пункт, выезд_из_пункта, возврат_на_базу) для trip_index (0-based).

    Поездка 0: 09:00 → 10:00 → 11:00 → 12:00
    Поездка 1: 12:00 → 13:00 → 14:00 → 15:00
    Поездка 2: 15:00 → 16:00 → 17:00 → 18:00
    Поездка 3: 18:00 → 19:00 → 20:00 → 21:00
    """
    if not 0 <= trip_index < MAX_TRIPS_PER_DAY:
        raise ValueError(f"trip_index должен быть 0..{MAX_TRIPS_PER_DAY - 1}, получен {trip_index}")
    base = WORK_DAY_START_HOUR + trip_index * TRIP_DURATION_HOURS
    return (
        time(base, 0),
        time(base + ONE_WAY_HOURS, 0),
        time(base + ONE_WAY_HOURS + AT_DESTINATION_HOURS, 0),
        time(base + TRIP_DURATION_HOURS, 0),
    )
