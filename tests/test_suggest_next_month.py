"""Тесты для `_suggest_next_month` — подсказка следующего месяца на /dashboard и /generate.

Логика по приоритету:
  1. Есть прогоны → месяц после самого свежего.
  2. Нет прогонов, есть `state.last_date` → месяц после last_date.
  3. Иначе → предыдущий календарный (новый user без профиля).

Тесты покрывают все три ветки + переход через декабрь.
"""
from __future__ import annotations

from datetime import date


SETUP_DATA_BASE = {
    "organization_name": "ООО ИИС", "mechanic_name": "Павлов В.О.",
    "driver_full_name": "Тихонов А.Ю.", "driver_snils": "098-274-108 00",
    "driver_license_number": "99 19 №306940", "driver_license_issue_date": "2020-10-23",
    "vehicle_make_model": "Changan CS55plus", "vehicle_license_plate": "Н960ХА 198",
    "vehicle_fuel_grade": "АИ-95", "vehicle_tank_capacity_l": "50",
    "base_city": "Санкт-Петербург", "base_street_type": "улица",
    "base_street_name": "Репищева", "base_house_number": "10", "base_corpus": "",
    "vehicle_fuel_consumption_l_per_100km": "10.4",
    "start_odometer_km": "49898", "start_fuel_balance_l": "31.37",
}


def _setup_profile(client, start_date: str) -> None:
    """Зарегистрировать профиль с заданной датой стартового состояния."""
    data = {**SETUP_DATA_BASE, "start_date": start_date}
    r = client.post("/setup", data=data, follow_redirects=False)
    assert r.status_code == 303, f"setup failed: {r.text[:200]}"


def _add_run_directly(year: int, month: int) -> None:
    """Добавить MonthlyRun прямо в БД, минуя генератор (для быстрого arrange)."""
    from datetime import datetime
    from sqlalchemy import select
    from putevoy.storage import db as _db
    from putevoy.storage.models import MonthlyRun, Vehicle
    from putevoy.storage.user_context import get_current_user_id

    uid = get_current_user_id()
    with _db.SessionLocal() as s:
        v = s.execute(select(Vehicle).where(Vehicle.user_id == uid)).scalars().first()
        assert v is not None, "нет активного ТС — сначала вызвать _setup_profile"
        s.add(MonthlyRun(
            vehicle_id=v.id, year=year, month=month,
            seed_used=1, validation_ok=True,
            validation_report_json='{"ok":true,"issues":[]}',
            generated_at=datetime(year, month, 1),
        ))
        s.commit()


def test_suggest_uses_state_last_date_when_no_runs(authed_client):
    """Профиль настроен, прогонов нет → берёт месяц после state.last_date."""
    from putevoy.web.app import _suggest_next_month

    _setup_profile(authed_client, start_date="2026-05-29")
    assert _suggest_next_month() == (2026, 6)


def test_suggest_state_december_rolls_to_next_year(authed_client):
    """state.last_date в декабре → переход на январь следующего года."""
    from putevoy.web.app import _suggest_next_month

    _setup_profile(authed_client, start_date="2026-12-31")
    assert _suggest_next_month() == (2027, 1)


def test_suggest_uses_latest_run_when_runs_exist(authed_client):
    """Есть прогоны → следующий месяц после самого свежего, state.last_date игнорится."""
    from putevoy.web.app import _suggest_next_month

    _setup_profile(authed_client, start_date="2026-05-29")
    # Прогоны не по порядку — функция должна взять максимум, а не последний добавленный
    _add_run_directly(2026, 3)
    _add_run_directly(2026, 7)
    _add_run_directly(2026, 5)
    assert _suggest_next_month() == (2026, 8)


def test_suggest_run_december_rolls_to_next_year(authed_client):
    """Самый свежий прогон в декабре → следующий январь следующего года."""
    from putevoy.web.app import _suggest_next_month

    _setup_profile(authed_client, start_date="2026-05-29")
    _add_run_directly(2026, 12)
    assert _suggest_next_month() == (2027, 1)


def test_suggest_falls_back_to_prev_calendar_without_profile(authed_client, monkeypatch):
    """Профиль не настроен, прогонов нет → фолбэк на предыдущий календарный месяц."""
    from datetime import date as _date
    import putevoy.web.app as app_mod

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 19)

    monkeypatch.setattr(app_mod, "date", _FixedDate)
    assert app_mod._suggest_next_month() == (2026, 5)


def test_suggest_january_fallback_rolls_to_previous_december(authed_client, monkeypatch):
    """Сегодня январь, без профиля и прогонов → декабрь прошлого года."""
    from datetime import date as _date
    import putevoy.web.app as app_mod

    class _FixedDate(_date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 5)

    monkeypatch.setattr(app_mod, "date", _FixedDate)
    assert app_mod._suggest_next_month() == (2025, 12)
