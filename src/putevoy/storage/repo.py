"""Высокоуровневый репозиторий — методы для веб-приложения.

Multi-vehicle: большинство функций работает в контексте «активного» ТС.
Активный vehicle_id хранится в Profile.active_vehicle_id.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select

from ..generator.models import (
    CarryOver, Driver as DriverModel, Fueling, MonthlyInput,
    Organization, Route as RouteModel, Vehicle as VehicleModel,
    MonthlyOutput, GeneratedDay as DomainDay, Trip,
)
from . import db as _db
from .models import (
    Base, Driver, FuelingRecord, GeneratedDay as DBDay, MonthlyRun,
    Profile, Route, Vehicle, VehicleState,
)
from .user_context import get_current_user_id


def _Session():
    """Динамическая ссылка на текущий SessionLocal — устойчива к подмене в тестах."""
    return _db.SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(_db.engine)
    _ensure_new_columns()


def _ensure_new_columns() -> None:
    """Простая миграция: добавить колонки в существующие таблицы."""
    from sqlalchemy import text
    additions = [
        ("monthly_run", "skip_dates_json", "TEXT"),
        ("monthly_run", "vehicle_id", "INTEGER DEFAULT 1"),
        ("route", "vehicle_id", "INTEGER DEFAULT 1"),
        ("vehicle_state", "vehicle_id", "INTEGER"),
        ("profile", "active_vehicle_id", "INTEGER"),
        # Per-user изоляция:
        ("profile", "user_id", "INTEGER"),
        ("driver", "user_id", "INTEGER"),
        ("vehicle", "user_id", "INTEGER"),
    ]
    with _db.engine.begin() as conn:
        for table, col, col_type in additions:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if col not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        conn.execute(text(
            "UPDATE vehicle_state SET vehicle_id = 1 WHERE vehicle_id IS NULL"
        ))
        conn.execute(text(
            "UPDATE profile SET active_vehicle_id = 1 WHERE active_vehicle_id IS NULL"
        ))


# --- Helpers: профиль/водитель текущего user --------------------------------

def _profile_for_user(session, user_id: int) -> Optional[Profile]:
    """Найти Profile залогиненного user. Legacy-данные (user_id IS NULL) тоже отдаём,
    если ни одного не привязано — это означает что миграция ещё не отработала.
    Делается ровно один раз при первой регистрации в auth_repo.create_user.
    """
    return session.execute(
        select(Profile).where(Profile.user_id == user_id)
    ).scalar_one_or_none()


def _driver_for_user(session, user_id: int) -> Optional[Driver]:
    return session.execute(
        select(Driver).where(Driver.user_id == user_id)
    ).scalar_one_or_none()


# --- Профиль и активное ТС --------------------------------------------------

def has_profile() -> bool:
    """Есть ли первичная настройка для текущего user: organization + driver + хотя бы одно ТС с состоянием."""
    uid = get_current_user_id()
    if not uid:
        return False
    with _Session() as s:
        p = _profile_for_user(s, uid)
        d = _driver_for_user(s, uid)
        if not (p and d):
            return False
        any_vehicle = s.execute(
            select(Vehicle).where(Vehicle.user_id == uid)
        ).scalars().first()
        if not any_vehicle:
            return False
        any_state = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == any_vehicle.id)
        ).scalars().first()
        return bool(any_state)


def current_vehicle_id() -> Optional[int]:
    """ID активного ТС текущего user из Profile.active_vehicle_id.

    Если не задан — берём минимальный по id среди ТС user'а.
    """
    uid = get_current_user_id()
    if not uid:
        return None
    with _Session() as s:
        p = _profile_for_user(s, uid)
        if p and p.active_vehicle_id:
            # Защита: убедимся, что active_vehicle действительно принадлежит user'у
            v = s.execute(
                select(Vehicle).where(
                    Vehicle.id == p.active_vehicle_id,
                    Vehicle.user_id == uid,
                )
            ).scalar_one_or_none()
            if v:
                return v.id
        first = s.execute(
            select(Vehicle).where(Vehicle.user_id == uid).order_by(Vehicle.id)
        ).scalars().first()
        return first.id if first else None


def set_active_vehicle(vehicle_id: int) -> None:
    uid = get_current_user_id()
    if not uid:
        return
    with _Session() as s:
        p = _profile_for_user(s, uid)
        if not p:
            return
        # ТС должно принадлежать тому же user'у
        v = s.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if not v:
            return
        p.active_vehicle_id = vehicle_id
        s.commit()


def save_setup(
    organization_name: str, mechanic_name: str,
    driver_full_name: str, driver_snils: str,
    driver_license_number: str, driver_license_issue_date: date,
    vehicle_make_model: str, vehicle_license_plate: str,
    vehicle_fuel_grade: str, vehicle_tank_capacity_l: float,
    vehicle_base_address: str, vehicle_fuel_consumption_l_per_100km: float,
    start_odometer_km: int, start_fuel_balance_l: float, start_date: date,
    vehicle_id: Optional[int] = None,
) -> int:
    """Первичная настройка / редактирование ТС для текущего user'а.

    Если vehicle_id передан — обновляем существующее ТС (должно принадлежать user).
    Если нет — создаём ПЕРВОЕ ТС user'а (используется в мастере /setup).
    Возвращает id созданного/обновлённого ТС.
    """
    uid = get_current_user_id()
    if not uid:
        raise RuntimeError("Нет залогиненного пользователя")
    with _Session() as s:
        # Profile: один на user. Создаём если нет.
        p = _profile_for_user(s, uid)
        if not p:
            p = Profile(user_id=uid)
            s.add(p)
        p.organization_name = organization_name
        p.mechanic_name = mechanic_name

        # Driver: один на user. Создаём если нет.
        d = _driver_for_user(s, uid)
        if not d:
            d = Driver(user_id=uid)
            s.add(d)
        d.full_name = driver_full_name
        d.snils = driver_snils
        d.license_number = driver_license_number
        d.license_issue_date = driver_license_issue_date

        if vehicle_id is not None:
            v = s.execute(
                select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
            ).scalar_one_or_none()
            if not v:
                # Не нашли — создаём новое привязанное к user
                v = Vehicle(user_id=uid)
        else:
            # Если у user уже есть ТС — берём первое, иначе создаём
            v = s.execute(
                select(Vehicle).where(Vehicle.user_id == uid).order_by(Vehicle.id)
            ).scalars().first()
            if not v:
                v = Vehicle(user_id=uid)
        v.make_model = vehicle_make_model
        v.license_plate = vehicle_license_plate
        v.fuel_grade = vehicle_fuel_grade
        v.tank_capacity_l = vehicle_tank_capacity_l
        v.base_address = vehicle_base_address
        v.fuel_consumption_l_per_100km = vehicle_fuel_consumption_l_per_100km
        v.user_id = uid  # на всякий случай — гарантируем привязку
        s.add(v)
        s.flush()  # чтобы v.id заполнился

        # VehicleState для этого ТС
        st = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == v.id)
        ).scalar_one_or_none()
        if not st:
            st = VehicleState(vehicle_id=v.id)
        st.current_odometer_km = start_odometer_km
        st.current_fuel_balance_l = start_fuel_balance_l
        st.last_date = start_date
        s.add(st)

        # Если активного ТС нет — делаем активным это
        if not p.active_vehicle_id:
            p.active_vehicle_id = v.id

        s.commit()
        return v.id


def add_vehicle(
    make_model: str, license_plate: str, fuel_grade: str,
    tank_capacity_l: float, base_address: str,
    fuel_consumption_l_per_100km: float,
    start_odometer_km: int, start_fuel_balance_l: float, start_date: date,
) -> int:
    """Добавить ещё одно ТС для текущего user'а. Активное не меняем — переключение отдельно."""
    uid = get_current_user_id()
    if not uid:
        raise RuntimeError("Нет залогиненного пользователя")
    with _Session() as s:
        v = Vehicle(
            user_id=uid,
            make_model=make_model, license_plate=license_plate,
            fuel_grade=fuel_grade, tank_capacity_l=tank_capacity_l,
            base_address=base_address,
            fuel_consumption_l_per_100km=fuel_consumption_l_per_100km,
        )
        s.add(v)
        s.flush()
        st = VehicleState(
            vehicle_id=v.id,
            current_odometer_km=start_odometer_km,
            current_fuel_balance_l=start_fuel_balance_l,
            last_date=start_date,
        )
        s.add(st)
        s.commit()
        return v.id


