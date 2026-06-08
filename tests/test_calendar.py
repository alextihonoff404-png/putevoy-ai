"""Тесты модуля calendar."""
from datetime import date

from putevoy.generator.calendar import working_days


def test_april_2026_has_22_working_days():
    # Апрель 2026: 1–30, нет праздничных дат, выходные 4,5,11,12,18,19,25,26 → 30−8=22
    days = working_days(2026, 4)
    assert len(days) == 22
    assert days[0] == date(2026, 4, 1)
    assert days[-1] == date(2026, 4, 30)


def test_may_2026_skips_holidays():
    # Май 2026: 1 мая (пт, праздник), 9 мая (сб), плюс переносы
    days = working_days(2026, 5)
    assert date(2026, 5, 1) not in days
    # 4 мая 2026 — понедельник, рабочий
    assert date(2026, 5, 4) in days


def test_february_2026_skips_23():
    days = working_days(2026, 2)
    assert date(2026, 2, 23) not in days


def test_march_2026_skips_8():
    days = working_days(2026, 3)
    assert date(2026, 3, 9) not in days  # 8 марта = вс, переносится на 9-е
