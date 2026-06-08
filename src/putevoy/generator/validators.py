"""Все 6 проверок из §7 инструкции."""
from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import BaseModel

from .models import MonthlyOutput


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str


class ValidationReport(BaseModel):
    ok: bool
    issues: list[ValidationIssue]


def validate(out: MonthlyOutput) -> ValidationReport:
    issues: list[ValidationIssue] = []
    tank = out.input.vehicle.tank_capacity_l

    for d in out.days:
        if d.fuel_balance_start < 0:
            issues.append(ValidationIssue(
                code="FUEL_NEGATIVE",
                severity="error",
                message=f"{d.date}: остаток на начало дня {d.fuel_balance_start:.2f} < 0 "
                        "— недостаточно стартового топлива или мало заправок",
            ))
        if d.fuel_balance_end < 0:
            issues.append(ValidationIssue(
                code="FUEL_NEGATIVE",
                severity="error",
                message=f"{d.date}: остаток на конец дня {d.fuel_balance_end:.2f} < 0",
            ))
        if d.fuel_balance_start > tank + 1e-6:
            issues.append(ValidationIssue(
                code="TANK_OVERFLOW",
                severity="error",
                message=f"{d.date}: остаток до заправки {d.fuel_balance_start:.2f} > бака {tank}",
            ))
        if d.fuel_balance_end > tank + 1e-6:
            issues.append(ValidationIssue(
                code="TANK_OVERFLOW",
                severity="error",
                message=f"{d.date}: остаток после возврата {d.fuel_balance_end:.2f} > бака {tank}",
            ))
        if d.return_datetime.time() > time(21, 0):
            issues.append(ValidationIssue(
                code="TIME_LATE",
                severity="error",
                message=f"{d.date}: возврат в {d.return_datetime.time()} — позже 21:00",
            ))
        if d.trip_count > 4:
            issues.append(ValidationIssue(
                code="TOO_MANY_TRIPS",
                severity="error",
                message=f"{d.date}: {d.trip_count} поездок (макс 4)",
            ))
        if not d.trips:
            issues.append(ValidationIssue(
                code="NO_TRIPS",
                severity="error",
                message=f"{d.date}: нет поездок",
            ))

    for i in range(1, len(out.days)):
        prev, cur = out.days[i - 1], out.days[i]
        if cur.odometer_start != prev.odometer_end:
            issues.append(ValidationIssue(
                code="ODOMETER_GAP",
                severity="error",
                message=f"{cur.date}: одометр начала {cur.odometer_start} != конца предыдущего {prev.odometer_end}",
            ))

    return ValidationReport(ok=not any(i.severity == "error" for i in issues), issues=issues)
