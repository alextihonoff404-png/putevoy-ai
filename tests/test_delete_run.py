"""Тесты удаления прогона + корректного отката VehicleState."""
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

ROUTES_TO_ADD = [
    ("Санкт-Петербург, Комсомола 19", 12, 3.0),
    ("Санкт-Петербург, Марсово Поле 1", 12, 2.0),
    ("Санкт-Петербург, Смоленская 27", 27, 1.5),
    ("Санкт-Петербург, Московское шоссе, 304", 44, 1.5),
    ("Санкт-Петербург, Новое шоссе, 17", 35, 2.0),
]


@pytest.fixture()
def client(authed_client) -> TestClient:
    c = authed_client
    c.post("/setup", data=SETUP_DATA, follow_redirects=False)
    for addr, km, w in ROUTES_TO_ADD:
        c.post("/routes/add",
               data={"address": addr, "km_one_way": str(km), "weight": str(w)},
               follow_redirects=False)
    return c


def test_delete_run_removes_it_from_dashboard(client: TestClient):
    client.post("/generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15", "2026-04-23"],
        "fueling_liters": ["47.63", "45.69"],
        "fueling_price": ["69.37", "69.26"],
    })
    r = client.get("/dashboard")
    assert "Апрель 2026" in r.text

    r = client.post("/generate/2026/4/delete", follow_redirects=False)
    assert r.status_code == 303

    r = client.get("/dashboard")
    assert "Апрель 2026" not in r.text


def test_delete_last_run_resets_state_to_previous(client: TestClient):
    """Удалили самый поздний прогон → state откатывается на конец предпоследнего."""
    # Сгенерировать апрель
    client.post("/generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15", "2026-04-23"],
        "fueling_liters": ["47.63", "45.69"],
        "fueling_price": ["69.37", "69.26"],
    })
    from putevoy.storage.repo import get_profile
    state_after_april = get_profile()["state"]

    # Сгенерировать май (заглушка — без заправок просто прогон)
    client.post("/generate", data={
        "year": "2026", "month": "5",
        "fueling_date": ["2026-05-15"], "fueling_liters": ["47.5"], "fueling_price": ["69.0"],
    })
    state_after_may = get_profile()["state"]
    assert state_after_may != state_after_april

    # Удаляем май → state должен откатиться до конца апреля
    client.post("/generate/2026/5/delete", follow_redirects=False)
    state_after_delete = get_profile()["state"]
    assert state_after_delete == state_after_april


def test_delete_middle_run_does_not_disturb_state(client: TestClient):
    """Удаление промежуточного прогона не трогает state (он отражает последний)."""
    # Апрель
    client.post("/generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15", "2026-04-23"],
        "fueling_liters": ["47.63", "45.69"],
        "fueling_price": ["69.37", "69.26"],
    })
    # Май
    client.post("/generate", data={
        "year": "2026", "month": "5",
        "fueling_date": ["2026-05-15"], "fueling_liters": ["47.5"], "fueling_price": ["69.0"],
    })
    from putevoy.storage.repo import get_profile
    state_after_may = get_profile()["state"]

    # Удаляем апрель (середина) — state должен остаться как после мая
    client.post("/generate/2026/4/delete", follow_redirects=False)
    state_after_delete = get_profile()["state"]
    assert state_after_delete == state_after_may
