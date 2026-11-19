"""Проверки данных: то, на что стоит обратить внимание до того, как верить цифрам."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from resto_analytics.config import ChecksConfig
from resto_analytics.domain.models import SalesReport
from resto_analytics.domain.money import ZERO, ratio

RECONCILIATION_TOLERANCE = Decimal(1)  # тенге


class IssueKind(StrEnum):
    ZERO_COST = "zero_cost"
    SUSPICIOUS_COST = "suspicious_cost"
    LOW_MARGIN = "low_margin"

    @property
    def label(self) -> str:
        return _TITLES[self]

    @property
    def hint(self) -> str:
        return _HINTS[self]

    @property
    def severity(self) -> str:
        return "critical" if self is IssueKind.ZERO_COST else "warning"


_TITLES = {
    IssueKind.ZERO_COST: "Себестоимость 0",
    IssueKind.SUSPICIOUS_COST: "Подозрительно низкая себестоимость",
    IssueKind.LOW_MARGIN: "Почти нет наценки",
}
_HINTS = {
    IssueKind.ZERO_COST: "Коэффициент не посчитать. Проверьте техкарты в iiko.",
    IssueKind.SUSPICIOUS_COST: (
        "Себестоимость в десятки раз меньше цены. Скорее всего, ошибка в техкарте."
    ),
    IssueKind.LOW_MARGIN: "Продажи едва покрывают себестоимость.",
}


@dataclass(frozen=True, slots=True)
class DataIssue:
    kind: IssueKind
    item: str
    group: str
    sales: Decimal
    cost: Decimal
    row_number: int

    @property
    def coefficient(self) -> Decimal | None:
        return ratio(self.sales, self.cost)


@dataclass(frozen=True, slots=True)
class CheckedLine:
    """Строка, уже прошедшая через настройки сводки: куда попала и с какой суммой."""

    item: str
    source_group: str
    source_category: str
    target: str
    quantity: Decimal
    sales: Decimal
    revenue_gross: Decimal
    cost: Decimal
    row_number: int


def find_issues(lines: Iterable[CheckedLine], checks: ChecksConfig) -> tuple[DataIssue, ...]:
    skip = {s.casefold() for s in checks.skip_groups}
    issues: list[DataIssue] = []
    for line in lines:
        if line.sales <= ZERO:
            continue
        if {line.source_group.casefold(), line.source_category.casefold()} & skip:
            continue
        kind = _classify(line, checks)
        if kind is not None:
            issues.append(
                DataIssue(
                    kind=kind,
                    item=line.item,
                    group=line.target,
                    sales=line.sales,
                    cost=line.cost,
                    row_number=line.row_number,
                )
            )
    order = list(IssueKind)
    issues.sort(key=lambda i: (order.index(i.kind), -i.sales, i.item))
    return tuple(issues)


def _classify(line: CheckedLine, checks: ChecksConfig) -> IssueKind | None:
    if line.cost == ZERO:
        return IssueKind.ZERO_COST
    if line.quantity > ZERO and line.revenue_gross > ZERO:
        unit_cost = line.cost / line.quantity
        unit_price = line.revenue_gross / line.quantity
        if unit_cost < unit_price * checks.suspicious_cost_ratio:
            return IssueKind.SUSPICIOUS_COST
    coefficient = ratio(line.sales, line.cost)
    if coefficient is not None and coefficient < checks.low_margin_coefficient:
        return IssueKind.LOW_MARGIN
    return None


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Сверка: сумма всех строк файла против строки «Итого» в нём же."""

    file_revenue: Decimal
    file_cost: Decimal
    lines_revenue: Decimal
    lines_cost: Decimal

    @property
    def ok(self) -> bool:
        return (
            abs(self.file_revenue - self.lines_revenue) <= RECONCILIATION_TOLERANCE
            and abs(self.file_cost - self.lines_cost) <= RECONCILIATION_TOLERANCE
        )


def reconcile(report: SalesReport) -> Reconciliation | None:
    if report.file_totals is None:
        return None
    return Reconciliation(
        file_revenue=report.file_totals.revenue,
        file_cost=report.file_totals.cost,
        lines_revenue=sum((line.revenue for line in report.lines), ZERO),
        lines_cost=sum((line.cost for line in report.lines), ZERO),
    )
