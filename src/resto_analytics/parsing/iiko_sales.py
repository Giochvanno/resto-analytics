"""Парсер выгрузки iiko «Отчет о продажах» (.xlsx).

Структура файла, которую мы ожидаем:

    строки 1..N   — заголовок: «Отчет о продажах с 01.11.26 по 30.11.26», период, склады
    строка N+1    — шапка таблицы: Группа | Категория | Элемент номенклатуры | Количество | …
    далее         — по строке на позицию меню
    последняя     — «Итого:»

Столбцы ищем по названию, а не по номеру: если в iiko поменяют порядок
или добавят столбец, парсер не сломается.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from resto_analytics.domain.models import FileTotals, ReportMeta, SaleLine, SalesReport
from resto_analytics.domain.money import NumberFormatError, parse_decimal
from resto_analytics.parsing.errors import ParseError

HEADER_SEARCH_ROWS = 40
NO_GROUP = "Без группы"

_WS = re.compile(r"\s+")
_PERIOD = re.compile(
    r"с\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*по\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})", re.I
)
_WAREHOUSES = re.compile(r"^склад(?:\(ы\)|ы)?\s*:\s*", re.I)
_TOTAL = re.compile(r"^\s*итого", re.I)


class Field(StrEnum):
    GROUP = "group"
    CATEGORY = "category"
    ITEM = "item"
    QUANTITY = "quantity"
    REVENUE_GROSS = "revenue_gross"
    DISCOUNT = "discount"
    COST = "cost"
    PROFIT = "profit"
    REVENUE = "revenue"


# Порядок важен: «Выручка без вычета скидок» надо распознать раньше, чем просто «Выручка».
_HEADER_RULES: tuple[tuple[Field, tuple[str, ...]], ...] = (
    (Field.GROUP, ("группа",)),
    (Field.CATEGORY, ("категория",)),
    (Field.ITEM, ("элемент номенклатуры", "номенклатура", "блюдо")),
    (Field.QUANTITY, ("количество",)),
    (Field.REVENUE_GROSS, ("выручка без",)),
    (Field.DISCOUNT, ("сумма скид", "скидк")),
    (Field.COST, ("себестоимость",)),
    (Field.PROFIT, ("валовая прибыль",)),
    (Field.REVENUE, ("выручка",)),
)

_HUMAN_NAMES = {
    Field.QUANTITY: "Количество",
    Field.REVENUE_GROSS: "Выручка без вычета скидок",
    Field.DISCOUNT: "Сумма скидок",
    Field.COST: "Себестоимость",
    Field.REVENUE: "Выручка",
}


def _clean(value: object) -> str:
    return "" if value is None else _WS.sub(" ", str(value)).strip()


def classify_header(text: object) -> Field | None:
    norm = _clean(text).lower()
    if not norm:
        return None
    for field, prefixes in _HEADER_RULES:
        if any(norm.startswith(p) for p in prefixes):
            return field
    return None


@dataclass(frozen=True, slots=True)
class _Header:
    row_index: int
    columns: dict[Field, int]


def _find_header(rows: Sequence[Sequence[object]]) -> _Header | None:
    for idx, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns: dict[Field, int] = {}
        for col, value in enumerate(row):
            field = classify_header(value)
            if field is not None and field not in columns:
                columns[field] = col
        has_name = bool({Field.ITEM, Field.GROUP, Field.CATEGORY} & columns.keys())
        has_money = Field.REVENUE in columns or Field.REVENUE_GROSS in columns
        if has_name and has_money and Field.COST in columns:
            return _Header(idx, columns)
    return None


def _parse_short_date(day: str, month: str, year: str) -> date | None:
    y = int(year)
    if y < 100:
        y += 2000
    try:
        return date(y, int(month), int(day))
    except ValueError:
        return None


def _parse_meta(rows: Sequence[Sequence[object]], sheet_name: str) -> ReportMeta:
    title = ""
    date_from: date | None = None
    date_to: date | None = None
    warehouses: tuple[str, ...] = ()
    for row in rows:
        for value in row:
            text = _clean(value)
            if not text:
                continue
            if not title and "отч" in text.lower():
                title = text
            if _WAREHOUSES.match(text):
                rest = _WAREHOUSES.sub("", text)
                warehouses = tuple(w.strip() for w in rest.split(",") if w.strip())
            m = _PERIOD.search(text)
            if m and date_from is None:
                date_from = _parse_short_date(*m.group(1, 2, 3))
                date_to = _parse_short_date(*m.group(4, 5, 6))
    if not title:
        title = "Отчет о продажах"
    return ReportMeta(
        title=title,
        date_from=date_from,
        date_to=date_to,
        warehouses=warehouses,
        sheet_name=sheet_name,
    )


def _is_total_row(row: Sequence[object]) -> bool:
    return any(isinstance(v, str) and _TOTAL.match(v) for v in row)


def _is_blank(row: Sequence[object]) -> bool:
    return all(_clean(v) == "" for v in row)


class _RowReader:
    def __init__(self, header: _Header) -> None:
        self.columns = header.columns

    def text(self, row: Sequence[object], field: Field) -> str:
        col = self.columns.get(field)
        return _clean(row[col]) if col is not None and col < len(row) else ""

    def number(self, row: Sequence[object], field: Field, row_number: int) -> Decimal:
        col = self.columns.get(field)
        if col is None or col >= len(row):
            return Decimal(0)
        try:
            return parse_decimal(row[col])
        except NumberFormatError as exc:
            name = _HUMAN_NAMES.get(field, field.value)
            raise ParseError(f"Строка {row_number}, столбец «{name}»: {exc}.") from exc


def _parse_table(
    rows: Sequence[Sequence[object]], header: _Header
) -> tuple[tuple[SaleLine, ...], FileTotals | None]:
    reader = _RowReader(header)
    has = header.columns.__contains__
    lines: list[SaleLine] = []
    totals: FileTotals | None = None
    last_group = last_category = ""

    for idx in range(header.row_index + 1, len(rows)):
        row = rows[idx]
        row_number = idx + 1
        if _is_blank(row):
            continue
        if _is_total_row(row):
            # Если в файле есть промежуточные «Итого», последнее — общий итог.
            revenue_field = Field.REVENUE if has(Field.REVENUE) else Field.REVENUE_GROSS
            totals = FileTotals(
                revenue=reader.number(row, revenue_field, row_number),
                cost=reader.number(row, Field.COST, row_number),
            )
            continue

        group = reader.text(row, Field.GROUP)
        category = reader.text(row, Field.CATEGORY)
        item = reader.text(row, Field.ITEM)
        # iiko иногда пишет группу только в первой строке блока — протягиваем вниз.
        if not group and item and has(Field.GROUP):
            group = last_group
        if not category and item and has(Field.CATEGORY):
            category = last_category
        last_group = group or last_group
        last_category = category or last_category
        group = group or category or NO_GROUP
        category = category or group

        revenue_gross = reader.number(row, Field.REVENUE_GROSS, row_number)
        discount = reader.number(row, Field.DISCOUNT, row_number)
        if has(Field.REVENUE):
            revenue = reader.number(row, Field.REVENUE, row_number)
        else:
            revenue = revenue_gross - discount
        if not has(Field.REVENUE_GROSS):
            revenue_gross = revenue + discount

        lines.append(
            SaleLine(
                group=group,
                category=category,
                item=item or group,
                quantity=reader.number(row, Field.QUANTITY, row_number),
                revenue_gross=revenue_gross,
                discount=discount,
                revenue=revenue,
                cost=reader.number(row, Field.COST, row_number),
                row_number=row_number,
            )
        )

    return tuple(lines), totals


def parse_rows(rows: Iterable[Sequence[object]], sheet_name: str = "") -> SalesReport | None:
    """Разбирает одну таблицу (список строк). None — если таблицы продаж в ней нет."""
    materialized = [tuple(r) for r in rows]
    header = _find_header(materialized)
    if header is None:
        return None
    lines, totals = _parse_table(materialized, header)
    if not lines:
        return None
    meta = _parse_meta(materialized[: header.row_index], sheet_name)
    return SalesReport(meta=meta, lines=lines, file_totals=totals)


def _read_bytes(source: bytes | BinaryIO | Path) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, Path):
        return source.read_bytes()
    return source.read()


def parse_sales_report(source: bytes | BinaryIO | Path) -> SalesReport:
    """Читает .xlsx и возвращает отчёт с первого листа, где нашлась таблица продаж."""
    data = _read_bytes(source)
    if not data:
        raise ParseError("Файл пустой.")
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise ParseError(
            "Не получилось открыть файл как Excel (.xlsx). "
            "Выгрузите отчёт из iiko заново в формате Excel."
        ) from exc

    try:
        for sheet in workbook.worksheets:
            # Некоторые генераторы пишут неверный размер листа — пересчитываем.
            reset = getattr(sheet, "reset_dimensions", None)
            if callable(reset):
                reset()
            report = parse_rows(sheet.iter_rows(values_only=True), sheet.title)
            if report is not None:
                return report
    finally:
        workbook.close()

    raise ParseError(
        "Не нашёл таблицу продаж. Нужна выгрузка «Отчет о продажах» из iiko "
        "со столбцами «Группа» или «Категория», «Выручка» и «Себестоимость»."
    )
