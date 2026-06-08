from datetime import date

from putevoy.parsing.fueling_parser import parse_fuelings


def test_instruction_format():
    text = """
    Заправка 05.03.2026 количество 47.50 цена 69.20 сумма 3286.00
    Заправка 18.03.2026 количество 44.00 цена 69.20 сумма 2975.60
    """
    r = parse_fuelings(text)
    assert len(r) == 2
    assert r[0].date == date(2026, 3, 5)
    assert r[0].liters == 47.5
    assert r[0].price_per_l == 69.2
    assert r[0].sum == 3286.0
    assert r[1].date == date(2026, 3, 18)


def test_short_format_with_default_year():
    text = "15.04 47.63л по 69.37"
    r = parse_fuelings(text, default_year=2026)
    assert len(r) == 1
    assert r[0].date == date(2026, 4, 15)
    assert r[0].liters == 47.63
    assert r[0].price_per_l == 69.37


def test_russian_month_name():
    text = "23 апреля 2026 45,69л 69,26 ₽"
    r = parse_fuelings(text)
    assert len(r) == 1
    assert r[0].date == date(2026, 4, 23)
    assert r[0].liters == 45.69
    assert r[0].price_per_l == 69.26


def test_comma_decimal():
    text = "02.03.2026 - 47,55л x 68,77 = 3269,01"
    r = parse_fuelings(text)
    assert len(r) == 1
    assert r[0].liters == 47.55
    assert r[0].price_per_l == 68.77
    assert r[0].sum == 3269.01


def test_skip_garbage_lines():
    text = """
    Привет!
    Это какой-то текст без заправки
    15.04.2026 47.63л 69.37 ₽
    Ещё мусор
    """
    r = parse_fuelings(text)
    assert len(r) == 1


def test_total_method():
    from putevoy.generator.models import Fueling
    f = Fueling(date=date(2026, 4, 15), liters=47.63, price_per_l=69.37)
    assert f.total() == round(47.63 * 69.37, 2)