def update_vehicle(
    vehicle_id: int,
    make_model: str, license_plate: str, fuel_grade: str,
    tank_capacity_l: float, base_address: str,
    fuel_consumption_l_per_100km: float,
) -> None:
    """Редактировать ТС (без изменения состояния). Только своё ТС."""
    uid = get_current_user_id()
    if not uid:
        return
    with _Session() as s:
        v = s.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if not v:
            return
        v.make_model = make_model
        v.license_plate = license_plate
        v.fuel_grade = fuel_grade
        v.tank_capacity_l = tank_capacity_l
        v.base_address = base_address
        v.fuel_consumption_l_per_100km = fuel_consumption_l_per_100km
        s.commit()


def update_vehicle_state(
    vehicle_id: int,
    current_odometer_km: int, current_fuel_balance_l: float, last_date: date,
) -> None:
    """Обновить состояние ТС текущего user'а."""
    uid = get_current_user_id()
    if not uid:
        return
    with _Session() as s:
        # Проверяем что ТС принадлежит user
        owns = s.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if not owns:
            return
        st = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == vehicle_id)
        ).scalar_one_or_none()
        if not st:
            return
        st.current_odometer_km = current_odometer_km
        st.current_fuel_balance_l = current_fuel_balance_l
        st.last_date = last_date
        s.commit()


