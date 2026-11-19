from decimal import Decimal

import pytest

from resto_analytics.domain.money import NumberFormatError, parse_decimal, percent, ratio


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, Decimal(0)),
        (0, Decimal(0)),
        (105, Decimal(105)),
        (99.59, Decimal("99.59")),
        (198047.286939145, Decimal("198047.286939145")),
        (Decimal("1.5"), Decimal("1.5")),
        ("1 234,50", Decimal("1234.50")),
        ("1 234", Decimal(1234)),
        ("-6 969 тг", Decimal(-6969)),
        ("500₸", Decimal(500)),
        ("", Decimal(0)),
        ("—", Decimal(0)),
        ("-", Decimal(0)),
    ],
)
def test_parse_decimal_accepts_excel_values(raw: object, expected: Decimal) -> None:
    assert parse_decimal(raw) == expected


def test_float_is_not_dragged_with_binary_tail() -> None:
    # Decimal(0.1) == 0.1000000000000000055511..., а нам нужно ровно 0.1
    assert parse_decimal(0.1) == Decimal("0.1")


@pytest.mark.parametrize("raw", ["abc", "12abc", True, [1, 2]])
def test_parse_decimal_rejects_garbage(raw: object) -> None:
    with pytest.raises(NumberFormatError):
        parse_decimal(raw)


def test_ratio_and_percent() -> None:
    assert ratio(Decimal(3), Decimal(2)) == Decimal("1.5")
    assert ratio(Decimal(3), Decimal(0)) is None
    assert percent(Decimal(1), Decimal(4)) == Decimal(25)
    assert percent(Decimal(1), Decimal(0)) is None
