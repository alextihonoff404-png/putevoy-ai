"""Per-user изоляция: два пользователя видят только свои данные.

Регресс-кейс: до изоляции любой залогиненный мог видеть Profile/Vehicle/Route/Run
других пользователей (singleton-таблицы).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from putevoy.storage.user_context import set_current_user_id, reset_current_user_id


SETUP_A = {
    "organization_name": "ООО Альфа", "mechanic_name": "Иванов А.А.",
    "driver_full_name": "Петров П.П.", "driver_snils": "111-111-111 11",
    "driver_license_number": "11 11 №111111", "driver_license_issue_date": "2020-01-01",
    "vehicle_make_model": "Альфа-машина", "vehicle_license_plate": "А111АА 11",
    "vehicle_fuel_grade": "АИ-95", "vehicle_tank_capacity_l": "50",
    "base_city": "Москва",
    "base_street_type": "улица",
    "base_street_name": "Ленина",
    "base_house_number": "1",
    "base_corpus": "",
    "vehicle_fuel_consumption_l_per_100km": "10.0",
    "start_odometer_km": "10000", "start_fuel_balance_l": "20",
    "start_date": "2026-01-01",
}

SETUP_B = {
    "organization_name": "ООО Бета", "mechanic_name": "Сидоров С.С.",
    "driver_full_name": "Кузнецов К.К.", "driver_snils": "222-222-222 22",
    "driver_license_number": "22 22 №222222", "driver_license_issue_date": "2021-02-02",
    "vehicle_make_model": "Бета-машина", "vehicle_license_plate": "Б222ББ 22",
    "vehicle_fuel_grade": "АИ-92", "vehicle_tank_capacity_l": "60",
    "base_city": "Казань",
    "base_street_type": "улица",
    "base_street_name": "Кремлёвская",
    "base_house_number": "2",
    "base_corpus": "",
    "vehicle_fuel_consumption_l_per_100km": "8.0",
    "start_odometer_km": "20000", "start_fuel_balance_l": "30",
    "start_date": "2026-02-01",
}


@pytest.fixture()
def two_users_setup(fresh_db):
    """Регистрирует двух пользователей, каждый настраивает свой профиль.

    Возвращает (client_a, client_b, user_a_id, user_b_id) для тестов.
    """
    from putevoy.web.app import app
    from putevoy.storage.auth_repo import create_user

    user_a = create_user("alpha@example.com", "passpass123")
    user_b = create_user("beta@example.com", "passpass456")

    client_a = TestClient(app)
    client_a.post("/login", data={"email": "alpha@example.com", "password": "passpass123"})

    client_b = TestClient(app)
    client_b.post("/login", data={"email": "beta@example.com", "password": "passpass456"})

    # User A настраивает свой профиль
    client_a.post("/setup", data=SETUP_A)
    # User B настраивает свой профиль
    client_b.post("/setup", data=SETUP_B)

    return client_a, client_b, user_a.id, user_b.id


def test_users_see_only_own_vehicles(two_users_setup):
    """User A не видит ТС user B и наоборот."""
    from putevoy.storage.repo import list_vehicles

    client_a, client_b, uid_a, uid_b = two_users_setup

    # User A: видит только свою «Альфа-машина»
    token = set_current_user_id(uid_a)
    try:
        vehicles_a = list_vehicles()
        plates_a = {v.license_plate for v in vehicles_a}
        assert "А111АА 11" in plates_a
        assert "Б222ББ 22" not in plates_a
    finally:
        reset_current_user_id(token)

    # User B: видит только свою «Бета-машина»
    token = set_current_user_id(uid_b)
    try:
        vehicles_b = list_vehicles()
        plates_b = {v.license_plate for v in vehicles_b}
        assert "Б222ББ 22" in plates_b
        assert "А111АА 11" not in plates_b
    finally:
        reset_current_user_id(token)


def test_users_see_only_own_profile_in_dashboard(two_users_setup):
    """В UI каждый видит только свой профиль (driver, vehicle make_model)."""
    client_a, client_b, _, _ = two_users_setup

    r_a = client_a.get("/dashboard")
    assert "Петров П.П." in r_a.text
    assert "Альфа-машина" in r_a.text
    assert "Кузнецов К.К." not in r_a.text
    assert "Бета-машина" not in r_a.text

    r_b = client_b.get("/dashboard")
    assert "Кузнецов К.К." in r_b.text
    assert "Бета-машина" in r_b.text
    assert "Петров П.П." not in r_b.text
    assert "Альфа-машина" not in r_b.text


def test_user_cannot_delete_other_users_route(two_users_setup):
    """User A не может удалить маршрут user B даже зная его route_id."""
    from putevoy.storage.repo import list_routes

    client_a, client_b, uid_a, uid_b = two_users_setup

    # User B добавляет маршрут
    client_b.post("/routes/add", data={
        "address": "СЕКРЕТНЫЙ маршрут B", "km_one_way": "10", "weight": "1.0",
    })
    # Получаем его id (как user B)
    token = set_current_user_id(uid_b)
    try:
        routes_b = list_routes()
        target_id = next(r.id for r in routes_b if "СЕКРЕТНЫЙ" in r.address)
    finally:
        reset_current_user_id(token)

    # User A пытается удалить маршрут user B
    client_a.post(f"/routes/{target_id}/delete")

    # Маршрут НЕ должен пропасть из БД user B
    token = set_current_user_id(uid_b)
    try:
        routes_b_after = list_routes()
        assert any("СЕКРЕТНЫЙ" in r.address for r in routes_b_after), \
            "User A смог удалить маршрут user B! Это уязвимость per-user изоляции."
    finally:
        reset_current_user_id(token)


def test_user_cannot_switch_to_other_users_vehicle(two_users_setup):
    """User A не может сделать активным ТС user B."""
    from putevoy.storage.repo import list_vehicles, current_vehicle_id

    client_a, _, uid_a, uid_b = two_users_setup

    # Узнаём id ТС user B
    token = set_current_user_id(uid_b)
    try:
        vehicle_b_id = list_vehicles()[0].id
    finally:
        reset_current_user_id(token)

    # User A пытается переключить активное ТС на чужое
    client_a.post(f"/vehicles/switch/{vehicle_b_id}")

    # Проверяем что активное ТС user A осталось его собственным
    token = set_current_user_id(uid_a)
    try:
        active = current_vehicle_id()
        own_vehicles = {v.id for v in list_vehicles()}
        assert active in own_vehicles, \
            f"User A получил активным ТС user B (id={active}, его id: {own_vehicles})"
    finally:
        reset_current_user_id(token)


# --- Миграция orphan-данных при первой регистрации ------------------------


def test_orphan_data_migrates_to_first_registered_user(fresh_db):
    """Сценарий: на сервере есть legacy данные без user_id (Vehicle, Profile),
    кто-то регистрируется первым → данные привязываются к нему.

    Это тот самый кейс, который описан в STATUS.md: на проде существующий
    Changan + Foyah + история должны достаться первому зарегистрированному.
    """
    from putevoy.storage import db as _db
    from putevoy.storage.models import Profile, Driver, Vehicle, VehicleState
    from putevoy.storage.auth_repo import create_user
    from datetime import date

    # Имитируем legacy: создаём данные без user_id напрямую
    with _db.SessionLocal() as s:
        p = Profile(organization_name="Legacy Org", mechanic_name="Legacy Mech",
                    user_id=None)
        s.add(p)
        d = Driver(full_name="Legacy Driver", snils="000-000-000 00",
                   license_number="LEG", license_issue_date=date(2020, 1, 1),
                   user_id=None)
        s.add(d)
        v = Vehicle(make_model="Legacy Car", license_plate="L 000",
                    fuel_grade="АИ-95", tank_capacity_l=50.0,
                    base_address="Где-то", fuel_consumption_l_per_100km=10.0,
                    user_id=None)
        s.add(v)
        s.flush()
        st = VehicleState(vehicle_id=v.id, current_odometer_km=1000,
                          current_fuel_balance_l=20.0, last_date=date(2025, 12, 31))
        s.add(st)
        s.commit()

    # Регистрируем первого пользователя
    user = create_user("firstuser@example.com", "firstpass")
    assert user is not None

    # Проверяем что все orphan-записи привязаны к нему
    with _db.SessionLocal() as s:
        from sqlalchemy import select
        profiles = list(s.execute(select(Profile)).scalars())
        assert all(p.user_id == user.id for p in profiles), \
            "Profile не привязался к первому user"

        drivers = list(s.execute(select(Driver)).scalars())
        assert all(d.user_id == user.id for d in drivers), \
            "Driver не привязался к первому user"

        vehicles = list(s.execute(select(Vehicle)).scalars())
        assert all(v.user_id == user.id for v in vehicles), \
            "Vehicle не привязался к первому user"


def test_orphan_data_does_not_migrate_to_second_user(fresh_db):
    """Только ПЕРВЫЙ user забирает orphan-данные. Второй регистрируется в чистый scope."""
    from putevoy.storage import db as _db
    from putevoy.storage.models import Vehicle
    from putevoy.storage.auth_repo import create_user

    # Сначала легкий orphan
    with _db.SessionLocal() as s:
        v = Vehicle(make_model="OrphanCar", license_plate="O 000",
                    fuel_grade="АИ-95", tank_capacity_l=50.0,
                    base_address="X", fuel_consumption_l_per_100km=10.0,
                    user_id=None)
        s.add(v)
        s.commit()

    # Первый user забирает
    user_a = create_user("a@example.com", "passpass1")
    # Второй регистрируется
    user_b = create_user("b@example.com", "passpass2")

    # Проверяем что orphan ушёл к user_a, а user_b ничего не получил
    with _db.SessionLocal() as s:
        from sqlalchemy import select
        vehicles_a = list(s.execute(select(Vehicle).where(Vehicle.user_id == user_a.id)).scalars())
        vehicles_b = list(s.execute(select(Vehicle).where(Vehicle.user_id == user_b.id)).scalars())
        assert len(vehicles_a) == 1
        assert vehicles_a[0].make_model == "OrphanCar"
        assert len(vehicles_b) == 0
