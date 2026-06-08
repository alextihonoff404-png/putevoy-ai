"""Центральная функция генерации месяца — чистая, без I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .calendar import working_days
from .fuel_balance import DayPlan, plan_day
from .models import CarryOver, GeneratedDay, MonthlyInput, MonthlyOutput, Trip
from .route_planner import assign_main_routes, assign_main_routes_budget_aware
from .trip_scheduler import trip_times

DEFAULT_TARGET_END_BALANCE_L = 2.0


@dataclass
class AutoSeedResult:
    output: MonthlyOutput
    seed_used: int
    attempts: int


def generate_month(inp: MonthlyInput, budget_aware: bool = True) -> MonthlyOutput:
    days = working_days(inp.year, inp.month)
    # Исключаем дни простоя (отпуск, праздники, командировка и т.д.)
    if inp.skip_dates:
        skip_set = set(inp.skip_dates)
        days = [d for d in days if d not in skip_set]
    if budget_aware:
        main_routes = assign_main_routes_budget_aware(
            days=days,
            routes=inp.routes,
            fuelings=inp.fuelings,
            start_balance_l=inp.carry_over.last_fuel_balance_l,
            target_end_balance_l=DEFAULT_TARGET_END_BALANCE_L,
            seed=inp.seed,
        )
    else:
        main_routes = assign_main_routes(days, inp.routes, seed=inp.seed)
    large_routes = [r for r in inp.routes if r.is_large]
    base = inp.vehicle.base_address

    balance = inp.carry_over.last_fuel_balance_l
    odometer = inp.carry_over.last_odometer_km
    last_date = inp.carry_over.last_date

    generated: list[GeneratedDay] = []

    fueling_map = {f.date: f for f in inp.fuelings}

    for d in days:
        main = main_routes[d]
        fueling = fueling_map.get(d)
        plan: DayPlan = plan_day(
            main=main,
            prev_balance_l=balance,
            fueling=fueling,
            tank_capacity_l=inp.vehicle.tank_capacity_l,
            large_routes=large_routes,
        )

        trips: list[Trip] = []
        odo_start = odometer
        for trip_idx, route in enumerate([plan.main, *plan.extras]):
            t_out_dep, t_out_arr, t_in_dep, t_in_arr = trip_times(trip_idx)
            trips.append(Trip(
                from_address=base, to_address=route.address,
                km=route.km_one_way, consumption_l=route.consumption_l_one_way,
                depart=t_out_dep, arrive=t_out_arr, direction="outbound",
            ))
            trips.append(Trip(
                from_address=route.address, to_address=base,
                km=route.km_one_way, consumption_l=route.consumption_l_one_way,
                depart=t_in_dep, arrive=t_in_arr, direction="inbound",
            ))

        total_km = int(round(plan.total_km))
        total_burn = plan.total_consumption_l
        odometer = odo_start + total_km

        balance_start = balance
        fueled_l = fueling.liters if fueling else 0.0
        balance_end = round(balance_start + fueled_l - total_burn, 4)
        balance = balance_end

        first_trip_depart = trips[0].depart
        last_trip_arrive = trips[-1].arrive
        release_dt = datetime.combine(d, first_trip_depart)
        return_dt = datetime.combine(d, last_trip_arrive)

        generated.append(GeneratedDay(
            date=d,
            trips=trips,
            fueling=fueling,
            odometer_start=odo_start,
            odometer_end=odometer,
            fuel_balance_start=balance_start,
            fuel_balance_end=balance_end,
            release_datetime=release_dt,
            return_datetime=return_dt,
        ))
        last_date = d

    return MonthlyOutput(
        input=inp,
        days=generated,
        final_state=CarryOver(
            last_odometer_km=odometer,
            last_fuel_balance_l=balance,
            last_date=last_date,
        ),
    )


def generate_month_auto_seed(
    inp: MonthlyInput,
    max_attempts: int = 500,
    target_min_balance_l: float = 0.5,
) -> AutoSeedResult:
    """Перебрать seeds, найти первый, дающий валидный месяц.

    Валидный = ни одного дня с отрицательным остатком и ни одного с переполнением бака.
    `target_min_balance_l` — желаемый минимальный остаток в конце месяца
    (чтобы алгоритм не оставлял пустой бак на грани, что хрупко при изменениях).
    """
    from .validators import validate

    best_seed = inp.seed
    best_out: MonthlyOutput | None = None
    best_neg_count = 10**9

    for attempt in range(max_attempts):
        trial_seed = inp.seed + attempt
        trial_inp = inp.model_copy(update={"seed": trial_seed})
        out = generate_month(trial_inp)
        report = validate(out)
        critical = [
            i for i in report.issues
            if i.code in ("FUEL_NEGATIVE", "TANK_OVERFLOW")
        ]
        if not critical and out.final_state.last_fuel_balance_l >= target_min_balance_l:
            return AutoSeedResult(output=out, seed_used=trial_seed, attempts=attempt + 1)
        # Считаем количество критических — фоллбэк на минимум проблем
        neg_count = len([i for i in critical if i.code == "FUEL_NEGATIVE"])
        if neg_count < best_neg_count:
            best_neg_count = neg_count
            best_seed = trial_seed
            best_out = out

    assert best_out is not None
    return AutoSeedResult(output=best_out, seed_used=best_seed, attempts=max_attempts)
