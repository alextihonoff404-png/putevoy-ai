"""ORM-модели БД для сервиса путевых листов.

Один пользователь = один профиль (singleton с id=1). Когда добавим auth —
к каждой таблице придёт user_id, а singleton-таблицы станут per-user.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Зарегистрированный пользователь сервиса (auth)."""
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_name: Mapped[str] = mapped_column(String(255))
    mechanic_name: Mapped[str] = mapped_column(String(255))
    # На каком ТС пользователь сейчас работает. NULL = берётся минимальный по id.
    active_vehicle_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Привязка к пользователю (после ввода auth). NULL = legacy профиль до миграции.
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("user.id"), nullable=True, index=True)


class Driver(Base):
    __tablename__ = "driver"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255))
    snils: Mapped[str] = mapped_column(String(20))
    license_number: Mapped[str] = mapped_column(String(50))
    license_issue_date: Mapped[date] = mapped_column(Date)
    # NULL = legacy водитель до миграции; после первой регистрации привязывается.
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, index=True,
    )


class Vehicle(Base):
    __tablename__ = "vehicle"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    make_model: Mapped[str] = mapped_column(String(100))
    license_plate: Mapped[str] = mapped_column(String(20))
    fuel_grade: Mapped[str] = mapped_column(String(20), default="АИ-95")
    tank_capacity_l: Mapped[float] = mapped_column(Float, default=50.0)
    base_address: Mapped[str] = mapped_column(String(500))
    fuel_consumption_l_per_100km: Mapped[float] = mapped_column(Float, default=10.0)
    # NULL = legacy ТС до миграции; после первой регистрации привязывается.
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True, index=True,
    )


class VehicleState(Base):
    """Текущее состояние конкретного ТС."""
    __tablename__ = "vehicle_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, ForeignKey("vehicle.id"), unique=True)
    current_odometer_km: Mapped[int] = mapped_column(Integer)
    current_fuel_balance_l: Mapped[float] = mapped_column(Float)
    last_date: Mapped[date] = mapped_column(Date)


class Route(Base):
    __tablename__ = "route"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, ForeignKey("vehicle.id"), index=True)
    address: Mapped[str] = mapped_column(String(500))
    km_one_way: Mapped[float] = mapped_column(Float)
    is_large: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class MonthlyRun(Base):
    __tablename__ = "monthly_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, ForeignKey("vehicle.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    seed_used: Mapped[int] = mapped_column(Integer)
    validation_ok: Mapped[bool] = mapped_column(Boolean)
    validation_report_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skip_dates_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-список ISO-дат

    fuelings: Mapped[list["FuelingRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    days: Mapped[list["GeneratedDay"]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        order_by="GeneratedDay.date",
    )


class FuelingRecord(Base):
    __tablename__ = "fueling_record"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("monthly_run.id"))
    date: Mapped[date] = mapped_column(Date)
    liters: Mapped[float] = mapped_column(Float)
    price_per_l: Mapped[float] = mapped_column(Float)
    sum: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    run: Mapped[MonthlyRun] = relationship(back_populates="fuelings")


class GeneratedDay(Base):
    __tablename__ = "generated_day"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("monthly_run.id"))
    date: Mapped[date] = mapped_column(Date)
    odometer_start: Mapped[int] = mapped_column(Integer)
    odometer_end: Mapped[int] = mapped_column(Integer)
    fuel_balance_start: Mapped[float] = mapped_column(Float)
    fuel_balance_end: Mapped[float] = mapped_column(Float)
    release_datetime: Mapped[datetime] = mapped_column(DateTime)
    return_datetime: Mapped[datetime] = mapped_column(DateTime)
    trips_json: Mapped[str] = mapped_column(Text)  # JSON-сериализованный список Trip
    fueling_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("fueling_record.id"), nullable=True
    )

    run: Mapped[MonthlyRun] = relationship(back_populates="days")
