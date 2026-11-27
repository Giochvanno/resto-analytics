from decimal import Decimal

from resto_analytics.config import MarginBase, SummaryConfig
from resto_analytics.domain.models import SalesReport
from resto_analytics.insights import build_overview
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.data_checks import IssueKind
from resto_analytics.reports.group_summary import build_group_summary
from tests.factories import SAMPLE_LINES, Line, make_iiko_xlsx


def test_totals(sample_report: SalesReport) -> None:
    ov = build_overview(build_group_summary(sample_report))
    assert (ov.sales_net, ov.service, ov.sales_total) == (80010, 7361, 87371)
    assert ov.gross == Decimal(38036)
    assert round(ov.coefficient or 0, 2) == Decimal("1.91")
    assert ov.reconciled is True
    assert ov.margin_base is MarginBase.WITHOUT_SERVICE
    assert ov.title == "Отчет о продажах с 01.11.26 по 30.11.26"


def test_top_sellers(sample_report: SalesReport) -> None:
    ov = build_overview(build_group_summary(sample_report))
    assert [g.name for g in ov.top_sellers] == ["Самса", "Бар", "Плов"]
    assert ov.top_sellers[0].sales == Decimal(35000)


def test_best_and_worst_margin_skip_tiny_and_costless_groups(sample_report: SalesReport) -> None:
    ov = build_overview(build_group_summary(sample_report))
    # Супы: коэф. 533 (себестоимость 6 тг) — но 4% продаж, поэтому участвует.
    # Штрафы и Лагман без себестоимости, в сравнение не попадают.
    assert [g.name for g in ov.best_margin] == ["Супы", "Плов"]
    assert [g.name for g in ov.worst_margin] == ["Самса", "Бар"]
    names = {g.name for g in (*ov.best_margin, *ov.worst_margin)}
    assert not names & {"Лагман", "Штрафы"}


def test_best_and_worst_never_overlap() -> None:
    lines = [
        Line("Плов", "Плов", "Плов", 10, 1000, 500),
        Line("Самса", "Самса", "Самса", 10, 1000, 400),
    ]
    ov = build_overview(build_group_summary(parse_sales_report(make_iiko_xlsx(lines))))
    assert [g.name for g in ov.best_margin] == ["Самса", "Плов"]
    assert ov.worst_margin == ()


def test_issue_facts(sample_report: SalesReport) -> None:
    ov = build_overview(build_group_summary(sample_report))
    assert [(i.kind, i.count) for i in ov.issues] == [
        (IssueKind.ZERO_COST, 1),
        (IssueKind.SUSPICIOUS_COST, 1),
        (IssueKind.LOW_MARGIN, 1),
    ]
    assert ov.issues[2].examples[0].item == "Куырдак"
    assert ov.issue_count == 3


def test_examples_are_limited_and_sorted_by_sales() -> None:
    lines = [Line("Лагман", "Лагман", f"Лагман {n}", n, 1000, 0) for n in range(1, 6)]
    ov = build_overview(build_group_summary(parse_sales_report(make_iiko_xlsx(lines))))
    zero = ov.issues[0]
    assert zero.count == 5
    assert [e.item for e in zero.examples] == ["Лагман 5", "Лагман 4"]


def test_follows_margin_base(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(margin_base=MarginBase.WITH_SERVICE)
    ov = build_overview(build_group_summary(sample_report, cfg))
    assert ov.gross == Decimal(45397)
    assert ov.top_sellers[0].sales == Decimal(38500)


def test_serializes_to_json_for_api_or_llm(sample_report: SalesReport) -> None:
    payload = build_overview(build_group_summary(sample_report)).model_dump(mode="json")
    assert payload["top_sellers"][0]["name"] == "Самса"
    assert payload["issues"][0]["kind"] == "zero_cost"
    assert payload["date_from"] == "2026-11-01"


def test_without_total_row() -> None:
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, with_total=False))
    assert build_overview(build_group_summary(report)).reconciled is None
