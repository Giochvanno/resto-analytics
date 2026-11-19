"""Работа с деньгами.

Все суммы храним в Decimal: float даёт ошибки округления (0.1 + 0.2 != 0.3),
а в отчёте о деньгах сумма по группам должна сходиться с итогом файла до тиына.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)
HUNDRED = Decimal(100)

_SPACES = re.compile(r"[\s  ]")
_CURRENCY = re.compile(r"(тг|тенге|₸|kzt)\.?$", re.IGNORECASE)


class NumberFormatError(ValueError):
    """Значение ячейки нельзя прочитать как число."""


def parse_decimal(value: object) -> Decimal:
    """Превращает значение ячейки Excel в Decimal.

    Понимает int/float/Decimal и строки вида «1 234,50», «-6 969 тг», «» (пусто = 0).
    Бросает NumberFormatError, если в ячейке явно не число.
    """
    if value is None:
        return ZERO
    if isinstance(value, bool):  # bool — подкласс int, но в отчёте о продажах это ошибка
        raise NumberFormatError(f"ожидалось число, а в ячейке логическое значение {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # str() даёт кратчайшее представление: 198047.286939145, а не 198047.28693914499...
        return Decimal(str(value))
    if isinstance(value, str):
        text = _CURRENCY.sub("", _SPACES.sub("", value)).replace(",", ".")
        if text in {"", "-", "—"}:
            return ZERO
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise NumberFormatError(f"«{value}» не похоже на число") from exc
    raise NumberFormatError(f"неожиданный тип значения: {type(value).__name__}")


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """numerator / denominator или None, если делить не на что."""
    if denominator == ZERO:
        return None
    return numerator / denominator


def percent(part: Decimal, whole: Decimal) -> Decimal | None:
    value = ratio(part, whole)
    return None if value is None else value * HUNDRED
