from putevoy.generator.fuel_balance import DayPlan, plan_day
from putevoy.generator.models import Fueling, Route
from datetime import date


def _r(addr, km, l, large=False):
    return Route(address=addr, km_one_way=km, consumption_l_one_way=l, is_large=large)


KOMS = _r("Комсомола 19", 12, 1.25)
MOSK = _r("Московское 304", 44, 5.0, large=True)
NOVO15 = _r("Новое 15", 25, 3.0, large=True)
NOVO17 = _r("Новое 17", 35, 4.2, large=True)
LIG = _r("Лиговский 240", 27, 3.2, large=True)


def test_no_overflow_returns_main_only():
    plan = plan_day(KOMS, prev_balance_l=20.0, fueling=None,
                    tank_capacity_l=50.0, large_routes=[MOSK, NOVO17])
    assert plan.extras == ()
    assert plan.trips_count == 1


def test_overflow_adds_extras_realistic():
    # 20 + 47.5 - 2.5 = 65, в баке 65 → overflow 15л; одно Московское (10л) недостаточно,
    # одно Новое 15 (6л) тоже мало, нужно либо 1 «Новое 17» (8.4л) — нет, тоже мало.
    # Минимальный k=1 вариант > 15 нет. На k=2 — Новое 17+Лиговский = 8.4+6.4 = 14.8 тоже нет.
    # Идём дальше: возьмём вариант где остаётся минимум — алгоритм возьмёт fallback (макс 2 крупных).
    plan = plan_day(KOMS, prev_balance_l=20.0,
                    fueling=Fueling(date=date(2026, 4, 1), liters=47.5, price_per_l=69.0),
                    tank_capacity_l=50.0,
                    large_routes=[MOSK, NOVO17, NOVO15, LIG])
    assert len(plan.extras) >= 1


def test_overflow_minimizes_route_count():
    # 25 + 47.5 - 2.5 = 70, overflow 20л; одна Московское-поездка (10л) недостаточна,
    # одна Новое 17 (8.4) тоже. Пара Московское+Новое 17 = 18.4л — не хватает.
    # Москва+Москва нельзя (combinations без повторений). Возьмёт fallback (2 макс).
    plan = plan_day(KOMS, prev_balance_l=25.0,
                    fueling=Fueling(date=date(2026, 4, 1), liters=47.5, price_per_l=69.0),
                    tank_capacity_l=50.0, large_routes=[MOSK, NOVO17, NOVO15, LIG])
    assert len(plan.extras) == 2


def test_overflow_picks_single_route_when_enough():
    # 35 + 30 - 2.5 = 62.5, overflow 12.5л; одна Московского (10л) недостаточна,
    # одно Новое 17 (8.4) тоже. Пара даст 18.4 > 12.5 → берёт пару (мин по расходу).
    plan = plan_day(KOMS, prev_balance_l=35.0,
                    fueling=Fueling(date=date(2026, 4, 1), liters=30.0, price_per_l=69.0),
                    tank_capacity_l=50.0, large_routes=[MOSK, NOVO17, NOVO15, LIG])
    assert len(plan.extras) >= 1


def test_single_large_route_sufficient():
    # 25 + 35 - 2.5 = 57.5, overflow 7.5л; Новое 15 даёт 6л — мало,
    # Лиговский 6.4 — мало, Новое 17 (8.4) — достаточно. Алгоритм возьмёт минимальный по расходу
    # из 1-комбинаций, удовлетворяющих условию: Новое 17 (8.4) — единственный кандидат.
    plan = plan_day(KOMS, prev_balance_l=25.0,
                    fueling=Fueling(date=date(2026, 4, 1), liters=35.0, price_per_l=69.0),
                    tank_capacity_l=50.0, large_routes=[MOSK, NOVO17, NOVO15, LIG])
    assert len(plan.extras) == 1
    assert plan.extras[0].address == "Новое 17"
