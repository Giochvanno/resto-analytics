import io
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from resto_analytics.config import LastColumn, SalesSource, SummaryConfig
from resto_analytics.domain.models import ReportMeta, SalesReport
from resto_analytics.export.excel import ExcelOptions, summary_filename, write_summary_xlsx
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import SalesSummary, build_group_summary
from tests.factories import Line, make_iiko_xlsx


def open_sheet(content: bytes, name: str = "Сводка") -> Worksheet:
    return load_workbook(io.BytesIO(content))[name]


def rows_by_name(ws: Worksheet) -> dict[str, tuple[object, ...]]:
    out: dict[str, tuple[object, ...]] = {}
    for row in ws.iter_rows(min_row=5, min_col=2, max_col=8, values_only=True):
        if isinstance(row[0], str) and row[1] is not None:
            out[row[0]] = row
    return out


@pytest.fixture
def summary(sample_report: SalesReport) -> SalesSummary:
    return build_group_summary(sample_report)


def test_layout_matches_example_sheet(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary))
    assert ws["B2"].value == "Отчет о продажах с 01.11.26 по 30.11.26"
    assert [c.value for c in ws[4][1:8]] == [
        "Продажа по группам",
        "Сумма продаж, тг",
        "Себестоимость, тг",
        "Валовый доход, тг",
        "Обслуживание 10%, тг",
        "Средний коэффициент (сумма / себестоимость)",
        "Доля в продажах, %",
    ]
    assert ws.freeze_panes == "C5"


def test_values(summary: SalesSummary) -> None:
    rows = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    assert rows["Бар"][1:5] == (22550, 10110, 12440, 2050)
    assert rows["Бар"][5] == pytest.approx(22550 / 10110)
    assert rows["Лагман"][5] == "—"
    assert rows["Итого"][1:4] == (87371, 41974, 45397)
    assert rows["Итого"][6] == pytest.approx(100)


def test_notes_mention_reconciliation(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary))
    notes = [c.value for c in ws["B"] if isinstance(c.value, str)]
    assert any("совпадает (87 371 тг)" in n for n in notes)
    assert any("Проверка данных" in n for n in notes)


def test_formulas_mode(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary, ExcelOptions(formulas=True)))
    first, total = 5, 5 + len(summary.groups)
    assert ws[f"E{first}"].value == f"=C{first}-D{first}"
    assert ws[f"G{first}"].value == f'=IF(D{first}=0,"—",C{first}/D{first})'
    assert ws[f"H{first}"].value == f"=C{first}/C${total}*100"
    assert ws[f"C{total}"].value == f"=SUM(C{first}:C{total - 1})"
    assert ws[f"H{total}"].value == f"=SUM(H{first}:H{total - 1})"


def test_efficiency_formulas(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(last_column=LastColumn.EFFICIENCY, sales_source=SalesSource.REVENUE_GROSS)
    summary = build_group_summary(sample_report, cfg)
    content = write_summary_xlsx(summary, ExcelOptions(formulas=True))
    ws = open_sheet(content)
    total = 5 + len(summary.groups)
    assert ws["C4"].value == "Сумма продаж без обслуживания, тг"
    assert ws["H4"].value.startswith("Эффективность")
    assert ws["H5"].value == '=IF(D5=0,"—",C5/D5*100)'
    assert ws[f"H{total}"].value == f'=IF(D{total}=0,"—",C{total}/D{total}*100)'
    values = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    assert values["Лагман"][6] == "—"


def test_items_sheet_explains_where_numbers_come_from(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary), "Позиции")
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == summary.line_count
    bar_rows = [r for r in rows if r[0] == "Бар"]
    assert {r[1] for r in bar_rows} == {"Горячие напитки", "Десерты", "Куырдак"}
    assert sum(r[4] for r in bar_rows) == 22550  # type: ignore[misc]
    assert ws.auto_filter.ref == f"A1:H{len(rows) + 1}"


def test_items_sheet_formulas(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary, ExcelOptions(formulas=True)), "Позиции")
    assert ws["G2"].value == "=E2-F2"
    assert ws["H2"].value == '=IF(F2=0,"—",E2/F2)'


def test_issues_sheet(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary), "Проверка данных")
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert [r[1] for r in rows] == ["Гуйру Лагман", "Домашние пельмени (суп)", "Куырдак"]
    assert rows[0][0] == "Себестоимость 0"
    assert rows[2][6] == 8  # строка в исходном файле


def test_no_issues_no_issues_sheet() -> None:
    report = parse_sales_report(make_iiko_xlsx([Line("Плов", "Плов", "Плов", 2, 1000, 400)]))
    content = write_summary_xlsx(build_group_summary(report))
    assert load_workbook(io.BytesIO(content)).sheetnames == ["Сводка", "Позиции"]


def test_filename(summary: SalesSummary) -> None:
    assert summary_filename(summary) == "Сводка_продаж_01.11.26-30.11.26.xlsx"
    empty = SalesReport(meta=ReportMeta(title="x"), lines=())
    assert summary_filename(build_group_summary(empty)) == "Сводка_продаж.xlsx"
    dated = SalesReport(meta=ReportMeta("x", date(2026, 12, 1), date(2026, 12, 31)), lines=())
    assert summary_filename(build_group_summary(dated)) == "Сводка_продаж_01.12.26-31.12.26.xlsx"


def test_reconciliation_warning_in_notes() -> None:
    lines = [Line("Плов", "Плов", "Плов", 2, 1000, 400)]
    data = make_iiko_xlsx(lines, total_override={"Выручка, тг.": 1.0})
    ws = open_sheet(write_summary_xlsx(build_group_summary(parse_sales_report(data))))
    assert any(isinstance(c.value, str) and c.value.startswith("Внимание") for c in ws["B"])


def test_excluded_lines_in_notes(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(exclude_groups=("Штрафы",)))
    ws = open_sheet(write_summary_xlsx(summary))
    assert any(isinstance(c.value, str) and "Не учтено" in c.value for c in ws["B"])


@pytest.mark.libreoffice
@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice не установлен")
def test_formulas_give_same_numbers_as_values(summary: SalesSummary, tmp_path: Path) -> None:
    """Пересчитываем формулы настоящим табличным движком и сравниваем с нашими значениями."""
    src = tmp_path / "formulas.xlsx"
    src.write_bytes(write_summary_xlsx(summary, ExcelOptions(formulas=True)))
    out_dir = tmp_path / "out"
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--calc",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(out_dir),
            str(src),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    recalculated = load_workbook(out_dir / "formulas.xlsx", data_only=True)["Сводка"]
    expected = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    for name, row in rows_by_name(recalculated).items():
        for got, want in zip(row[1:], expected[name][1:], strict=True):
            if isinstance(want, str):
                assert got == want
            else:
                assert got == pytest.approx(want, abs=0.01), name
