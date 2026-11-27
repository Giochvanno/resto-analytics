"""Числа для чата: коротко и по-русски.

В телефоне «12 345 678» читается тяжело, «12,3 млн» — сразу.
Точные цифры остаются в Excel.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

MILLION = Decimal(1_000_000)
THOUSAND = Decimal(1_000)

MONTHS = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)  # fmt: skip


def _round(value: Decimal, digits: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _ru(value: Decimal, digits: int) -> str:
    text = f"{_round(value, digits):,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def money(value: Decimal, digits: int = 1) -> str:
    """12 345 678 → «12,3 млн»; 456 789 → «457 тыс»; 950 → «950»."""
    sign = "−" if value < 0 else ""
    value = abs(value)
    if _round(value, 0) >= MILLION:
        return f"{sign}{_ru(value / MILLION, digits)} млн"
    if _round(value, 0) >= THOUSAND:
        return f"{sign}{_ru(value / THOUSAND, 0)} тыс"
    return f"{sign}{_ru(value, 0)}"


def coef(value: Decimal | None) -> str:
    return "—" if value is None else _ru(value, 2)


COEF_CAP = Decimal(100)


def coef_cell(value: Decimal | None) -> str:
    """Для узких таблиц: коэффициент 533,33 (себестоимость почти 0) показываем как «>100»."""
    if value is not None and value >= COEF_CAP:
        return ">100"
    return coef(value)


def pct(value: Decimal | None) -> str:
    return "—" if value is None else f"{_ru(value, 1)}%"


def period_title(date_from: date | None, date_to: date | None, fallback: str) -> str:
    """Полный календарный месяц → «Ноябрь 2026», иначе «01.11.2026 – 15.11.2026»."""
    if date_from is None or date_to is None:
        return fallback
    whole_month = (
        date_from.day == 1
        and (date_from.year, date_from.month) == (date_to.year, date_to.month)
        and _is_last_day(date_to)
    )
    if whole_month:
        return f"{MONTHS[date_from.month - 1]} {date_from.year}"
    return f"{date_from:%d.%m.%Y} – {date_to:%d.%m.%Y}"


def _is_last_day(day: date) -> bool:
    next_day = day.toordinal() + 1
    return date.fromordinal(next_day).month != day.month


def clip(text: str, width: int) -> str:
    """Обрезает для моноширинной таблицы: «Горячие напитки» → «Горячие н…»."""
    return text if len(text) <= width else text[: width - 1] + "…"
