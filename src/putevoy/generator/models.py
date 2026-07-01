"""Pydantic-модели входа/выхода генератора."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field, NonNegativeFloat, PositiveFloat, PositiveInt


class Organization(BaseModel):
    name: str
    mechanic_name: str
    # Юридические реквизиты для шапки путевого листа (ОГРН, адрес, телефон).
    # Опциональны для обратной совместимости со старыми сохранёнными прогонами.
    address: str = ""
    ogrn: str = ""
    phone: str = ""


class Driver(BaseModel):
    full_name: str
    snils: str
    license_number: str
    license_issue_date: date


class Vehicle(BaseModel):
    make_model: str
    license_plate: str
    fuel_grade: str = "АИ-95"
    tank_capacity_l: PositiveFloat = 50.0
    base_address: str


class Route(BaseModel):
    address: str
    km_one_way: PositiveFloat
    consumption_l_one_way: PositiveFloat
    is_large: bool = Field(
        False,
        description="Можно использовать для сжигания излишка топлива (доп. поездки)",
    )
    weight: PositiveFloat = Field(
        1.0,
        description="Относительная частота выбора маршрута в качестве основного на день",
    )


class Fueling(BaseModel):
    date: date
    liters: PositiveFloat
    price_per_l: PositiveFloat
    sum: Optional[NonNegativeFloat] = None

    def total(self) -> float:
        return self.sum if self.sum is not None else round(self.liters * self.price_per_l, 2)


class CarryOver(BaseModel):
    """Состояние, переходящее из предыдущего месяца.

    `last_fuel_balance_l` допускает отрицательные значения, чтобы алгоритм мог
    отработать на заведомо невалидном входе и validators.py это обнаружил.
    """

    last_odometer_km: PositiveInt
    last_fuel_balance_l: float
    last_date: date


class MonthlyInput(BaseModel):
    year: PositiveInt
    month: PositiveInt = Field(..., ge=1, le=12)
    organization: Organization
    driver: Driver
    vehicle: Vehicle
    routes: list[Route]
    fuelings: list[Fueling] = Field(default_factory=list)
    carry_over: CarryOver
    seed: int = 42
    skip_dates: list[date] = Field(
        default_factory=list,
        description="Рабочие дни, которые исключить из генерации (отпуск, праздники сверх календаря, простой)",
    )


class Trip(BaseModel):
    from_address: str
    to_address: str
    km: float
    consumption_l: float
    depart: time
    arrive: time
    direction: Literal["outbound", "inbound"]


class GeneratedDay(BaseModel):
    date: date
    trips: list[Trip]
    fueling: Optional[Fueling] = None
    odometer_start: int
    odometer_end: int
    fuel_balance_start: float
    fuel_balance_end: float
    release_datetime: datetime
    return_datetime: datetime

    @property
    def trip_count(self) -> int:
        return len(self.trips) // 2

    @property
    def total_km(self) -> float:
        return sum(t.km for t in self.trips)

    @property
    def total_consumption_l(self) -> float:
        return round(sum(t.consumption_l for t in self.trips), 4)


class MonthlyOutput(BaseModel):
    input: MonthlyInput
    days: list[GeneratedDay]
    final_state: CarryOver
