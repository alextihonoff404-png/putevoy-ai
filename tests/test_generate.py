from datetime import date

from putevoy.generator.generate import generate_month
from putevoy.generator.models import (
    CarryOver, Driver, Fueling, MonthlyInput, Organization, Route, Vehicle,
)


def _routes():
    return [
        Route(address="Санкт-Петербург, Комсомола 19", km_one_way=12, consumption_l_one_way=1.25),
        Route(address="Санкт-Петербург, Марсово Поле 1", km_one_way=12, consumption_l_one_way=1.25),
        Route(address="Санкт-Петербург, Смоленская 27", km_one_way=27, consumption_l_one_way=3.2, is_large=True),
        Route(address="Санкт-Петербург, Московское шоссе, 304", km_one_way=44, consumption_l_one_way=5.0, is_large=True),
        Route(address="Санкт-Петербург, пр. Юрия Гагарина 26", km_one_way=35, consumption_l_one_way=4.2, is_large=True),
        Route(address="Санкт-Петербург, Новое шоссе, 15", km_one_way=25, consumption_l_one_way=3.0, is_large=True),
        Route(address="Санкт-Петербург, Новое шоссе, 17", km_one_way=35, consumption_l_one_way=4.2, is_large=True),
        Route(address="Санкт-Петербург, Штурманская 19В", km_one_way=40, consumption_l_one_way=4.8, is_large=True),
        Route(address="Санкт-Петербург, Лиговский 240", km_one_way=27, consumption_l_one_way=3.2, is_large=True),
    ]


def _input_april():
    return MonthlyInput(
        year=2026, month=4, seed=42,
        organization=Organization(name="ООО «ИИС»", mechanic_name="Павлов В.О."),
        driver=Driver(full_name="Тихонов А.Ю.", snils="098-274-108 00",
                      license_number="99 19 №306940", license_issue_date=date(2020, 10, 23)),
        vehicle=Vehicle(make_model="Changan CS55plus", license_plate="Н960ХА 198",
                        tank_capacity_l=50, base_address="Санкт-Петербург, Репищева 10"),
        routes=_routes(),
        fuelings=[
            Fueling(date=date(2026, 4, 15), liters=47.63, price_per_l=69.37),
            Fueling(date=date(2026, 4, 23), liters=45.69, price_per_l=69.26),
        ],
        carry_over=CarryOver(
            last_odometer_km=49874,  # подставим заведомое (уточним по реальным файлам в golden-тесте)
            last_fuel_balance_l=33.87, last_date=date(2026, 3, 31),
        ),
    )


def test_april_22_working_days():
    out = generate_month(_input_april())
    assert len(out.days) == 22


def test_no_balance_exceeds_tank():
    out = generate_month(_input_april())
    for d in out.days:
        assert d.fuel_balance_end <= 50 + 1e-6, f"{d.date}: balance_end={d.fuel_balance_end}"
        assert d.fuel_balance_start <= 50 + 1e-6, f"{d.date}: balance_start={d.fuel_balance_start}"


def test_odometer_continuous():
    out = generate_month(_input_april())
    for i in range(1, len(out.days)):
        assert out.days[i].odometer_start == out.days[i - 1].odometer_end


def test_time_within_21():
    from datetime import time
    out = generate_month(_input_april())
    for d in out.days:
        assert d.return_datetime.time() <= time(21, 0), \
            f"{d.date}: возврат {d.return_datetime} позже 21:00"


def test_max_4_trips():
    out = generate_month(_input_april())
    for d in out.days:
        # одна поездка = 2 trip-объекта (туда/обратно)
        assert len(d.trips) // 2 <= 4, f"{d.date}: {len(d.trips) // 2} поездок"
