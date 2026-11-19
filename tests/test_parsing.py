from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from resto_analytics.domain.models import SalesReport
from resto_analytics.parsing.errors import ParseError
from resto_analytics.parsing.iiko_sales import Field, classify_header, parse_sales_report
from tests.factories import IIKO_COLUMNS, SAMPLE_LINES, Line, make_iiko_xlsx


def test_reads_all_lines_and_meta(sample_report: SalesReport) -> None:
    assert len(sample_report.lines) == len(SAMPLE_LINES)
    meta = sample_report.meta
    assert meta.title == "Отчет о продажах с 01.11.26 по 30.11.26"
    assert meta.date_from == date(2026, 11, 1)
    assert meta.date_to == date(2026, 11, 30)
    assert meta.period_label == "01.11.2026 – 30.11.2026"
    assert meta.warehouses == (
        "Бар склад Точка 2",
        "Основной склад Точка 2",
        "Кухня склад Точка 2",
    )
    assert meta.sheet_name == "Отчет о продажах"


def test_line_values(sample_report: SalesReport) -> None:
    tea = sample_report.lines[0]
    assert (tea.group, tea.category, tea.item) == ("Горячие напитки", "Бар", "Ташкентский чай")
    assert tea.quantity == 10
    assert tea.revenue_gross == Decimal(6900)
    assert tea.discount == Decimal(-690)
    assert tea.service_surcharge == Decimal(690)
    assert tea.revenue == Decimal(7590)
    assert tea.cost == Decimal(650)
    assert tea.unit_price == Decimal(690)
    assert tea.unit_cost == Decimal(65)
    assert tea.row_number == 5  # строки 1–3 заголовок, 4 — шапка


def test_file_totals_are_read(sample_report: SalesReport) -> None:
    assert sample_report.file_totals is not None
    assert sample_report.file_totals.revenue == sum(ln.revenue for ln in SAMPLE_LINES)
    assert sample_report.file_totals.cost == sum(ln.cost for ln in SAMPLE_LINES)


def test_columns_found_by_name_not_position() -> None:
    shuffled = list(reversed(list(IIKO_COLUMNS)))
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, columns=shuffled))
    assert report.lines[0].item == "Ташкентский чай"
    assert report.lines[0].revenue == Decimal(7590)


def test_revenue_derived_when_column_missing() -> None:
    cols = [c for c in IIKO_COLUMNS if c != "Выручка, тг."]
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, columns=cols, with_total=False))
    assert report.lines[0].revenue == Decimal(7590)  # 6900 − (−690)
    assert report.file_totals is None


def test_gross_derived_when_column_missing() -> None:
    cols = [c for c in IIKO_COLUMNS if c != "Выручка без вычета скидок, тг."]
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, columns=cols))
    assert report.lines[0].revenue_gross == Decimal(6900)


def test_group_is_filled_down_when_iiko_leaves_it_blank() -> None:
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, blank_repeated_groups=True))
    assert report.lines[1].group == "Горячие напитки"


def test_only_category_column() -> None:
    cols = [c for c in IIKO_COLUMNS if c not in {"Группа", "Элемент номенклатуры"}]
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, columns=cols))
    assert {ln.group for ln in report.lines} == {ln.category for ln in report.lines}
    assert report.lines[0].item == "Бар"  # без названия позиции подставляется группа


def test_works_without_title_rows() -> None:
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, with_meta=False))
    assert report.meta.title == "Отчет о продажах"
    assert report.meta.date_from is None
    assert report.meta.period_label == ""
    assert len(report.lines) == len(SAMPLE_LINES)


def test_finds_table_on_second_sheet() -> None:
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, leading_sheet=True))
    assert report.meta.sheet_name == "Отчет"


def test_numbers_stored_as_text_are_understood() -> None:
    data = make_iiko_xlsx(SAMPLE_LINES, cell_overrides={(0, "Выручка, тг."): "7 590,00"})
    assert parse_sales_report(data).lines[0].revenue == Decimal(7590)


def test_bad_number_points_to_row_and_column() -> None:
    data = make_iiko_xlsx(SAMPLE_LINES, cell_overrides={(2, "Себестоимость, тг."): "много"})
    with pytest.raises(ParseError, match=r"Строка 7, столбец «Себестоимость»"):
        parse_sales_report(data)


def test_accepts_path_and_file_object(tmp_path: Path, sample_xlsx: bytes) -> None:
    path = tmp_path / "report.xlsx"
    path.write_bytes(sample_xlsx)
    assert len(parse_sales_report(path).lines) == len(SAMPLE_LINES)
    with path.open("rb") as fh:
        assert len(parse_sales_report(fh).lines) == len(SAMPLE_LINES)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "пустой"),
        (b"not an excel file", "как Excel"),
    ],
)
def test_broken_files(data: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_sales_report(data)


def test_excel_without_sales_table() -> None:
    data = make_iiko_xlsx([], columns=["Группа", "Количество"])
    with pytest.raises(ParseError, match="Не нашёл таблицу продаж"):
        parse_sales_report(data)


def test_header_without_rows_is_not_a_report() -> None:
    with pytest.raises(ParseError, match="Не нашёл таблицу продаж"):
        parse_sales_report(make_iiko_xlsx([]))


def test_total_row_is_not_a_line() -> None:
    lines = [Line("Плов", "Плов", "Плов", 1, 100, 50)]
    report = parse_sales_report(make_iiko_xlsx(lines))
    assert [ln.item for ln in report.lines] == ["Плов"]


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Группа", Field.GROUP),
        ("Категория", Field.CATEGORY),
        ("Элемент номенклатуры", Field.ITEM),
        ("Выручка без вычета скидок, тг.", Field.REVENUE_GROSS),
        ("Выручка, тг.", Field.REVENUE),
        ("Сумма скидок, тг.", Field.DISCOUNT),
        ("Себестоимость, тг.", Field.COST),
        ("  СЕБЕСТОИМОСТЬ,\nтг. ", Field.COST),
        ("Себес. за ед., тг.", None),  # себестоимость за единицу нам не нужна
        ("Средняя цена без вычета скидок, тг.", None),
        (None, None),
    ],
)
def test_classify_header(header: object, field: Field | None) -> None:
    assert classify_header(header) is field
