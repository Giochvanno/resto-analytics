"""Модели исходных данных — то, что лежит в выгрузке iiko «Отчет о продажах»."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from resto_analytics.domain.money import ZERO


@dataclass(frozen=True, slots=True)
class SaleLine:
    """Одна строка выгрузки: позиция меню и её продажи за период."""

    group: str
    """«Группа» в iiko (Горячие напитки, Лагман, Плов…)."""
    category: str
    """«Категория» в iiko (Бар, Плов, Самса…). По умолчанию сводка строится по ней."""
    item: str
    """«Элемент номенклатуры» — само блюдо или товар."""
    quantity: Decimal
    revenue_gross: Decimal
    """«Выручка без вычета скидок» — по ценам меню."""
    discount: Decimal
    """«Сумма скидок». Отрицательное значение в iiko — это надбавка (обслуживание 10%)."""
    revenue: Decimal
    """«Выручка» — сколько реально получено."""
    cost: Decimal
    """«Себестоимость» всей проданной партии, не за единицу."""
    row_number: int = 0
    """Номер строки в Excel — чтобы в ошибках можно было показать, где искать."""

    @property
    def service_surcharge(self) -> Decimal:
        """Надбавка за обслуживание: в iiko она лежит в «Сумме скидок» со знаком минус."""
        return -self.discount if self.discount < ZERO else ZERO

    @property
    def unit_price(self) -> Decimal | None:
        return self.revenue_gross / self.quantity if self.quantity else None

    @property
    def unit_cost(self) -> Decimal | None:
        return self.cost / self.quantity if self.quantity else None


@dataclass(frozen=True, slots=True)
class ReportMeta:
    title: str
    date_from: date | None = None
    date_to: date | None = None
    warehouses: tuple[str, ...] = ()
    sheet_name: str = ""

    @property
    def period_label(self) -> str:
        if self.date_from and self.date_to:
            return f"{self.date_from:%d.%m.%Y} – {self.date_to:%d.%m.%Y}"
        return ""


@dataclass(frozen=True, slots=True)
class FileTotals:
    """Строка «Итого» из самого файла — по ней сверяем, что ничего не потеряли."""

    revenue: Decimal
    cost: Decimal


@dataclass(frozen=True, slots=True)
class SalesReport:
    meta: ReportMeta
    lines: tuple[SaleLine, ...]
    file_totals: FileTotals | None = None
