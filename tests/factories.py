"""Генератор синтетических выгрузок iiko для тестов.

Настоящие выгрузки с деньгами ресторана в репозиторий не кладём,
поэтому тестовый файл собирается здесь — с той же структурой, что у iiko:
три строки заголовка, шапка таблицы, объединённые ячейки «Сумма скидок» (H:I),
строки позиций и «Итого:».
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from openpyxl import Workbook


@dataclass(frozen=True)
class Line:
    group: str
    category: str
    item: str
    qty: int
    price: Decimal | int
    unit_cost: Decimal | int
    service_pct: int = 10

    @property
    def revenue_gross(self) -> Decimal:
        return Decimal(self.qty) * Decimal(self.price)

    @property
    def discount(self) -> Decimal:
        # iiko пишет надбавку за обслуживание как отрицательную скидку
        return -(self.revenue_gross * self.service_pct / 100)

    @property
    def revenue(self) -> Decimal:
        return self.revenue_gross - self.discount

    @property
    def cost(self) -> Decimal:
        return Decimal(self.qty) * Decimal(self.unit_cost)

    @property
    def profit(self) -> Decimal:
        return self.revenue - self.cost


Getter = Callable[[Line], object]

IIKO_COLUMNS: dict[str, Getter] = {
    "Группа": lambda ln: ln.group,
    "Категория": lambda ln: ln.category,
    "Элемент номенклатуры": lambda ln: ln.item,
    "Количество": lambda ln: ln.qty,
    "Средняя цена без вычета скидок, тг.": lambda ln: float(ln.price),
    "Себес. за ед., тг.": lambda ln: float(ln.unit_cost),
    "Выручка без вычета скидок, тг.": lambda ln: float(ln.revenue_gross),
    "Сумма скидок, тг.": lambda ln: float(ln.discount),
    "Себестоимость, тг.": lambda ln: float(ln.cost),
    "Валовая прибыль, тг.": lambda ln: float(ln.profit),
    "Выручка, тг.": lambda ln: float(ln.revenue),
}
TOTAL_FIELDS: dict[str, Callable[[Sequence[Line]], object]] = {
    "Количество": lambda ls: sum(ln.qty for ln in ls),
    "Выручка без вычета скидок, тг.": lambda ls: float(sum(ln.revenue_gross for ln in ls)),
    "Сумма скидок, тг.": lambda ls: float(sum(ln.discount for ln in ls)),
    "Себестоимость, тг.": lambda ls: float(sum(ln.cost for ln in ls)),
    "Валовая прибыль, тг.": lambda ls: float(sum(ln.profit for ln in ls)),
    "Выручка, тг.": lambda ls: float(sum(ln.revenue for ln in ls)),
}

TITLE = "Отчет о продажах с 01.11.26 по 30.11.26"
WAREHOUSES = "Склад(ы): Бар склад Точка 2, Основной склад Точка 2, Кухня склад Точка 2"


def make_iiko_xlsx(
    lines: Sequence[Line],
    *,
    columns: Sequence[str] | None = None,
    with_meta: bool = True,
    with_total: bool = True,
    blank_repeated_groups: bool = False,
    total_override: dict[str, object] | None = None,
    leading_sheet: bool = False,
    cell_overrides: dict[tuple[int, str], object] | None = None,
) -> bytes:
    """Собирает .xlsx как у iiko.

    columns — порядок/набор столбцов (по умолчанию как в iiko).
    blank_repeated_groups — как иногда делает iiko: группа пишется только в первой строке блока.
    cell_overrides — {(индекс строки позиции, столбец): значение} — чтобы подложить «кривые» данные.
    """
    columns = list(columns or IIKO_COLUMNS)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    if leading_sheet:
        ws.title = "Инфо"
        ws["A1"] = "Тут нет таблицы продаж"
        ws = wb.create_sheet("Отчет")
    else:
        ws.title = "Отчет о продажах"

    header_row = 1
    if with_meta:
        ws["A1"] = TITLE
        ws["A2"] = "За период: с 01.11.26 по 30.11.26 "
        ws["A3"] = WAREHOUSES
        ws.merge_cells("A3:H3")
        header_row = 4

    # Как в iiko: после «Суммы скидок» идёт объединённая пустая ячейка (H:I)
    layout: list[str | None] = []
    for name in columns:
        layout.append(name)
        if name == "Сумма скидок, тг.":
            layout.append(None)

    for col, name in enumerate(layout, start=1):
        if name is not None:
            ws.cell(row=header_row, column=col, value=name)

    overrides = cell_overrides or {}
    previous_group = None
    for idx, line in enumerate(lines):
        row = header_row + 1 + idx
        for col, name in enumerate(layout, start=1):
            if name is None:
                continue
            value = IIKO_COLUMNS[name](line)
            if name == "Группа" and blank_repeated_groups and line.group == previous_group:
                value = None
            if (idx, name) in overrides:
                value = overrides[(idx, name)]
            ws.cell(row=row, column=col, value=value)
            if name == "Сумма скидок, тг.":
                ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        previous_group = line.group

    if with_total:
        row = header_row + 1 + len(lines)
        item_col = (
            layout.index("Элемент номенклатуры") + 1 if "Элемент номенклатуры" in layout else 1
        )
        ws.cell(row=row, column=item_col, value="Итого: ")
        totals = {name: fn(lines) for name, fn in TOTAL_FIELDS.items()}
        totals.update(total_override or {})
        for col, name in enumerate(layout, start=1):
            if name in totals:
                ws.cell(row=row, column=col, value=totals[name])  # type: ignore[arg-type]

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Набор позиций с заранее посчитанными вручную итогами (см. tests/test_group_summary.py)
SAMPLE_LINES: tuple[Line, ...] = (
    Line("Горячие напитки", "Бар", "Ташкентский чай", 10, 690, 65),
    Line("Горячие напитки", "Бар", "Чайник черного чая", 4, 600, 15),
    Line("Десерты", "Бар", "Пахлава", 5, 400, 240),
    Line("Куырдак", "Бар", "Куырдак", 4, 2300, 2050),
    Line("Лагман", "Бар", "Гуйру Лагман", 3, 990, 0),
    Line("Плов", "Плов", "Ханский плов", 6, 1990, 1115),
    Line("Плов", "Плов", "Ханский плов / агрегатор", 2, 2700, 534, service_pct=0),
    Line("Самса", "Самса", "Самса с мясом", 100, 350, 241),
    Line("Супы", "Супы", "Домашние пельмени (суп)", 2, 1600, 3),
    Line("Штрафы", "Штрафы", "Штраф 1000 тг", 1, 1000, 0, service_pct=0),
)
