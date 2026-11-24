"""Сводка продаж по группам — то, что отец нарисовал во второй вкладке.

Это обычная сводная таблица: строки выгрузки раскладываются по группам
(по умолчанию по «Категории» iiko), внутри группы суммы складываются,
а из сумм считаются валовый доход, коэффициент и доля.

У каждой строки три суммы продаж: без обслуживания, само обслуживание и с ним
(sales_net + service = sales_total). Валовый доход, коэффициент и доля считаются
от одной из них — какой, решает настройка margin_base.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal

from resto_analytics.config import (
    GroupBy,
    LastColumn,
    MarginBase,
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
    sales_net: Decimal
    service: Decimal
    cost: Decimal
    margin_base: MarginBase

    @property
    def sales_total(self) -> Decimal:
        """Продажи с обслуживанием = без обслуживания + обслуживание."""
        return self.sales_net + self.service

    @property
    def sales(self) -> Decimal:
        """Сумма, от которой считаются доход, коэффициент и доля (см. margin_base)."""
        if self.margin_base is MarginBase.WITH_SERVICE:
            return self.sales_total
        return self.sales_net

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
    sales_net: Decimal
    service: Decimal
    cost: Decimal
    margin_base: MarginBase


@dataclass(frozen=True, slots=True)
class GroupRow(_Figures):
    name: str
    sales_net: Decimal
    service: Decimal
    cost: Decimal
    margin_base: MarginBase
    share: Decimal
    """Доля в общих продажах, % (от той же суммы, что и коэффициент)."""
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


def service_of(line: SaleLine, config: SummaryConfig) -> Decimal:
    """Обслуживание по строке выгрузки."""
    if config.service_source is ServiceSource.NONE:
        return ZERO
    if config.service_source is ServiceSource.PERCENT:
        return net_of(line) * config.service_percent / HUNDRED
    return line.service_surcharge


def net_of(line: SaleLine) -> Decimal:
    """Продажи без обслуживания: выручка минус надбавка (настоящие скидки уже вычтены iiko)."""
    return line.revenue - line.service_surcharge


@dataclass
class _Acc:
    sales_net: Decimal = ZERO
    service: Decimal = ZERO
    cost: Decimal = ZERO


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
        item = ItemRow(
            name=line.item,
            source_group=line.group,
            quantity=line.quantity,
            sales_net=net_of(line),
            service=service_of(line, config),
            cost=line.cost,
            margin_base=config.margin_base,
        )
        a = acc[target]
        a.sales_net += item.sales_net
        a.service += item.service
        a.cost += item.cost
        sources[target][line.group] = None
        items[target].append(item)
        checked.append(
            CheckedLine(
                item=line.item,
                source_group=line.group,
                source_category=line.category,
                target=target,
                quantity=line.quantity,
                sales=item.sales,
                revenue_gross=line.revenue_gross,
                cost=line.cost,
                row_number=line.row_number,
            )
        )

    base = config.margin_base
    total = GroupRow(
        name="Итого",
        sales_net=sum((a.sales_net for a in acc.values()), ZERO),
        service=sum((a.service for a in acc.values()), ZERO),
        cost=sum((a.cost for a in acc.values()), ZERO),
        margin_base=base,
        share=ZERO,
    )
    total = replace(total, share=HUNDRED if total.sales else ZERO)

    rows = []
    for name, a in acc.items():
        row = GroupRow(
            name=name,
            sales_net=a.sales_net,
            service=a.service,
            cost=a.cost,
            margin_base=base,
            share=ZERO,
            sources=tuple(sources[name]),
            items=tuple(sorted(items[name], key=lambda i: (-i.sales, i.name))),
        )
        rows.append(replace(row, share=percent(row.sales, total.sales) or ZERO))
    order = {name.casefold(): idx for idx, name in enumerate(config.row_order)}
    rows.sort(key=lambda r: (order.get(r.name.casefold(), len(order)), -r.sales, r.name))

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
