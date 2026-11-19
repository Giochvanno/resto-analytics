"""Итоги посчитаны вручную по SAMPLE_LINES (tests/factories.py):

Бар    = Ташкентский чай 7590 + Чайник 2640 + Пахлава 2200 + Куырдак 10120 = 22 550
         себестоимость 650 + 60 + 1200 + 8200 = 10 110, обслуживание 690 + 240 + 200 + 920 = 2050
Лагман = 3267 (в iiko лежит в категории «Бар», но по настройке идёт отдельной строкой)
Плов   = 13 134 + 5400 = 18 534, себестоимость 6690 + 1068 = 7758, обслуживание 1194
Самса  = 38 500, себестоимость 24 100
Супы   = 3520, Штрафы = 1000
Итого  = 87 371, себестоимость 41 974
"""

from decimal import Decimal

import pytest

from resto_analytics.config import (
    GroupBy,
    LastColumn,
    SalesSource,
    ServiceSource,
    SummaryConfig,
)
from resto_analytics.domain.models import SalesReport
from resto_analytics.reports.group_summary import GroupRow, SalesSummary, build_group_summary


def by_name(summary: SalesSummary) -> dict[str, GroupRow]:
    return {g.name: g for g in summary.groups}


def test_default_rows_and_order(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report)
    # Порядок из row_order (Салатов и Шашлыков в примере нет), дальше — по убыванию продаж
    assert [g.name for g in summary.groups] == ["Бар", "Плов", "Самса", "Лагман", "Супы", "Штрафы"]


def test_group_sums(sample_report: SalesReport) -> None:
    rows = by_name(build_group_summary(sample_report))
    bar = rows["Бар"]
    assert bar.sales == Decimal(22550)
    assert bar.cost == Decimal(10110)
    assert bar.service == Decimal(2050)
    assert bar.gross == Decimal(12440)
    assert bar.sources == ("Горячие напитки", "Десерты", "Куырдак")
    assert rows["Плов"].sales == Decimal(18534)
    assert rows["Плов"].cost == Decimal(7758)
    assert rows["Плов"].service == Decimal(1194)  # у агрегатора обслуживания нет
    assert rows["Самса"].sales == Decimal(38500)


def test_lagman_is_split_out_of_bar(sample_report: SalesReport) -> None:
    rows = by_name(build_group_summary(sample_report))
    assert rows["Лагман"].sales == Decimal(3267)
    assert rows["Лагман"].sources == ("Лагман",)
    assert all(i.source_group != "Лагман" for i in rows["Бар"].items)


def test_totals_and_ratios(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report)
    total = summary.total
    assert total.sales == Decimal(87371)
    assert total.cost == Decimal(41974)
    assert total.gross == Decimal(45397)
    assert total.service == Decimal(7361)
    assert total.share == Decimal(100)
    assert sum(g.share for g in summary.groups) == pytest.approx(Decimal(100))
    samsa = by_name(summary)["Самса"]
    assert round(samsa.coefficient or 0, 4) == Decimal("1.5975")  # 38500 / 24100
    assert round(samsa.share, 2) == Decimal("44.06")  # 38500 / 87371 × 100


def test_zero_cost_group_has_no_coefficient(sample_report: SalesReport) -> None:
    lagman = by_name(build_group_summary(sample_report))["Лагман"]
    assert lagman.coefficient is None
    assert lagman.efficiency is None


def test_items_sorted_by_sales(sample_report: SalesReport) -> None:
    bar = by_name(build_group_summary(sample_report))["Бар"]
    assert [i.name for i in bar.items] == [
        "Куырдак",
        "Ташкентский чай",
        "Чайник черного чая",
        "Пахлава",
    ]
    assert bar.items[0].gross == Decimal(1920)
    assert sum(i.sales for i in bar.items) == bar.sales


def test_group_by_iiko_group(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(group_by=GroupBy.GROUP, group_overrides={})
    names = {g.name for g in build_group_summary(sample_report, cfg).groups}
    assert {"Горячие напитки", "Десерты", "Куырдак", "Лагман"} <= names
    assert "Бар" not in names


def test_overrides_merge_groups(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(group_overrides={"Супы": "Плов", "Лагман": "Лагман"})
    rows = by_name(build_group_summary(sample_report, cfg))
    assert "Супы" not in rows
    assert rows["Плов"].sales == Decimal(18534 + 3520)


def test_exclude_groups(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(exclude_groups=("штрафы",)))
    assert "Штрафы" not in by_name(summary)
    assert summary.excluded_lines == 1
    assert summary.total.sales == Decimal(87371 - 1000)
    assert summary.line_count == 10


def test_sales_without_service(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(sales_source=SalesSource.REVENUE_GROSS)
    summary = build_group_summary(sample_report, cfg)
    assert by_name(summary)["Бар"].sales == Decimal(22550 - 2050)
    assert summary.total.sales == Decimal(87371 - 7361)


@pytest.mark.parametrize(
    ("source", "expected_bar_service"),
    [
        (ServiceSource.FILE, Decimal(2050)),
        (ServiceSource.PERCENT, Decimal(2255)),  # 10% от 22 550
        (ServiceSource.NONE, Decimal(0)),
    ],
)
def test_service_sources(
    sample_report: SalesReport, source: ServiceSource, expected_bar_service: Decimal
) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(service_source=source))
    assert by_name(summary)["Бар"].service == expected_bar_service


def test_last_column(sample_report: SalesReport) -> None:
    share = build_group_summary(sample_report)
    eff = build_group_summary(sample_report, SummaryConfig(last_column=LastColumn.EFFICIENCY))
    samsa_share = by_name(share)["Самса"]
    samsa_eff = by_name(eff)["Самса"]
    assert share.last_value(samsa_share) == samsa_share.share
    assert eff.last_value(samsa_eff) == samsa_eff.efficiency
    assert round(eff.last_value(samsa_eff) or 0, 1) == Decimal("159.8")
    assert eff.last_value(by_name(eff)["Лагман"]) is None


def test_everything_excluded_gives_empty_summary(sample_report: SalesReport) -> None:
    cats = tuple({ln.category for ln in sample_report.lines})
    summary = build_group_summary(sample_report, SummaryConfig(exclude_groups=cats))
    assert summary.groups == ()
    assert summary.total.sales == 0
    assert summary.total.share == 0
