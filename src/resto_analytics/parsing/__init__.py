"""Чтение выгрузок iiko."""

from resto_analytics.parsing.errors import ParseError
from resto_analytics.parsing.iiko_sales import parse_sales_report

__all__ = ["ParseError", "parse_sales_report"]
