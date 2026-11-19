"""Выгрузка сводки в .xlsx в том же виде, что и во второй вкладке примера отца.

Листы:
    «Сводка»          — таблица по группам + «Итого»
    «Позиции»         — каждая позиция меню и в какую строку сводки она попала
    «Проверка данных» — позиции, на которые стоит посмотреть (если такие есть)

По умолчанию в ячейки пишутся готовые значения: такой файл одинаково открывается
в Excel, Google Sheets и в превью WhatsApp/Telegram на телефоне. С formulas=True
производные столбцы пишутся формулами, как в примере отца, — но тогда превью
на телефоне может показать пустые ячейки, пока файл не откроют в Excel.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from resto_analytics.config import LastColumn, SalesSource
from resto_analytics.reports.data_checks import IssueKind
from resto_analytics.reports.group_summary import GroupRow, SalesSummary

MONEY = "#,##0"
COEF = "0.00"
PCT = "0.0"
DASH = "—"

_INK = "16213A"
_HEAD_FILL = PatternFill("solid", fgColor="E3E9F3")
_TOTAL_FILL = PatternFill("solid", fgColor="F3F5F9")
_CRIT_FILL = PatternFill("solid", fgColor="F8D7D4")
_WARN_FILL = PatternFill("solid", fgColor="FCEBC7")
_THIN = Side(style="thin", color="C9D0DC")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_TOTAL_BORDER = Border(left=_THIN, right=_THIN, top=Side(style="medium", color=_INK), bottom=_THIN)
_BOLD = Font(bold=True, color=_INK)
_TITLE = Font(bold=True, size=14, color=_INK)
_MUTED = Font(size=9, color="5B6478")
_WRAP_CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")


@dataclass(frozen=True, slots=True)
class ExcelOptions:
    formulas: bool = False


def sales_title(summary: SalesSummary) -> str:
    if summary.config.sales_source is SalesSource.REVENUE_GROSS:
        return "Сумма продаж без обслуживания, тг"
    return "Сумма продаж, тг"


def last_column_title(summary: SalesSummary) -> str:
    if summary.config.last_column is LastColumn.EFFICIENCY:
        return "Эффективность, % (продажи / себестоимость × 100)"
    return "Доля в продажах, %"


def summary_filename(summary: SalesSummary) -> str:
    meta = summary.meta
    if meta.date_from and meta.date_to:
        return f"Сводка_продаж_{_d(meta.date_from)}-{_d(meta.date_to)}.xlsx"
    return "Сводка_продаж.xlsx"


def _d(value: date) -> str:
    return f"{value:%d.%m.%y}"


def _num(value: Decimal) -> float:
    # В xlsx числа всё равно хранятся как double; округляем до тиынов, чтобы не тащить хвосты.
    return float(round(value, 2))


def _set(ws: Worksheet, ref: str, value: object, fmt: str | None = None) -> None:
    cell = ws[ref]
    cell.value = value
    cell.border = _BORDER
    if fmt:
        cell.number_format = fmt


def _ratio_or_dash(value: Decimal | None) -> float | str:
    return DASH if value is None else float(value)


def write_summary_xlsx(summary: SalesSummary, options: ExcelOptions | None = None) -> bytes:
    options = options or ExcelOptions()
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # у нового Workbook всегда есть активный лист
    ws.title = "Сводка"
    _write_summary_sheet(ws, summary, options)
    _write_items_sheet(wb.create_sheet("Позиции"), summary, options)
    if summary.issues:
        _write_issues_sheet(wb.create_sheet("Проверка данных"), summary)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _write_summary_sheet(ws: Worksheet, summary: SalesSummary, options: ExcelOptions) -> None:
    meta = summary.meta
    ws["B2"] = meta.title
    ws["B2"].font = _TITLE
    info = []
    if meta.warehouses:
        info.append("Склады: " + ", ".join(meta.warehouses))
    info.append(f"Позиций в файле: {summary.line_count}")
    ws["B3"] = " · ".join(info)
    ws["B3"].font = _MUTED

    heads = [
        "Продажа по группам",
        sales_title(summary),
        "Себестоимость, тг",
        "Валовый доход, тг",
        "Обслуживание 10%, тг",
        "Средний коэффициент (сумма / себестоимость)",
        last_column_title(summary),
    ]
    for col_idx, text in enumerate(heads, start=2):
        cell = ws.cell(row=4, column=col_idx, value=text)
        cell.font = _BOLD
        cell.fill = _HEAD_FILL
        cell.alignment = _WRAP_CENTER
        cell.border = _BORDER
    ws.row_dimensions[4].height = 48

    first = 5
    last = first + len(summary.groups) - 1
    total_row = last + 1
    efficiency = summary.config.last_column is LastColumn.EFFICIENCY

    for offset, row in enumerate(summary.groups):
        n = first + offset
        _write_group_row(
            ws,
            n=n,
            row=row,
            summary=summary,
            options=options,
            total_row=total_row,
            efficiency=efficiency,
        )

    t = summary.total
    _set(ws, f"B{total_row}", "Итого")
    if options.formulas and summary.groups:
        for col in "CDEF":
            _set(ws, f"{col}{total_row}", f"=SUM({col}{first}:{col}{last})", MONEY)
        _set(ws, f"G{total_row}", f'=IF(D{total_row}=0,"{DASH}",C{total_row}/D{total_row})', COEF)
        h = (
            f'=IF(D{total_row}=0,"{DASH}",C{total_row}/D{total_row}*100)'
            if efficiency
            else f"=SUM(H{first}:H{last})"
        )
        _set(ws, f"H{total_row}", h, PCT)
    else:
        _set(ws, f"C{total_row}", _num(t.sales), MONEY)
        _set(ws, f"D{total_row}", _num(t.cost), MONEY)
        _set(ws, f"E{total_row}", _num(t.gross), MONEY)
        _set(ws, f"F{total_row}", _num(t.service), MONEY)
        _set(ws, f"G{total_row}", _ratio_or_dash(t.coefficient), COEF)
        _set(ws, f"H{total_row}", _ratio_or_dash(summary.last_value(t)), PCT)
    for col in "BCDEFGH":
        cell = ws[f"{col}{total_row}"]
        cell.font = _BOLD
        cell.fill = _TOTAL_FILL
        cell.border = _TOTAL_BORDER

    notes_row = total_row + 2
    notes = _notes(summary)
    for i, text in enumerate(notes):
        ws.cell(row=notes_row + i, column=2, value=text).font = _MUTED

    for col, width in zip("ABCDEFGH", (2, 24, 17, 17, 17, 17, 18, 18), strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "C5"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    if ws.sheet_properties.pageSetUpPr is not None:
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def _write_group_row(
    ws: Worksheet,
    *,
    n: int,
    row: GroupRow,
    summary: SalesSummary,
    options: ExcelOptions,
    total_row: int,
    efficiency: bool,
) -> None:
    _set(ws, f"B{n}", row.name)
    _set(ws, f"C{n}", _num(row.sales), MONEY)
    _set(ws, f"D{n}", _num(row.cost), MONEY)
    _set(ws, f"F{n}", _num(row.service), MONEY)
    if options.formulas:
        _set(ws, f"E{n}", f"=C{n}-D{n}", MONEY)
        _set(ws, f"G{n}", f'=IF(D{n}=0,"{DASH}",C{n}/D{n})', COEF)
        h = f'=IF(D{n}=0,"{DASH}",C{n}/D{n}*100)' if efficiency else f"=C{n}/C${total_row}*100"
        _set(ws, f"H{n}", h, PCT)
    else:
        _set(ws, f"E{n}", _num(row.gross), MONEY)
        _set(ws, f"G{n}", _ratio_or_dash(row.coefficient), COEF)
        _set(ws, f"H{n}", _ratio_or_dash(summary.last_value(row)), PCT)
    for col in "GH":
        ws[f"{col}{n}"].alignment = Alignment(horizontal="right")


def _notes(summary: SalesSummary) -> list[str]:
    notes = [
        "Валовый доход = сумма продаж − себестоимость. "
        "Коэффициент = сумма продаж / себестоимость (сколько тенге продаж на 1 тг себестоимости).",
        "Как строки собраны из позиций — на листе «Позиции».",
    ]
    rec = summary.reconciliation
    if rec is not None:
        if rec.ok:
            notes.append(
                f"Сверка с итогом файла iiko: совпадает ({_money_text(rec.file_revenue)} тг)."
            )
        else:
            notes.append(
                f"Внимание: сумма строк ({_money_text(rec.lines_revenue)} тг) не совпадает "
                f"с итогом файла ({_money_text(rec.file_revenue)} тг)."
            )
    if summary.excluded_lines:
        notes.append(f"Не учтено по настройкам: {summary.excluded_lines} позиц.")
    if summary.issues:
        notes.append(
            f"На что обратить внимание: {len(summary.issues)} позиц. — лист «Проверка данных»."
        )
    return notes


def _money_text(value: Decimal) -> str:
    return f"{round(value):,}".replace(",", " ")


def _write_items_sheet(ws: Worksheet, summary: SalesSummary, options: ExcelOptions) -> None:
    heads = [
        "Строка сводки",
        "Группа в iiko",
        "Позиция",
        "Количество",
        "Продажи, тг",
        "Себестоимость, тг",
        "Валовый доход, тг",
        "Коэффициент",
    ]
    _header_row(ws, heads)
    n = 2
    for group in summary.groups:
        for item in group.items:
            ws.cell(row=n, column=1, value=group.name)
            ws.cell(row=n, column=2, value=item.source_group)
            ws.cell(row=n, column=3, value=item.name)
            ws.cell(row=n, column=4, value=float(item.quantity)).number_format = "0.##"
            ws.cell(row=n, column=5, value=_num(item.sales)).number_format = MONEY
            ws.cell(row=n, column=6, value=_num(item.cost)).number_format = MONEY
            if options.formulas:
                ws.cell(row=n, column=7, value=f"=E{n}-F{n}")
                ws.cell(row=n, column=8, value=f'=IF(F{n}=0,"{DASH}",E{n}/F{n})')
            else:
                ws.cell(row=n, column=7, value=_num(item.gross))
                ws.cell(row=n, column=8, value=_ratio_or_dash(item.coefficient))
            ws.cell(row=n, column=7).number_format = MONEY
            ws.cell(row=n, column=8).number_format = COEF
            n += 1
    _finish_table(ws, heads, n - 1, widths=(16, 20, 44, 12, 14, 16, 16, 12))


def _write_issues_sheet(ws: Worksheet, summary: SalesSummary) -> None:
    heads = [
        "Что проверить",
        "Позиция",
        "Строка сводки",
        "Продажи, тг",
        "Себестоимость, тг",
        "Коэффициент",
        "Строка в файле iiko",
        "Подсказка",
    ]
    _header_row(ws, heads)
    for n, issue in enumerate(summary.issues, start=2):
        kind_cell = ws.cell(row=n, column=1, value=issue.kind.label)
        kind_cell.fill = _CRIT_FILL if issue.kind is IssueKind.ZERO_COST else _WARN_FILL
        ws.cell(row=n, column=2, value=issue.item)
        ws.cell(row=n, column=3, value=issue.group)
        ws.cell(row=n, column=4, value=_num(issue.sales)).number_format = MONEY
        ws.cell(row=n, column=5, value=_num(issue.cost)).number_format = MONEY
        ws.cell(row=n, column=6, value=_ratio_or_dash(issue.coefficient)).number_format = COEF
        ws.cell(row=n, column=7, value=issue.row_number or None)
        ws.cell(row=n, column=8, value=issue.kind.hint)
    _finish_table(ws, heads, len(summary.issues) + 1, widths=(30, 40, 16, 14, 16, 12, 12, 60))


def _header_row(ws: Worksheet, heads: Sequence[str]) -> None:
    for col_idx, text in enumerate(heads, start=1):
        cell = ws.cell(row=1, column=col_idx, value=text)
        cell.font = _BOLD
        cell.fill = _HEAD_FILL
        cell.alignment = _WRAP_CENTER


def _finish_table(
    ws: Worksheet, heads: Sequence[str], last_row: int, widths: Sequence[int]
) -> None:
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A2"
    if last_row >= 2:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{last_row}"