def delete_vehicle(vehicle_id: int) -> bool:
    """Удалить ТС user'а вместе со всеми его маршрутами, прогонами и состоянием.

    Возвращает False, если ТС не принадлежит user или у user'а оно последнее.
    """
    uid = get_current_user_id()
    if not uid:
        return False
    with _Session() as s:
        own_vehicles = s.execute(
            select(Vehicle).where(Vehicle.user_id == uid)
        ).scalars().all()
        if len(own_vehicles) <= 1:
            return False
        v = next((x for x in own_vehicles if x.id == vehicle_id), None)
        if not v:
            return False
        # Удаляем зависимости
        for r in s.execute(select(Route).where(Route.vehicle_id == vehicle_id)).scalars():
            s.delete(r)
        for run in s.execute(select(MonthlyRun).where(MonthlyRun.vehicle_id == vehicle_id)).scalars():
            s.delete(run)
        st = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == vehicle_id)
        ).scalar_one_or_none()
        if st:
            s.delete(st)
        s.delete(v)
        # Если удалили активное — переключаем на первое из оставшихся user'а
        p = _profile_for_user(s, uid)
        if p and p.active_vehicle_id == vehicle_id:
            remaining = s.execute(
                select(Vehicle).where(Vehicle.user_id == uid).order_by(Vehicle.id)
            ).scalars().first()
            p.active_vehicle_id = remaining.id if remaining else None
        s.commit()
        return True


def list_vehicles() -> list[Vehicle]:
    """ТС текущего user'а."""
    uid = get_current_user_id()
    if not uid:
        return []
    with _Session() as s:
        return list(s.execute(
            select(Vehicle).where(Vehicle.user_id == uid).order_by(Vehicle.id)
        ).scalars())


