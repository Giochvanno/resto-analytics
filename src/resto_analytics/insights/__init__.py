"""Выводы из сводки: что стоит сказать владельцу о месяце.

Сейчас выводы строятся правилами. Они же — структурированные факты, которые
потом получит ИИ: он сможет пересказать их по-человечески, а проверка сверит
каждое число в его тексте с этими фактами.
"""

from resto_analytics.insights.overview import (
    GroupFact,
    IssueFact,
    MonthOverview,
    build_overview,
)

__all__ = ["GroupFact", "IssueFact", "MonthOverview", "build_overview"]
