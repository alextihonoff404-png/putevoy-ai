from datetime import date

from putevoy.generator.generate import generate_month, generate_month_auto_seed
from putevoy.generator.models import (
    CarryOver, Driver, Fueling, MonthlyInput, Organization, Route, Vehicle,
)
from putevoy.generator.validators import validate


def _make_input(carry_balance: float, fuelings: list[Fueling]) -> MonthlyInput:
    routes = [
        Route(address="Санкт-Петербург, Комсомола 19", km_one_way=12, consumption_l_one_way=1.25),
        Route(address="Санкт-Петербург, Марсово Поле 1", km_one_way=12, consumption_l_one_way=1.25),
        Route(address="Санкт-Петербург, Смоленская 27", km_one_way=27, consumption_l_one_way=3.2, is_large=True),
        Route(address="Санкт-Петербург, Московское шоссе, 304", km_one_way=44, consumption_l_one_way=5.0, is_large=True),
    ]
    return MonthlyInput(
        year=2026, month=4, seed=42,
        organization=Organization(name="ООО «ИИС»", mechanic_name="Павлов В.О."),
        driver=Driver(full_name="Тихонов А.Ю.", snils="098-274-108 00",
                      license_number="99 19 №306940", license_issue_date=date(2020, 10, 23)),
        vehicle=Vehicle(make_model="CS55plus", license_plate="Н960ХА 198",
                        tank_capacity_l=50, base_address="Санкт-Петербург, Репищева 10"),
        routes=routes, fuelings=fuelings,
        carry_over=CarryOver(last_odometer_km=49874, last_fuel_balance_l=carry_balance,
                             last_date=date(2026, 3, 31)),
    )


def test_validator_clean_run_passes():
    inp = _make_input(carry_balance=45.0, fuelings=[
        Fueling(date=date(2026, 4, 7), liters=45, price_per_l=69),
        Fueling(date=date(2026, 4, 21), liters=45, price_per_l=69),
    ])
    # В реальности используется auto_seed — он перебирает seeds и находит валидный.
    res = generate_month_auto_seed(inp)
    rep = validate(res.output)
    neg = [i for i in rep.issues if i.code == "FUEL_NEGATIVE"]
    assert not neg, [i.message for i in neg]


def test_validator_catches_negative_balance():
    inp = _make_input(carry_balance=2.0, fuelings=[])
    rep = validate(generate_month(inp))
    assert not rep.ok
    assert any(i.code == "FUEL_NEGATIVE" for i in rep.issues)