def get_vehicle(vehicle_id: int) -> Optional[Vehicle]:
    """ТС user'а; None если такого id нет или принадлежит чужому."""
    uid = get_current_user_id()
    if not uid:
        return None
    with _Session() as s:
        return s.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()


def get_vehicle_state(vehicle_id: int) -> Optional[VehicleState]:
    """Состояние ТС user'а."""
    uid = get_current_user_id()
    if not uid:
        return None
    with _Session() as s:
        # Сначала проверим что ТС user'а
        own = s.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if not own:
            return None
        return s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == vehicle_id)
        ).scalar_one_or_none()


def get_profile() -> Optional[dict]:
    """Профиль + АКТИВНОЕ ТС текущего user + его состояние. None если ещё не настроен."""
    uid = get_current_user_id()
    if not uid:
        return None
    vid = current_vehicle_id()
    if not vid:
        return None
    with _Session() as s:
        p = _profile_for_user(s, uid)
        d = _driver_for_user(s, uid)
        v = s.execute(
            select(Vehicle).where(Vehicle.id == vid, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        st = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == vid)
        ).scalar_one_or_none()
        if not (p and d and v and st):
            return None
        return {
            "organization": {"name": p.organization_name, "mechanic_name": p.mechanic_name},
            "driver": {
                "full_name": d.full_name, "snils": d.snils,
                "license_number": d.license_number,
                "license_issue_date": d.license_issue_date,
            },
            "vehicle": {
                "make_model": v.make_model, "license_plate": v.license_plate,
                "fuel_grade": v.fuel_grade, "tank_capacity_l": v.tank_capacity_l,
                "base_address": v.base_address,
                "fuel_consumption_l_per_100km": v.fuel_consumption_l_per_100km,
            },
            "state": {
                "current_odometer_km": st.current_odometer_km,
                "current_fuel_balance_l": st.current_fuel_balance_l,
                "last_date": st.last_date,
            },
            "vehicle_id": v.id,
        }


# --- Маршруты (CRUD) -------------------------------------------------------

def list_routes() -> list[Route]:
    """Маршруты активного ТС."""
    vid = current_vehicle_id()
    if not vid:
        return []
    with _Session() as s:
        return list(s.execute(
            select(Route).where(Route.vehicle_id == vid)
            .order_by(Route.sort_order, Route.id)
        ).scalars())


def add_route(address: str, km_one_way: float, is_large: bool = False, weight: float = 1.0) -> int:
    """Добавить маршрут в активное ТС."""
    vid = current_vehicle_id()
    if not vid:
        raise RuntimeError("Нет активного ТС")
    with _Session() as s:
        max_order = s.execute(
            select(Route).where(Route.vehicle_id == vid).order_by(Route.sort_order.desc())
        ).scalars().first()
        order = (max_order.sort_order + 1) if max_order else 0
        r = Route(vehicle_id=vid, address=address, km_one_way=km_one_way,
                  is_large=is_large, weight=weight, sort_order=order)
        s.add(r)
        s.commit()
        return r.id


