"""Точка входа в ядро для любых интерфейсов: веб, CLI, а потом Telegram-бот или iiko API.

Интерфейсы не знают про openpyxl и правила расчёта — они только передают байты файла
и настройки и получают готовую сводку или .xlsx.
"""

from __future__ import annotations

from dataclasses import dataclass

from resto_analytics.config import SummaryConfig
from resto_analytics.export.excel import ExcelOptions, summary_filename, write_summary_xlsx
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import SalesSummary, build_group_summary


def summarize(data: bytes, config: SummaryConfig | None = None) -> SalesSummary:
    """Байты .xlsx из iiko → сводка по группам. Бросает ParseError с понятным текстом."""
    report = parse_sales_report(data)
    return build_group_summary(report, config)


@dataclass(frozen=True, slots=True)
class ExcelResult:
    summary: SalesSummary
    filename: str
    content: bytes


def summarize_to_excel(
    data: bytes,
    config: SummaryConfig | None = None,
    options: ExcelOptions | None = None,
) -> ExcelResult:
    summary = summarize(data, config)
    return ExcelResult(
        summary=summary,
        filename=summary_filename(summary),
        content=write_summary_xlsx(summary, options),
    )
