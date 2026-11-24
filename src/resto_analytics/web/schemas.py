"""Схемы ответа API. Отдельно от доменных моделей, чтобы ядро не зависело от формата JSON."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

from resto_analytics.config import LastColumn, MarginBase, ServiceSource
from resto_analytics.export.excel import last_column_title, margin_base_label
from resto_analytics.reports.data_checks import DataIssue, Reconciliation
from resto_analytics.reports.group_summary import GroupRow, ItemRow, SalesSummary

# Внутри — Decimal, наружу — число с двумя знаками: так удобнее и JS, и Telegram-боту.
Money = Annotated[Decimal, PlainSerializer(lambda v: float(round(v, 2)), return_type=float)]
Ratio = Annotated[
    Decimal | None,
    PlainSerializer(lambda v: None if v is None else float(round(v, 4)), return_type=float | None),
]


class ItemOut(BaseModel):
    name: str
    source_group: str
    quantity: Money
    sales_net: Money
    service: Money
    sales_total: Money
    sales: Money
    """Сумма, от которой считаются доход и коэффициент (см. settings.margin_base)."""
    cost: Money
    gross: Money
    coefficient: Ratio

    @classmethod
    def from_domain(cls, item: ItemRow) -> ItemOut:
        return cls(
            name=item.name,
            source_group=item.source_group,
            quantity=item.quantity,
            sales_net=item.sales_net,
            service=item.service,
            sales_total=item.sales_total,
            sales=item.sales,
            cost=item.cost,
            gross=item.gross,
            coefficient=item.coefficient,
        )


class GroupOut(BaseModel):
    name: str
    sales_net: Money
    service: Money
    sales_total: Money
    sales: Money
    """Сумма, от которой считаются доход, коэффициент и доля (см. settings.margin_base)."""
    cost: Money
    gross: Money
    coefficient: Ratio
    share: Ratio
    last_value: Ratio
    sources: list[str]
    items: list[ItemOut]

    @classmethod
    def from_domain(cls, row: GroupRow, summary: SalesSummary) -> GroupOut:
        return cls(
            name=row.name,
            sales_net=row.sales_net,
            service=row.service,
            sales_total=row.sales_total,
            sales=row.sales,
            cost=row.cost,
            gross=row.gross,
            coefficient=row.coefficient,
            share=row.share,
            last_value=summary.last_value(row),
            sources=list(row.sources),
            items=[ItemOut.from_domain(i) for i in row.items],
        )


class IssueOut(BaseModel):
    kind: str
    severity: str
    title: str
    hint: str
    item: str
    group: str
    sales: Money
    cost: Money
    coefficient: Ratio
    row_number: int

    @classmethod
    def from_domain(cls, issue: DataIssue) -> IssueOut:
        return cls(
            kind=issue.kind.value,
            severity=issue.kind.severity,
            title=issue.kind.label,
            hint=issue.kind.hint,
            item=issue.item,
            group=issue.group,
            sales=issue.sales,
            cost=issue.cost,
            coefficient=issue.coefficient,
            row_number=issue.row_number,
        )


class ReconciliationOut(BaseModel):
    ok: bool
    file_revenue: Money
    lines_revenue: Money
    file_cost: Money
    lines_cost: Money

    @classmethod
    def from_domain(cls, rec: Reconciliation) -> ReconciliationOut:
        return cls(
            ok=rec.ok,
            file_revenue=rec.file_revenue,
            lines_revenue=rec.lines_revenue,
            file_cost=rec.file_cost,
            lines_cost=rec.lines_cost,
        )


class MetaOut(BaseModel):
    title: str
    period: str
    date_from: date | None
    date_to: date | None
    warehouses: list[str]
    sheet_name: str


class SettingsOut(BaseModel):
    margin_base: MarginBase
    service_source: ServiceSource
    last_column: LastColumn


class SummaryOut(BaseModel):
    meta: MetaOut
    settings: SettingsOut
    margin_base_label: str
    """«продаж без обслуживания» — для подписи «доход считается от …»."""
    last_column_title: str
    groups: list[GroupOut]
    total: GroupOut
    issues: list[IssueOut]
    reconciliation: ReconciliationOut | None
    line_count: int
    excluded_lines: int

    @classmethod
    def from_domain(cls, s: SalesSummary) -> SummaryOut:
        return cls(
            meta=MetaOut(
                title=s.meta.title,
                period=s.meta.period_label,
                date_from=s.meta.date_from,
                date_to=s.meta.date_to,
                warehouses=list(s.meta.warehouses),
                sheet_name=s.meta.sheet_name,
            ),
            settings=SettingsOut(
                margin_base=s.config.margin_base,
                service_source=s.config.service_source,
                last_column=s.config.last_column,
            ),
            margin_base_label=margin_base_label(s),
            last_column_title=last_column_title(s),
            groups=[GroupOut.from_domain(g, s) for g in s.groups],
            total=GroupOut.from_domain(s.total, s),
            issues=[IssueOut.from_domain(i) for i in s.issues],
            reconciliation=(
                ReconciliationOut.from_domain(s.reconciliation) if s.reconciliation else None
            ),
            line_count=s.line_count,
            excluded_lines=s.excluded_lines,
        )


class ErrorOut(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
    version: str
