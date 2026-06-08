"""Тесты, что multi-vehicle не путает данные между автомобилями.

Главный регресс-кейс: при сохранении /setup с активным ТС-2 данные ТС-1
оставались без изменений (раньше save_setup всегда писал в первое ТС).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


SETUP_DATA = {
    "organization_name": "ООО ИИС", "mechanic_name": "Павлов В.О.",
    "driver_full_name": "Тихонов А.Ю.", "driver_snils": "098-274-108 00",
    "driver_license_number": "99 19 №306940", "driver_license_issue_date": "2020-10-23",
    "vehicle_make_model": "Changan CS55plus", "vehicle_license_plate": "Н960ХА 198",
    "vehicle_fuel_grade": "АИ-95", "vehicle_tank_capacity_l": "50",
    "base_city": "Санкт-Петербург",
    "base_street_type": "улица",
    "base_street_name": "Репищева",
    "base_house_number": "10",
    "base_corpus": "",
    "vehicle_fuel_consumption_l_per_100km": "10.4",
    "start_odometer_km": "49898", "start_fuel_balance_l": "31.37",
    "start_date": "2026-03-31",
}


@pytest.fixture()
def client(authed_client) -> TestClient:
    c = authed_client
    c.post("/setup", data=SETUP_DATA, follow_redirects=False)
    # Добавляем второе ТС — становится активным
    c.post("/vehicles/add", data={
        "make_model": "Lada Vesta", "license_plate": "А123БВ 178",
        "fuel_grade": "АИ-92", "tank_capacity_l": "55",
        "base_address": "СПб, Невский 100",
        "fuel_consumption_l_per_100km": "8.5",
        "start_odometer_km": "15000", "start_fuel_balance_l": "10",
        "start_date": "2026-03-31",
    }, follow_redirects=False)
    return c


def test_setup_edits_active_vehicle_not_first(client: TestClient):
    """Регресс: при активном ТС-2 /setup должен редактировать ТС-2, а не ТС-1."""
    from putevoy.storage.repo import list_vehicles, current_vehicle_id
    assert current_vehicle_id() == 2  # после vehicles/add активным стал второй

    # Через /setup меняем имя — должно поменяться у активного (ТС-2)
    new_data = {**SETUP_DATA, "vehicle_make_model": "Lada Vesta UPDATED",
                "vehicle_license_plate": "А999ЯЯ 199"}
    client.post("/setup", data=new_data, follow_redirects=False)

    vehicles = {v.id: v for v in list_vehicles()}
    assert vehicles[1].make_model == "Changan CS55plus", "Первое ТС не должно было поменяться"
    assert vehicles[2].make_model == "Lada Vesta UPDATED", "Второе ТС должно было обновиться"


def test_routes_isolated_between_vehicles(client: TestClient):
    """Маршруты ТС-1 не видны на ТС-2 и наоборот."""
    from putevoy.storage.repo import list_routes, set_active_vehicle

    # Сейчас активно ТС-2, добавляем ему маршрут
    client.post("/routes/add", data={
        "address": "Маршрут для Лады", "km_one_way": "20", "weight": "1.0",
    }, follow_redirects=False)
    addrs_v2 = {r.address for r in list_routes()}
    assert "Маршрут для Лады" in addrs_v2

    # Переключаемся на ТС-1, у него маршрутов быть не должно
    set_active_vehicle(1)
    addrs_v1 = {r.address for r in list_routes()}
    assert "Маршрут для Лады" not in addrs_v1


def test_runs_isolated_between_vehicles(client: TestClient):
    """Прогон ТС-2 не показывается в истории ТС-1."""
    from putevoy.storage.repo import list_runs, set_active_vehicle

    # Добавим маршрут в ТС-2 и сгенерируем прогон
    client.post("/routes/add", data={
        "address": "Маршрут для Лады", "km_one_way": "20", "weight": "1.0",
    }, follow_redirects=False)
    client.post("/generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15"], "fueling_liters": ["30"], "fueling_price": ["70"],
    }, follow_redirects=False)
    assert len(list_runs()) == 1

    # Переключение на ТС-1 — прогонов ноль
    set_active_vehicle(1)
    assert len(list_runs()) == 0
