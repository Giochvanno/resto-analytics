import io
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from resto_analytics.config import LastColumn, MarginBase, SummaryConfig
from resto_analytics.domain.models import ReportMeta, SalesReport
from resto_analytics.export.excel import ExcelOptions, summary_filename, write_summary_xlsx
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import SalesSummary, build_group_summary
from tests.factories import Line, make_iiko_xlsx

# Столбцы листа «Сводка»: B группа, C без обслуж., D обслуж., E с обслуж.,
# F себестоимость, G валовый доход, H коэффициент, I доля / эффективность
NAME, NET, SERVICE, TOTAL, COST, GROSS, COEF, LAST = range(8)


def open_sheet(content: bytes, name: str = "Сводка") -> Worksheet:
    return load_workbook(io.BytesIO(content))[name]


def rows_by_name(ws: Worksheet) -> dict[str, tuple[object, ...]]:
    out: dict[str, tuple[object, ...]] = {}
    for row in ws.iter_rows(min_row=5, min_col=2, max_col=9, values_only=True):
        if isinstance(row[NAME], str) and row[NET] is not None:
            out[row[NAME]] = row
    return out


@pytest.fixture
def summary(sample_report: SalesReport) -> SalesSummary:
    return build_group_summary(sample_report)


def test_layout(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary))
    assert ws["B2"].value == "Отчет о продажах с 01.11.26 по 30.11.26"
    assert [c.value for c in ws[4][1:9]] == [
        "Продажа по группам",
        "Продажи без обслуживания, тг",
        "Обслуживание 10%, тг",
        "Продажи с обслуживанием, тг",
        "Себестоимость, тг",
        "Валовый доход, тг",
        "Средний коэффициент (продажи / себестоимость)",
        "Доля в продажах, %",
    ]
    assert ws.freeze_panes == "C5"


def test_values(summary: SalesSummary) -> None:
    rows = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    assert rows["Бар"][NET : GROSS + 1] == (20500, 2050, 22550, 10110, 10390)
    assert rows["Бар"][COEF] == pytest.approx(20500 / 10110)
    assert rows["Лагман"][COEF] == "—"
    assert rows["Итого"][NET : GROSS + 1] == (80010, 7361, 87371, 41974, 38036)
    assert rows["Итого"][LAST] == pytest.approx(100)


def test_values_with_service_base(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(margin_base=MarginBase.WITH_SERVICE))
    rows = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    assert rows["Бар"][GROSS] == 12440  # 22 550 − 10 110
    assert rows["Итого"][GROSS] == 45397


def test_notes(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary))
    notes = [c.value for c in ws["B"] if isinstance(c.value, str)]
    assert any("считаются от продаж без обслуживания" in n for n in notes)
    assert any("совпадает (87 371 тг с обслуживанием)" in n for n in notes)
    assert any("Проверка данных" in n for n in notes)


@pytest.mark.parametrize(
    ("base", "col"),
    [(MarginBase.WITHOUT_SERVICE, "C"), (MarginBase.WITH_SERVICE, "E")],
)
def test_formulas_mode(sample_report: SalesReport, base: MarginBase, col: str) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(margin_base=base))
    ws = open_sheet(write_summary_xlsx(summary, ExcelOptions(formulas=True)))
    first, total = 5, 5 + len(summary.groups)
    assert ws[f"E{first}"].value == f"=C{first}+D{first}"
    assert ws[f"G{first}"].value == f"={col}{first}-F{first}"
    assert ws[f"H{first}"].value == f'=IF(F{first}=0,"—",{col}{first}/F{first})'
    assert ws[f"I{first}"].value == f"={col}{first}/{col}${total}*100"
    assert ws[f"C{total}"].value == f"=SUM(C{first}:C{total - 1})"
    assert ws[f"G{total}"].value == f"=SUM(G{first}:G{total - 1})"
    assert ws[f"H{total}"].value == f'=IF(F{total}=0,"—",{col}{total}/F{total})'
    assert ws[f"I{total}"].value == f"=SUM(I{first}:I{total - 1})"


def test_efficiency_column(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(last_column=LastColumn.EFFICIENCY))
    total = 5 + len(summary.groups)
    ws = open_sheet(write_summary_xlsx(summary, ExcelOptions(formulas=True)))
    assert ws["I4"].value.startswith("Эффективность")
    assert ws["I5"].value == '=IF(F5=0,"—",C5/F5*100)'
    assert ws[f"I{total}"].value == f'=IF(F{total}=0,"—",C{total}/F{total}*100)'
    values = rows_by_name(open_sheet(write_summary_xlsx(summary)))
    assert values["Лагман"][LAST] == "—"
    assert values["Самса"][LAST] == pytest.approx(35000 / 24100 * 100)


def test_items_sheet_explains_where_numbers_come_from(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary), "Позиции")
    assert [c.value for c in ws[1]][4:7] == [
        "Без обслуживания, тг",
        "Обслуживание, тг",
        "С обслуживанием, тг",
    ]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(rows) == summary.line_count
    bar_rows = [r for r in rows if r[0] == "Бар"]
    assert {r[1] for r in bar_rows} == {"Горячие напитки", "Десерты", "Куырдак"}
    assert sum(r[4] for r in bar_rows) == 20500  # type: ignore[misc]
    assert sum(r[6] for r in bar_rows) == 22550  # type: ignore[misc]
    assert ws.auto_filter.ref == f"A1:J{len(rows) + 1}"


@pytest.mark.parametrize(
    ("base", "col"),
    [(MarginBase.WITHOUT_SERVICE, "E"), (MarginBase.WITH_SERVICE, "G")],
)
def test_items_sheet_formulas(sample_report: SalesReport, base: MarginBase, col: str) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(margin_base=base))
    ws = open_sheet(write_summary_xlsx(summary, ExcelOptions(formulas=True)), "Позиции")
    assert ws["G2"].value == "=E2+F2"
    assert ws["I2"].value == f"={col}2-H2"
    assert ws["J2"].value == f'=IF(H2=0,"—",{col}2/H2)'


def test_issues_sheet(summary: SalesSummary) -> None:
    ws = open_sheet(write_summary_xlsx(summary), "Проверка данных")
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert [r[1] for r in rows] == ["Гуйру Лагман", "Домашние пельмени (суп)", "Куырдак"]
    assert rows[0][0] == "Себестоимость 0"
    assert rows[2][3] == 9200  # продажи без обслуживания
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
@pytest.mark.parametrize("base", list(MarginBase))
def test_formulas_give_same_numbers_as_values(
    sample_report: SalesReport, base: MarginBase, tmp_path: Path
) -> None:
    """Пересчитываем формулы настоящим табличным движком и сравниваем с нашими значениями."""
    summary = build_group_summary(sample_report, SummaryConfig(margin_base=base))
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
    got = rows_by_name(recalculated)
    assert got.keys() == expected.keys()
    for name, row in got.items():
        for value, want in zip(row[1:], expected[name][1:], strict=True):
            if isinstance(want, str):
                assert value == want
            else:
                assert value == pytest.approx(want, abs=0.01), name
