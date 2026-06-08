from datetime import date
from pathlib import Path

from putevoy.parsing.fuel_log_importer import import_state_from_xlsx

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_import_from_april_2026():
    """В фикстуре Топливо_апрель_2026.xlsx последний день — 30.04.2026,
    одометр 50964, остаток ~2.49 л."""
    state = import_state_from_xlsx(FIXTURES / "Топливо_апрель_2026.xlsx")
    assert state is not None
    assert state.odometer_km == 50964
    assert abs(state.fuel_balance_l - 2.49) < 0.01
    assert state.last_date == date(2026, 4, 30)


def test_import_from_march_2026():
    state = import_state_from_xlsx(FIXTURES / "Топливо_март_2026.xlsx")
    assert state is not None
    assert state.last_date == date(2026, 3, 31)
