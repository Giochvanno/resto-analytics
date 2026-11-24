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

from resto_analytics.config import LastColumn, MarginBase
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


def margin_base_label(summary: SalesSummary) -> str:
    """«…от продаж без обслуживания» — для подписей и примечаний."""
    if summary.config.margin_base is MarginBase.WITH_SERVICE:
        return "продаж с обслуживанием"
    return "продаж без обслуживания"


def _base_col(summary: SalesSummary, *, without: str, with_: str) -> str:
    """Буква столбца, от которого считаются доход и коэффициент."""
    return with_ if summary.config.margin_base is MarginBase.WITH_SERVICE else without


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


SUMMARY_HEADS = (
    "Продажа по группам",
    "Продажи без обслуживания, тг",
    "Обслуживание 10%, тг",
    "Продажи с обслуживанием, тг",
    "Себестоимость, тг",
    "Валовый доход, тг",
    "Средний коэффициент (продажи / себестоимость)",
)
# B — группа, C — без обслуживания, D — обслуживание, E — с обслуживанием,
# F — себестоимость, G — валовый доход, H — коэффициент, I — доля / эффективность
_SUMMARY_COLS = "BCDEFGHI"


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

    for col_idx, text in enumerate((*SUMMARY_HEADS, last_column_title(summary)), start=2):
        cell = ws.cell(row=4, column=col_idx, value=text)
        cell.font = _BOLD
        cell.fill = _HEAD_FILL
        cell.alignment = _WRAP_CENTER
        cell.border = _BORDER
    ws.row_dimensions[4].height = 48

    first = 5
    last = first + len(summary.groups) - 1
    total_row = last + 1
    for offset, row in enumerate(summary.groups):
        _write_group_row(
            ws, n=first + offset, row=row, summary=summary, options=options, total_row=total_row
        )
    _write_total_row(ws, summary, options, first=first, last=last, total_row=total_row)

    notes_row = total_row + 2
    for i, text in enumerate(_notes(summary)):
        ws.cell(row=notes_row + i, column=2, value=text).font = _MUTED

    widths = (2, 22, 16, 15, 16, 16, 16, 17, 17)
    for col, width in zip("A" + _SUMMARY_COLS, widths, strict=True):
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
) -> None:
    base = _base_col(summary, without="C", with_="E")
    efficiency = summary.config.last_column is LastColumn.EFFICIENCY
    _set(ws, f"B{n}", row.name)
    _set(ws, f"C{n}", _num(row.sales_net), MONEY)
    _set(ws, f"D{n}", _num(row.service), MONEY)
    _set(ws, f"F{n}", _num(row.cost), MONEY)
    if options.formulas:
        _set(ws, f"E{n}", f"=C{n}+D{n}", MONEY)
        _set(ws, f"G{n}", f"={base}{n}-F{n}", MONEY)
        _set(ws, f"H{n}", f'=IF(F{n}=0,"{DASH}",{base}{n}/F{n})', COEF)
        last = (
            f'=IF(F{n}=0,"{DASH}",{base}{n}/F{n}*100)'
            if efficiency
            else f"={base}{n}/{base}${total_row}*100"
        )
        _set(ws, f"I{n}", last, PCT)
    else:
        _set(ws, f"E{n}", _num(row.sales_total), MONEY)
        _set(ws, f"G{n}", _num(row.gross), MONEY)
        _set(ws, f"H{n}", _ratio_or_dash(row.coefficient), COEF)
        _set(ws, f"I{n}", _ratio_or_dash(summary.last_value(row)), PCT)
    for col in "HI":
        ws[f"{col}{n}"].alignment = Alignment(horizontal="right")


def _write_total_row(
    ws: Worksheet,
    summary: SalesSummary,
    options: ExcelOptions,
    *,
    first: int,
    last: int,
    total_row: int,
) -> None:
    t = summary.total
    n = total_row
    base = _base_col(summary, without="C", with_="E")
    _set(ws, f"B{n}", "Итого")
    if options.formulas and summary.groups:
        for col in "CDEFG":
            _set(ws, f"{col}{n}", f"=SUM({col}{first}:{col}{last})", MONEY)
        _set(ws, f"H{n}", f'=IF(F{n}=0,"{DASH}",{base}{n}/F{n})', COEF)
        last_formula = (
            f'=IF(F{n}=0,"{DASH}",{base}{n}/F{n}*100)'
            if summary.config.last_column is LastColumn.EFFICIENCY
            else f"=SUM(I{first}:I{last})"
        )
        _set(ws, f"I{n}", last_formula, PCT)
    else:
        for col, value in zip(
            "CDEFG", (t.sales_net, t.service, t.sales_total, t.cost, t.gross), strict=True
        ):
            _set(ws, f"{col}{n}", _num(value), MONEY)
        _set(ws, f"H{n}", _ratio_or_dash(t.coefficient), COEF)
        _set(ws, f"I{n}", _ratio_or_dash(summary.last_value(t)), PCT)
    for col in _SUMMARY_COLS:
        cell = ws[f"{col}{n}"]
        cell.font = _BOLD
        cell.fill = _TOTAL_FILL
        cell.border = _TOTAL_BORDER


def _notes(summary: SalesSummary) -> list[str]:
    notes = [
        f"Валовый доход, коэффициент и доля считаются от {margin_base_label(summary)}.",
        "Валовый доход = продажи − себестоимость. "
        "Коэффициент = продажи / себестоимость (сколько тенге продаж на 1 тг себестоимости).",
        "Как строки собраны из позиций — на листе «Позиции».",
    ]
    rec = summary.reconciliation
    if rec is not None:
        if rec.ok:
            notes.append(
                "Сверка с итогом файла iiko: совпадает "
                f"({_money_text(rec.file_revenue)} тг с обслуживанием)."
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
        "Без обслуживания, тг",
        "Обслуживание, тг",
        "С обслуживанием, тг",
        "Себестоимость, тг",
        "Валовый доход, тг",
        "Коэффициент",
    ]
    _header_row(ws, heads)
    base = _base_col(summary, without="E", with_="G")
    n = 2
    for group in summary.groups:
        for item in group.items:
            ws.cell(row=n, column=1, value=group.name)
            ws.cell(row=n, column=2, value=item.source_group)
            ws.cell(row=n, column=3, value=item.name)
            ws.cell(row=n, column=4, value=float(item.quantity)).number_format = "0.##"
            ws.cell(row=n, column=5, value=_num(item.sales_net))
            ws.cell(row=n, column=6, value=_num(item.service))
            ws.cell(row=n, column=8, value=_num(item.cost))
            if options.formulas:
                ws.cell(row=n, column=7, value=f"=E{n}+F{n}")
                ws.cell(row=n, column=9, value=f"={base}{n}-H{n}")
                ws.cell(row=n, column=10, value=f'=IF(H{n}=0,"{DASH}",{base}{n}/H{n})')
            else:
                ws.cell(row=n, column=7, value=_num(item.sales_total))
                ws.cell(row=n, column=9, value=_num(item.gross))
                ws.cell(row=n, column=10, value=_ratio_or_dash(item.coefficient))
            for col in range(5, 10):
                ws.cell(row=n, column=col).number_format = MONEY
            ws.cell(row=n, column=10).number_format = COEF
            n += 1
    _finish_table(ws, heads, n - 1, widths=(16, 20, 44, 11, 15, 14, 15, 15, 15, 12))


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
