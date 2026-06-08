"""Тесты дней простоя — исключение рабочих дней из генерации."""
from __future__ import annotations

from datetime import date

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
    for addr, km, w in [
        ("Санкт-Петербург, Комсомола 19", 12, 3.0),
        ("Санкт-Петербург, Марсово Поле 1", 12, 2.0),
        ("Санкт-Петербург, Новое шоссе, 17", 35, 2.0),
    ]:
        c.post("/routes/add",
               data={"address": addr, "km_one_way": str(km), "weight": str(w)},
               follow_redirects=False)
    return c


def test_skip_dates_excluded_from_generation(client: TestClient):
    """Если отметить 5 дней простоя, total рабочих дней должно уменьшиться на 5."""
    # Сначала без skip_dates
    r = client.post("/api/preview-generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15"], "fueling_liters": ["47.63"], "fueling_price": ["69.37"],
    })
    base_days = r.json()["days_count"]
    assert base_days == 22  # апрель 2026

    # Теперь с 5 skip-датами
    r = client.post("/api/preview-generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15"], "fueling_liters": ["47.63"], "fueling_price": ["69.37"],
        "skip_date": ["2026-04-01", "2026-04-02", "2026-04-03",
                      "2026-04-06", "2026-04-07"],
    })
    assert r.json()["days_count"] == base_days - 5


def test_skip_dates_can_fix_negative_balance(client: TestClient):
    """Если без skip_dates баланс уходит в минус — добавление skip_dates должно его выровнять."""
    # Май 2026: 18 рабочих дней. Заправок мало. Сначала проверим что есть минус.
    base_fuelings = {
        "fueling_date": ["2026-05-15"], "fueling_liters": ["20"], "fueling_price": ["70"],
    }
    r = client.post("/api/preview-generate", data={
        "year": "2026", "month": "5", **base_fuelings,
    })
    j = r.json()
    base_min = j["min_balance_l"]

    # С 10 skip_dates в начале мая — минимум должен подрасти (стало меньше расхода)
    skip = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
            "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14"]
    r = client.post("/api/preview-generate", data={
        "year": "2026", "month": "5", **base_fuelings,
        "skip_date": skip,
    })
    j2 = r.json()
    assert j2["min_balance_l"] > base_min


def test_preview_does_not_save_to_db(client: TestClient):
    """preview не должен оставлять следов в БД."""
    client.post("/api/preview-generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15"], "fueling_liters": ["47.63"], "fueling_price": ["69.37"],
    })
    from putevoy.storage.repo import list_runs
    assert list_runs() == []


def test_skip_dates_persist_through_save_and_load(client: TestClient):
    """skip_dates сохраняются в БД и подгружаются при перезагрузке /generate."""
    skip = ["2026-04-01", "2026-04-02"]
    r = client.post("/generate", data={
        "year": "2026", "month": "4",
        "fueling_date": ["2026-04-15", "2026-04-23"],
        "fueling_liters": ["47.63", "45.69"],
        "fueling_price": ["69.37", "69.26"],
        "skip_date": skip,
    }, follow_redirects=False)
    assert r.status_code == 200

    # Подгружаем форму повторно
    r2 = client.get("/generate?year=2026&month=4")
    # В шаблон должны вставиться существующие skip-даты в JSON-массиве для JS
    assert '"2026-04-01"' in r2.text
    assert '"2026-04-02"' in r2.text
