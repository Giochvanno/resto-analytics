"""Обзор месяца: главные цифры и выводы, без форматирования.

Модели — pydantic: их легко отдать в JSON (API, а потом и LLM как контекст
или результат инструмента), а форматирование под Telegram/веб живёт отдельно.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from resto_analytics.config import MarginBase
from resto_analytics.reports.data_checks import IssueKind
from resto_analytics.reports.group_summary import GroupRow, SalesSummary

TOP_SELLERS = 3
MARGIN_EXAMPLES = 2
ISSUE_EXAMPLES = 2
MIN_SHARE_FOR_MARGIN = Decimal(2)
"""Группы меньше 2% продаж не попадают в «выгоднее/слабее всего»: на них выводы шумные."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class GroupFact(_Frozen):
    name: str
    sales: Decimal
    """Сумма, от которой считается доход (см. MonthOverview.margin_base)."""
    coefficient: Decimal | None
    share: Decimal


class IssueExample(_Frozen):
    item: str
    sales: Decimal
    coefficient: Decimal | None


class IssueFact(_Frozen):
    kind: IssueKind
    count: int
    examples: tuple[IssueExample, ...]
    """Самые крупные по продажам позиции этого вида."""


class MonthOverview(_Frozen):
    title: str
    date_from: date | None
    date_to: date | None
    reconciled: bool | None
    """Совпала ли сумма строк с «Итого» файла. None — в файле нет итога."""
    margin_base: MarginBase
    sales_total: Decimal
    sales_net: Decimal
    service: Decimal
    cost: Decimal
    gross: Decimal
    coefficient: Decimal | None
    top_sellers: tuple[GroupFact, ...]
    best_margin: tuple[GroupFact, ...]
    worst_margin: tuple[GroupFact, ...]
    issues: tuple[IssueFact, ...]

    @property
    def issue_count(self) -> int:
        return sum(i.count for i in self.issues)


def _fact(row: GroupRow) -> GroupFact:
    return GroupFact(name=row.name, sales=row.sales, coefficient=row.coefficient, share=row.share)


def build_overview(summary: SalesSummary) -> MonthOverview:
    groups = summary.groups
    by_sales = sorted(groups, key=lambda g: (-g.sales, g.name))
    comparable = [
        g for g in groups if g.coefficient is not None and g.share >= MIN_SHARE_FOR_MARGIN
    ]
    by_margin = sorted(comparable, key=lambda g: (-(g.coefficient or 0), g.name))
    best = by_margin[:MARGIN_EXAMPLES]
    worst = [g for g in reversed(by_margin) if g not in best][:MARGIN_EXAMPLES]

    issues = []
    for kind in IssueKind:
        found = [i for i in summary.issues if i.kind is kind]
        if found:
            examples = tuple(
                IssueExample(item=i.item, sales=i.sales, coefficient=i.coefficient)
                for i in found[:ISSUE_EXAMPLES]
            )
            issues.append(IssueFact(kind=kind, count=len(found), examples=examples))

    total = summary.total
    rec = summary.reconciliation
    return MonthOverview(
        title=summary.meta.title,
        date_from=summary.meta.date_from,
        date_to=summary.meta.date_to,
        reconciled=None if rec is None else rec.ok,
        margin_base=summary.config.margin_base,
        sales_total=total.sales_total,
        sales_net=total.sales_net,
        service=total.service,
        cost=total.cost,
        gross=total.gross,
        coefficient=total.coefficient,
        top_sellers=tuple(_fact(g) for g in by_sales[:TOP_SELLERS]),
        best_margin=tuple(_fact(g) for g in best),
        worst_margin=tuple(_fact(g) for g in worst),
        issues=tuple(issues),
    )
