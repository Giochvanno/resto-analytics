from decimal import Decimal

from resto_analytics.config import ChecksConfig, SummaryConfig
from resto_analytics.domain.models import FileTotals, SalesReport
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.data_checks import IssueKind, reconcile
from resto_analytics.reports.group_summary import build_group_summary
from tests.factories import SAMPLE_LINES, Line, make_iiko_xlsx


def kinds(report: SalesReport, config: SummaryConfig | None = None) -> dict[str, IssueKind]:
    return {i.item: i.kind for i in build_group_summary(report, config).issues}


def test_issues_found_in_sample(sample_report: SalesReport) -> None:
    assert kinds(sample_report) == {
        "Гуйру Лагман": IssueKind.ZERO_COST,
        "Домашние пельмени (суп)": IssueKind.SUSPICIOUS_COST,  # 3 тг при цене 1600
        "Куырдак": IssueKind.LOW_MARGIN,  # 9200 / 8200 = 1,12 (без обслуживания)
    }


def test_fines_are_not_checked(sample_report: SalesReport) -> None:
    assert "Штраф 1000 тг" not in kinds(sample_report)


def test_issue_details(sample_report: SalesReport) -> None:
    issues = build_group_summary(sample_report).issues
    # сначала критичные, потом предупреждения
    assert [i.kind for i in issues] == [
        IssueKind.ZERO_COST,
        IssueKind.SUSPICIOUS_COST,
        IssueKind.LOW_MARGIN,
    ]
    kuyrdak = issues[-1]
    assert kuyrdak.group == "Бар"
    assert round(kuyrdak.coefficient or 0, 2) == Decimal("1.12")
    assert kuyrdak.row_number == 8
    assert issues[0].coefficient is None
    assert IssueKind.ZERO_COST.severity == "critical"
    assert IssueKind.LOW_MARGIN.severity == "warning"
    assert IssueKind.LOW_MARGIN.label
    assert IssueKind.LOW_MARGIN.hint


def test_thresholds_are_configurable(sample_report: SalesReport) -> None:
    strict = SummaryConfig(checks=ChecksConfig(low_margin_coefficient=Decimal(2)))
    low = [
        item for item, kind in kinds(sample_report, strict).items() if kind is IssueKind.LOW_MARGIN
    ]
    assert set(low) == {"Куырдак", "Пахлава", "Ханский плов", "Самса с мясом"}


def test_returns_and_zero_sales_are_ignored() -> None:
    lines = [Line("Плов", "Плов", "Возврат", 0, 0, 0), Line("Плов", "Плов", "Плов", 1, 100, 50)]
    assert build_group_summary(parse_sales_report(make_iiko_xlsx(lines))).issues == ()


def test_reconciliation_ok(sample_report: SalesReport) -> None:
    rec = build_group_summary(sample_report).reconciliation
    assert rec is not None
    assert rec.ok
    assert rec.lines_revenue == rec.file_revenue


def test_reconciliation_detects_lost_rows() -> None:
    data = make_iiko_xlsx(SAMPLE_LINES, total_override={"Выручка, тг.": 999_999.0})
    rec = build_group_summary(parse_sales_report(data)).reconciliation
    assert rec is not None
    assert not rec.ok


def test_reconciliation_tolerates_rounding(sample_report: SalesReport) -> None:
    totals = sample_report.file_totals
    assert totals is not None
    shifted = SalesReport(
        meta=sample_report.meta,
        lines=sample_report.lines,
        file_totals=FileTotals(revenue=totals.revenue + Decimal("0.4"), cost=totals.cost),
    )
    rec = reconcile(shifted)
    assert rec is not None
    assert rec.ok


def test_no_total_row_means_no_reconciliation() -> None:
    report = parse_sales_report(make_iiko_xlsx(SAMPLE_LINES, with_total=False))
    assert reconcile(report) is None
