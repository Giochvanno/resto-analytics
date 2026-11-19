"""Сводка продаж по группам — то, что отец нарисовал во второй вкладке.

Это обычная сводная таблица: строки выгрузки раскладываются по группам
(по умолчанию по «Категории» iiko), внутри группы суммы складываются,
а из сумм считаются валовый доход, коэффициент и доля.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from resto_analytics.config import (
    GroupBy,
    LastColumn,
    SalesSource,
    ServiceSource,
    SummaryConfig,
)
from resto_analytics.domain.models import ReportMeta, SaleLine, SalesReport
from resto_analytics.domain.money import HUNDRED, ZERO, percent, ratio
from resto_analytics.reports.data_checks import (
    CheckedLine,
    DataIssue,
    Reconciliation,
    find_issues,
    reconcile,
)


class _Figures:
    """Общие производные показатели для строки сводки и позиции."""

    __slots__ = ()
    sales: Decimal
    cost: Decimal

    @property
    def gross(self) -> Decimal:
        """Валовый доход = продажи − себестоимость."""
        return self.sales - self.cost

    @property
    def coefficient(self) -> Decimal | None:
        """Средний коэффициент = продажи / себестоимость. None, если себестоимость 0."""
        return ratio(self.sales, self.cost)

    @property
    def efficiency(self) -> Decimal | None:
        """Продажи / себестоимость × 100."""
        return percent(self.sales, self.cost)


@dataclass(frozen=True, slots=True)
class ItemRow(_Figures):
    name: str
    source_group: str
    quantity: Decimal
    sales: Decimal
    cost: Decimal
    service: Decimal


@dataclass(frozen=True, slots=True)
class GroupRow(_Figures):
    name: str
    sales: Decimal
    cost: Decimal
    service: Decimal
    share: Decimal
    """Доля в общих продажах, %."""
    sources: tuple[str, ...] = ()
    """Из каких «Групп» iiko собрана строка — чтобы было видно, откуда цифры."""
    items: tuple[ItemRow, ...] = ()


@dataclass(frozen=True, slots=True)
class SalesSummary:
    meta: ReportMeta
    config: SummaryConfig
    groups: tuple[GroupRow, ...]
    total: GroupRow
    issues: tuple[DataIssue, ...]
    reconciliation: Reconciliation | None
    line_count: int
    excluded_lines: int

    def last_value(self, row: GroupRow) -> Decimal | None:
        if self.config.last_column is LastColumn.EFFICIENCY:
            return row.efficiency
        return row.share


def target_for(line: SaleLine, config: SummaryConfig) -> str | None:
    """В какую строку сводки попадает позиция. None — не учитывать."""
    excluded = {name.casefold() for name in config.exclude_groups}
    if line.group.casefold() in excluded or line.category.casefold() in excluded:
        return None
    override = config.group_overrides.get(line.group)
    if override:
        return override
    return line.category if config.group_by is GroupBy.CATEGORY else line.group


def sales_of(line: SaleLine, config: SummaryConfig) -> Decimal:
    if config.sales_source is SalesSource.REVENUE_GROSS:
        return line.revenue_gross
    return line.revenue


def service_of(line: SaleLine, sales: Decimal, config: SummaryConfig) -> Decimal:
    if config.service_source is ServiceSource.NONE:
        return ZERO
    if config.service_source is ServiceSource.PERCENT:
        return sales * config.service_percent / HUNDRED
    return line.service_surcharge


@dataclass
class _Acc:
    sales: Decimal = ZERO
    cost: Decimal = ZERO
    service: Decimal = ZERO


def build_group_summary(report: SalesReport, config: SummaryConfig | None = None) -> SalesSummary:
    config = config or SummaryConfig()
    acc: dict[str, _Acc] = defaultdict(_Acc)
    items: dict[str, list[ItemRow]] = defaultdict(list)
    sources: dict[str, dict[str, None]] = defaultdict(dict)  # dict как упорядоченное множество
    checked: list[CheckedLine] = []
    excluded = 0

    for line in report.lines:
        target = target_for(line, config)
        if target is None:
            excluded += 1
            continue
        sales = sales_of(line, config)
        service = service_of(line, sales, config)
        a = acc[target]
        a.sales += sales
        a.cost += line.cost
        a.service += service
        sources[target][line.group] = None
        items[target].append(
            ItemRow(
                name=line.item,
                source_group=line.group,
                quantity=line.quantity,
                sales=sales,
                cost=line.cost,
                service=service,
            )
        )
        checked.append(
            CheckedLine(
                item=line.item,
                source_group=line.group,
                source_category=line.category,
                target=target,
                quantity=line.quantity,
                sales=sales,
                revenue_gross=line.revenue_gross,
                cost=line.cost,
                row_number=line.row_number,
            )
        )

    total_sales = sum((a.sales for a in acc.values()), ZERO)
    total_cost = sum((a.cost for a in acc.values()), ZERO)
    total_service = sum((a.service for a in acc.values()), ZERO)

    rows = [
        GroupRow(
            name=name,
            sales=a.sales,
            cost=a.cost,
            service=a.service,
            share=percent(a.sales, total_sales) or ZERO,
            sources=tuple(sources[name]),
            items=tuple(sorted(items[name], key=lambda i: (-i.sales, i.name))),
        )
        for name, a in acc.items()
    ]
    order = {name.casefold(): idx for idx, name in enumerate(config.row_order)}
    rows.sort(key=lambda r: (order.get(r.name.casefold(), len(order)), -r.sales, r.name))

    total = GroupRow(
        name="Итого",
        sales=total_sales,
        cost=total_cost,
        service=total_service,
        share=HUNDRED if total_sales else ZERO,
    )
    return SalesSummary(
        meta=report.meta,
        config=config,
        groups=tuple(rows),
        total=total,
        issues=find_issues(checked, config.checks),
        reconciliation=reconcile(report),
        line_count=len(report.lines),
        excluded_lines=excluded,
    )
