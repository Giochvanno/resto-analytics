"""Итоги посчитаны вручную по SAMPLE_LINES (tests/factories.py).

        без обслуж. + обслуж. = с обслуж.   себестоимость
Бар        20 500   + 2 050   = 22 550     10 110   (чай 6900, чайник 2400, пахлава 2000,
                                                     куырдак 9200)
Плов       17 340   + 1 194   = 18 534      7 758   (у агрегатора обслуживания нет)
Самса      35 000   + 3 500   = 38 500     24 100
Лагман      2 970   +   297   =  3 267          0   (в iiko лежит в «Баре», по настройке — отдельно)
Супы        3 200   +   320   =  3 520          6
Штрафы      1 000   +     0   =  1 000          0
Итого      80 010   + 7 361   = 87 371     41 974

По умолчанию доход и коэффициент считаются от продаж без обслуживания:
валовый доход 80 010 − 41 974 = 38 036, коэффициент 80 010 / 41 974 = 1,9062.
"""

from decimal import Decimal

import pytest

from resto_analytics.config import (
    GroupBy,
    LastColumn,
    MarginBase,
    ServiceSource,
    SummaryConfig,
)
from resto_analytics.domain.models import SalesReport
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import GroupRow, SalesSummary, build_group_summary
from tests.factories import Line, make_iiko_xlsx

WITH_SERVICE = SummaryConfig(margin_base=MarginBase.WITH_SERVICE)


def by_name(summary: SalesSummary) -> dict[str, GroupRow]:
    return {g.name: g for g in summary.groups}


def test_default_rows_and_order(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report)
    # Порядок из row_order (Салатов и Шашлыков в примере нет), дальше — по убыванию продаж
    assert [g.name for g in summary.groups] == ["Бар", "Плов", "Самса", "Лагман", "Супы", "Штрафы"]


def test_three_sales_columns(sample_report: SalesReport) -> None:
    rows = by_name(build_group_summary(sample_report))
    bar = rows["Бар"]
    assert (bar.sales_net, bar.service, bar.sales_total) == (20500, 2050, 22550)
    assert bar.cost == Decimal(10110)
    assert bar.sources == ("Горячие напитки", "Десерты", "Куырдак")
    plov = rows["Плов"]
    assert (plov.sales_net, plov.service, plov.sales_total) == (17340, 1194, 18534)
    for row in rows.values():
        assert row.sales_net + row.service == row.sales_total


def test_margin_is_from_sales_without_service_by_default(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report)
    samsa = by_name(summary)["Самса"]
    assert samsa.sales == samsa.sales_net == Decimal(35000)
    assert samsa.gross == Decimal(10900)
    assert round(samsa.coefficient or 0, 4) == Decimal("1.4523")  # 35 000 / 24 100
    assert round(samsa.share, 2) == Decimal("43.74")  # 35 000 / 80 010 × 100


def test_margin_with_service(sample_report: SalesReport) -> None:
    samsa = by_name(build_group_summary(sample_report, WITH_SERVICE))["Самса"]
    assert samsa.sales == samsa.sales_total == Decimal(38500)
    assert samsa.gross == Decimal(14400)
    assert round(samsa.coefficient or 0, 4) == Decimal("1.5975")  # 38 500 / 24 100
    assert round(samsa.share, 2) == Decimal("44.06")  # 38 500 / 87 371 × 100


def test_totals(sample_report: SalesReport) -> None:
    total = build_group_summary(sample_report).total
    assert (total.sales_net, total.service, total.sales_total) == (80010, 7361, 87371)
    assert total.cost == Decimal(41974)
    assert total.gross == Decimal(38036)
    assert round(total.coefficient or 0, 4) == Decimal("1.9062")
    assert total.share == Decimal(100)

    with_service = build_group_summary(sample_report, WITH_SERVICE).total
    assert with_service.gross == Decimal(45397)


def test_shares_add_up_to_100(sample_report: SalesReport) -> None:
    for cfg in (SummaryConfig(), WITH_SERVICE):
        summary = build_group_summary(sample_report, cfg)
        assert sum(g.share for g in summary.groups) == pytest.approx(Decimal(100))


