"""Рабочие дни РФ для генератора."""
from __future__ import annotations

from datetime import date

from workalendar.europe import Russia

_cal = Russia()


def working_days(year: int, month: int) -> list[date]:
    """Все рабочие дни РФ в указанном месяце (учёт праздников и переносов)."""
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    result: list[date] = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if _cal.is_working_day(d):
            result.append(d)
    return result


MONTH_GENITIVE_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

MONTH_NOMINATIVE_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
