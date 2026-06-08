"""CLI: python -m putevoy generate --config config.json."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .generator.generate import generate_month, generate_month_auto_seed
from .generator.models import MonthlyInput
from .generator.validators import validate
from .generator.writers.fuel_log_writer import append_month
from .generator.writers.waybill_writer import write_waybills

app = typer.Typer(no_args_is_help=True, add_completion=False, rich_markup_mode="rich")
console = Console()


@app.command()
def version() -> None:
    """Показать версию."""
    from . import __version__
    console.print(__version__)


@app.command()
def generate(
    config: Path = typer.Option(..., "--config", "-c", help="JSON-файл с MonthlyInput + путями"),
    template: Path = typer.Option(..., "--template", "-t", help="Шаблонный путевой лист .xlsx"),
    fuel_log: Path = typer.Option(..., "--fuel-log", "-f", help="Исторический Топливо.xlsx"),
    out_dir: Path = typer.Option(Path("out"), "--out-dir", "-o", help="Куда сохранить выход"),
    auto_seed: bool = typer.Option(True, "--auto-seed/--fixed-seed",
                                   help="Подобрать seed автоматически (по умолчанию)"),
) -> None:
    """Сгенерировать путевые листы + обновлённый Топливо.xlsx за указанный месяц."""
    inp = MonthlyInput.model_validate_json(config.read_text(encoding="utf-8"))

    console.print(f"[cyan]Месяц:[/] {inp.year}-{inp.month:02d}, ТС: {inp.vehicle.license_plate}")
    if auto_seed:
        result = generate_month_auto_seed(inp)
        out = result.output
        console.print(f"[cyan]Автоподбор seed:[/] {result.seed_used} "
                      f"(попыток: {result.attempts})")
    else:
        out = generate_month(inp)
    console.print(f"[cyan]Рабочих дней:[/] {len(out.days)}")

    report = validate(out)
    if report.issues:
        t = Table(title="Валидация")
        t.add_column("Код"); t.add_column("Уровень"); t.add_column("Сообщение")
        for issue in report.issues:
            t.add_row(issue.code, issue.severity, issue.message)
        console.print(t)
    if not report.ok:
        console.print("[red]Есть ошибки валидации — продолжаю генерацию, но проверьте вывод[/]")

    out_dir.mkdir(parents=True, exist_ok=True)
    waybill_path = out_dir / f"{inp.month:02d}__Путевой_лист_{_month_name(inp.month)}_{inp.year}.xlsx"
    fuel_out_path = out_dir / f"Журнал_учета_топлива_{_month_name(inp.month)}_{inp.year}.xlsx"

    write_waybills(template_path=template, output_path=waybill_path, out=out)
    append_month(template_path=fuel_log, output_path=fuel_out_path, out=out)

    console.print(f"[green]OK[/] {waybill_path}")
    console.print(f"[green]OK[/] {fuel_out_path}")
    console.print(f"[cyan]Финальный одометр:[/] {out.final_state.last_odometer_km}, "
                  f"[cyan]остаток:[/] {out.final_state.last_fuel_balance_l:.2f} л")

    report_path = out_dir / "validation_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[dim]Отчёт валидации: {report_path}[/]")


def _month_name(m: int) -> str:
    from .generator.calendar import MONTH_NOMINATIVE_RU
    return MONTH_NOMINATIVE_RU[m].lower()


def __main():
    app()


if __name__ == "__main__":
    __main()