def test_lagman_is_split_out_of_bar(sample_report: SalesReport) -> None:
    rows = by_name(build_group_summary(sample_report))
    assert rows["Лагман"].sales_total == Decimal(3267)
    assert rows["Лагман"].sources == ("Лагман",)
    assert all(i.source_group != "Лагман" for i in rows["Бар"].items)


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
    kuyrdak = bar.items[0]
    assert (kuyrdak.sales_net, kuyrdak.service, kuyrdak.sales_total) == (9200, 920, 10120)
    assert kuyrdak.gross == Decimal(1000)
    assert sum(i.sales_net for i in bar.items) == bar.sales_net


def test_real_discount_is_not_service() -> None:
    """Настоящая скидка (положительная «Сумма скидок») уменьшает продажи, но это не обслуживание."""
    line = Line("Плов", "Плов", "Плов по акции", 10, 2000, 900)
    data = make_iiko_xlsx(
        [line],
        cell_overrides={(0, "Сумма скидок, тг."): 2000.0, (0, "Выручка, тг."): 18000.0},
        with_total=False,
    )
    plov = build_group_summary(parse_sales_report(data)).groups[0]
    assert plov.service == 0
    assert plov.sales_net == plov.sales_total == Decimal(18000)


def test_group_by_iiko_group(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(group_by=GroupBy.GROUP, group_overrides={})
    names = {g.name for g in build_group_summary(sample_report, cfg).groups}
    assert {"Горячие напитки", "Десерты", "Куырдак", "Лагман"} <= names
    assert "Бар" not in names


def test_overrides_merge_groups(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(group_overrides={"Супы": "Плов", "Лагман": "Лагман"})
    rows = by_name(build_group_summary(sample_report, cfg))
    assert "Супы" not in rows
    assert rows["Плов"].sales_net == Decimal(17340 + 3200)


def test_exclude_groups(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report, SummaryConfig(exclude_groups=("штрафы",)))
    assert "Штрафы" not in by_name(summary)
    assert summary.excluded_lines == 1
    assert summary.total.sales_net == Decimal(80010 - 1000)
    assert summary.line_count == 10


@pytest.mark.parametrize(
    ("source", "expected_bar_service"),
    [
        (ServiceSource.FILE, Decimal(2050)),
        (ServiceSource.PERCENT, Decimal(2050)),  # 10% от 20 500 — в примере совпадает с файлом
        (ServiceSource.NONE, Decimal(0)),
    ],
)
def test_service_sources(
    sample_report: SalesReport, source: ServiceSource, expected_bar_service: Decimal
) -> None:
    bar = by_name(build_group_summary(sample_report, SummaryConfig(service_source=source)))["Бар"]
    assert bar.service == expected_bar_service
    assert bar.sales_net == Decimal(20500)  # продажи без обслуживания от этого не меняются
    assert bar.sales_total == bar.sales_net + expected_bar_service


def test_percent_service_uses_configured_rate(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(service_source=ServiceSource.PERCENT, service_percent=Decimal(15))
    plov = by_name(build_group_summary(sample_report, cfg))["Плов"]
    assert plov.service == Decimal(2601)  # 15% от 17 340, включая доставку


def test_last_column(sample_report: SalesReport) -> None:
    share = build_group_summary(sample_report)
    eff = build_group_summary(sample_report, SummaryConfig(last_column=LastColumn.EFFICIENCY))
    samsa_share = by_name(share)["Самса"]
    samsa_eff = by_name(eff)["Самса"]
    assert share.last_value(samsa_share) == samsa_share.share
    assert eff.last_value(samsa_eff) == samsa_eff.efficiency
    assert round(eff.last_value(samsa_eff) or 0, 1) == Decimal("145.2")
    assert eff.last_value(by_name(eff)["Лагман"]) is None


def test_everything_excluded_gives_empty_summary(sample_report: SalesReport) -> None:
    cats = tuple({ln.category for ln in sample_report.lines})
    summary = build_group_summary(sample_report, SummaryConfig(exclude_groups=cats))
    assert summary.groups == ()
    assert summary.total.sales == 0
    assert summary.total.share == 0