def update_route(route_id: int, **fields) -> None:
    """Обновить маршрут — только если он принадлежит ТС текущего user'а."""
    uid = get_current_user_id()
    if not uid:
        return
    with _Session() as s:
        r = s.execute(
            select(Route).join(Vehicle, Route.vehicle_id == Vehicle.id)
            .where(Route.id == route_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if not r:
            return
        for k, v in fields.items():
            if hasattr(r, k):
                setattr(r, k, v)
        s.commit()


def delete_route(route_id: int) -> None:
    """Удалить маршрут — только если он принадлежит ТС текущего user'а."""
    uid = get_current_user_id()
    if not uid:
        return
    with _Session() as s:
        r = s.execute(
            select(Route).join(Vehicle, Route.vehicle_id == Vehicle.id)
            .where(Route.id == route_id, Vehicle.user_id == uid)
        ).scalar_one_or_none()
        if r:
            s.delete(r)
            s.commit()


# --- Месячные прогоны ------------------------------------------------------

def list_runs() -> list[MonthlyRun]:
    """Прогоны активного ТС."""
    vid = current_vehicle_id()
    if not vid:
        return []
    with _Session() as s:
        return list(s.execute(
            select(MonthlyRun).where(MonthlyRun.vehicle_id == vid)
            .order_by(MonthlyRun.year.desc(), MonthlyRun.month.desc())
        ).scalars())


def get_run(year: int, month: int) -> Optional[MonthlyRun]:
    """Прогон активного ТС за указанный месяц."""
    vid = current_vehicle_id()
    if not vid:
        return None
    with _Session() as s:
        return s.execute(
            select(MonthlyRun).where(
                MonthlyRun.vehicle_id == vid,
                MonthlyRun.year == year,
                MonthlyRun.month == month,
            )
        ).scalar_one_or_none()


def delete_run(year: int, month: int) -> bool:
    """Удалить прогон активного ТС. Откатывает VehicleState на конец последнего оставшегося."""
    vid = current_vehicle_id()
    if not vid:
        return False
    with _Session() as s:
        run = s.execute(
            select(MonthlyRun).where(
                MonthlyRun.vehicle_id == vid,
                MonthlyRun.year == year, MonthlyRun.month == month,
            )
        ).scalar_one_or_none()
        if not run:
            return False
        s.delete(run)
        s.flush()

        latest = s.execute(
            select(MonthlyRun).where(MonthlyRun.vehicle_id == vid)
            .order_by(MonthlyRun.year.desc(), MonthlyRun.month.desc())
        ).scalars().first()
        if latest and latest.days:
            last_day = latest.days[-1]
            st = s.execute(
                select(VehicleState).where(VehicleState.vehicle_id == vid)
            ).scalar_one_or_none()
            if st:
                st.current_odometer_km = last_day.odometer_end
                st.current_fuel_balance_l = last_day.fuel_balance_end
                st.last_date = last_day.date

        s.commit()
        return True


def save_run(out: MonthlyOutput, seed_used: int, validation_ok: bool,
             validation_report_json: str) -> int:
    """Сохранить прогон активного ТС в БД."""
    vid = current_vehicle_id()
    if not vid:
        raise RuntimeError("Нет активного ТС")
    with _Session() as s:
        old = s.execute(
            select(MonthlyRun).where(
                MonthlyRun.vehicle_id == vid,
                MonthlyRun.year == out.input.year,
                MonthlyRun.month == out.input.month,
            )
        ).scalar_one_or_none()
        if old:
            s.delete(old)
            s.flush()

        skip_dates_json = (
            json.dumps([d.isoformat() for d in out.input.skip_dates], ensure_ascii=False)
            if out.input.skip_dates else None
        )
        run = MonthlyRun(
            vehicle_id=vid,
            year=out.input.year, month=out.input.month,
            seed_used=seed_used, validation_ok=validation_ok,
            validation_report_json=validation_report_json,
            skip_dates_json=skip_dates_json,
            generated_at=datetime.utcnow(),
        )
        s.add(run)
        s.flush()

        fuelings_by_date: dict[date, FuelingRecord] = {}
        for f in out.input.fuelings:
            fr = FuelingRecord(run_id=run.id, date=f.date, liters=f.liters,
                               price_per_l=f.price_per_l, sum=f.sum)
            s.add(fr)
            s.flush()
            fuelings_by_date[f.date] = fr

        for d in out.days:
            trips_json = json.dumps([
                {"from_address": t.from_address, "to_address": t.to_address,
                 "km": t.km, "consumption_l": t.consumption_l,
                 "depart": t.depart.isoformat(), "arrive": t.arrive.isoformat(),
                 "direction": t.direction}
                for t in d.trips
            ], ensure_ascii=False)
            day_row = DBDay(
                run_id=run.id, date=d.date,
                odometer_start=d.odometer_start, odometer_end=d.odometer_end,
                fuel_balance_start=d.fuel_balance_start, fuel_balance_end=d.fuel_balance_end,
                release_datetime=d.release_datetime, return_datetime=d.return_datetime,
                trips_json=trips_json,
                fueling_id=(fuelings_by_date[d.fueling.date].id if d.fueling else None),
            )
            s.add(day_row)

        # Обновляем VehicleState активного ТС
        st = s.execute(
            select(VehicleState).where(VehicleState.vehicle_id == vid)
        ).scalar_one_or_none()
        if st:
            st.current_odometer_km = out.final_state.last_odometer_km
            st.current_fuel_balance_l = out.final_state.last_fuel_balance_l
            st.last_date = out.final_state.last_date

        s.commit()
        return run.id


def load_run(year: int, month: int) -> Optional[MonthlyOutput]:
    """Прочитать прогон активного ТС обратно как доменный MonthlyOutput."""
    from datetime import time as _time
    prof = get_profile()
    if not prof:
        return None
    vid = current_vehicle_id()
    with _Session() as s:
        run = s.execute(
            select(MonthlyRun).where(
                MonthlyRun.vehicle_id == vid,
                MonthlyRun.year == year, MonthlyRun.month == month,
            )
        ).scalar_one_or_none()
        if not run:
            return None

        fuelings = [
            Fueling(date=f.date, liters=f.liters, price_per_l=f.price_per_l, sum=f.sum)
            for f in run.fuelings
        ]
        routes = [
            RouteModel(address=r.address, km_one_way=r.km_one_way,
                       consumption_l_one_way=(r.km_one_way *
                                              prof["vehicle"]["fuel_consumption_l_per_100km"] / 100),
                       is_large=r.is_large, weight=r.weight)
            for r in list_routes()
        ]
        skip_dates_list: list[date] = []
        if run.skip_dates_json:
            try:
                skip_dates_list = [date.fromisoformat(d) for d in json.loads(run.skip_dates_json)]
            except Exception:
                skip_dates_list = []
        inp = MonthlyInput(
            year=run.year, month=run.month, seed=run.seed_used,
            organization=Organization(**prof["organization"]),
            driver=DriverModel(**prof["driver"]),
            vehicle=VehicleModel(**prof["vehicle"]),
            routes=routes, fuelings=fuelings,
            carry_over=CarryOver(
                last_odometer_km=run.days[0].odometer_start if run.days else 0,
                last_fuel_balance_l=run.days[0].fuel_balance_start if run.days else 0,
                last_date=date(year, month, 1),
            ),
            skip_dates=skip_dates_list,
        )

        days: list[DomainDay] = []
        for d in run.days:
            trips_data = json.loads(d.trips_json)
            trips = [Trip(
                from_address=t["from_address"], to_address=t["to_address"],
                km=t["km"], consumption_l=t["consumption_l"],
                depart=_time.fromisoformat(t["depart"]),
                arrive=_time.fromisoformat(t["arrive"]),
                direction=t["direction"],
            ) for t in trips_data]
            fueling_obj = None
            if d.fueling_id:
                for f in fuelings:
                    if f.date == d.date:
                        fueling_obj = f
                        break
            days.append(DomainDay(
                date=d.date, trips=trips, fueling=fueling_obj,
                odometer_start=d.odometer_start, odometer_end=d.odometer_end,
                fuel_balance_start=d.fuel_balance_start, fuel_balance_end=d.fuel_balance_end,
                release_datetime=d.release_datetime, return_datetime=d.return_datetime,
            ))

        return MonthlyOutput(
            input=inp, days=days,
            final_state=CarryOver(
                last_odometer_km=days[-1].odometer_end if days else 0,
                last_fuel_balance_l=days[-1].fuel_balance_end if days else 0,
                last_date=days[-1].date if days else date(year, month, 1),
            ),
        )
