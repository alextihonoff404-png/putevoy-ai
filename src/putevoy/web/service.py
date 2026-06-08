"""Сервисный слой: связь между web-роутами и storage + generator."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from ..generator.generate import generate_month_auto_seed, AutoSeedResult
from ..generator.models import (
    CarryOver, Driver, Fueling, MonthlyInput, MonthlyOutput,
    Organization, Route as RouteDomain, Vehicle,
)
from ..generator.validators import ValidationReport, validate
from ..generator.writers.fuel_log_builder import build_fuel_log
from ..generator.writers.waybill_writer import write_waybills
from ..parsing.fueling_parser import parse_fuelings
from ..storage import db as _db
from ..storage.models import MonthlyRun as DBRun
from ..storage.repo import (
    get_profile, list_routes, list_runs, load_run, save_run,
)

BUILTIN_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "builtin_templates" / "preset_mintrans_390_v1.xlsx"
)

# Порог «крупности» маршрута — расход за круг (туда+обратно) в литрах.
# Маршруты, расходующие >= этого порога, доступны системе для добавления
# в качестве дополнительных поездок, когда нужно сжечь излишек топлива.
LARGE_ROUTE_THRESHOLD_L = 5.0


def _routes_to_domain() -> list[RouteDomain]:
    profile = get_profile()
    if not profile:
        return []
    consumption_per_100 = profile["vehicle"]["fuel_consumption_l_per_100km"]
    result = []
    for r in list_routes():
        consumption_one_way = round(r.km_one_way * consumption_per_100 / 100, 4)
        # Автоматически определяем «крупность» по расходу за круг
        is_large_auto = (consumption_one_way * 2) >= LARGE_ROUTE_THRESHOLD_L
        result.append(RouteDomain(
            address=r.address, km_one_way=r.km_one_way,
            consumption_l_one_way=consumption_one_way,
            is_large=is_large_auto, weight=r.weight,
        ))
    return result


def _carry_over_for_month(year: int, month: int) -> CarryOver:
    """Если прогон этого месяца уже был — взять состояние ДО него (день 0).
    Иначе — текущий VehicleState из профиля."""
    profile = get_profile()
    if not profile:
        raise RuntimeError("Профиль не настроен")
    with _db.SessionLocal() as s:
        existing = s.execute(
            select(DBRun).where(DBRun.year == year, DBRun.month == month)
        ).scalar_one_or_none()
        if existing and existing.days:
            first = existing.days[0]
            return CarryOver(
                last_odometer_km=first.odometer_start,
                last_fuel_balance_l=first.fuel_balance_start,
                last_date=date(year, month, 1),
            )
    st = profile["state"]
    return CarryOver(
        last_odometer_km=st["current_odometer_km"],
        last_fuel_balance_l=st["current_fuel_balance_l"],
        last_date=st["last_date"],
    )


def build_monthly_input(year: int, month: int, fuelings: list[Fueling],
                        skip_dates: list = None,
                        seed: int = 1) -> MonthlyInput:
    profile = get_profile()
    if not profile:
        raise RuntimeError("Профиль не настроен")
    routes = _routes_to_domain()
    if not routes:
        raise RuntimeError("Каталог адресов пуст — добавьте маршруты")
    return MonthlyInput(
        year=year, month=month, seed=seed,
        organization=Organization(**profile["organization"]),
        driver=Driver(**profile["driver"]),
        vehicle=Vehicle(**profile["vehicle"]),
        routes=routes, fuelings=fuelings,
        carry_over=_carry_over_for_month(year, month),
        skip_dates=skip_dates or [],
    )


def run_and_persist(year: int, month: int,
                    fuelings: list[Fueling],
                    skip_dates: list = None) -> tuple[AutoSeedResult, ValidationReport]:
    """Запустить генерацию, сохранить в БД, обновить состояние ТС."""
    inp = build_monthly_input(year, month, fuelings, skip_dates=skip_dates)
    result = generate_month_auto_seed(inp)
    report = validate(result.output)
    save_run(result.output, result.seed_used, report.ok, report.model_dump_json())
    return result, report


def preview_run(year: int, month: int,
                fuelings: list[Fueling],
                skip_dates: list = None) -> tuple[AutoSeedResult, ValidationReport]:
    """То же, что run_and_persist, но БЕЗ сохранения в БД (для интерактивного UI)."""
    inp = build_monthly_input(year, month, fuelings, skip_dates=skip_dates)
    result = generate_month_auto_seed(inp)
    report = validate(result.output)
    return result, report


def get_existing_fuelings(year: int, month: int) -> list[Fueling]:
    """Если этот месяц уже генерировался — вернуть его заправки. Иначе пусто."""
    out = load_run(year, month)
    if not out:
        return []
    return list(out.input.fuelings)


def get_existing_skip_dates(year: int, month: int) -> list:
    """Если этот месяц уже генерировался — вернуть его skip_dates. Иначе пусто."""
    out = load_run(year, month)
    if not out:
        return []
    return list(out.input.skip_dates)


def write_waybill_for_run(run_year: int, run_month: int, out_dir: Path) -> Optional[Path]:
    out = load_run(run_year, run_month)
    if not out:
        return None
    from ..generator.calendar import MONTH_NOMINATIVE_RU
    fname = f"{run_month:02d}__Путевой_лист_{MONTH_NOMINATIVE_RU[run_month].lower()}_{run_year}.xlsx"
    out_path = out_dir / fname
    write_waybills(
        template_path=BUILTIN_TEMPLATE,
        output_path=out_path,
        out=out,
    )
    return out_path


def write_fuel_log_for_month(run_year: int, run_month: int, out_dir: Path) -> Optional[Path]:
    """Журнал учёта топлива за один месяц."""
    out = load_run(run_year, run_month)
    if not out:
        return None
    profile = get_profile()
    if not profile:
        return None
    from ..generator.calendar import MONTH_NOMINATIVE_RU
    # carry_over баланс ДО этого месяца
    co_balance = out.days[0].fuel_balance_start if out.days else profile["state"]["current_fuel_balance_l"]
    fname = f"Журнал_учета_топлива_{MONTH_NOMINATIVE_RU[run_month].lower()}_{run_year}.xlsx"
    out_path = out_dir / fname
    build_fuel_log(out_path=out_path, months=[out], initial_balance_l=co_balance)
    return out_path


def write_full_fuel_log(out_dir: Path) -> Optional[Path]:
    """Накопительный журнал по всем сохранённым прогонам."""
    profile = get_profile()
    if not profile:
        return None
    runs = list_runs()
    if not runs:
        return None
    # Отсортируем по году+месяцу
    runs_sorted = sorted(runs, key=lambda r: (r.year, r.month))
    domain_outputs = [load_run(r.year, r.month) for r in runs_sorted]
    domain_outputs = [o for o in domain_outputs if o is not None]
    if not domain_outputs:
        return None
    initial = domain_outputs[0].days[0].fuel_balance_start if domain_outputs[0].days else 0
    out_path = out_dir / "Журнал_учета_топлива_полная_история.xlsx"
    build_fuel_log(out_path=out_path, months=domain_outputs, initial_balance_l=initial)
    return out_path
