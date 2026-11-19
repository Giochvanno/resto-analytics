import io

import pytest
from openpyxl import load_workbook

from resto_analytics.config import SummaryConfig
from resto_analytics.export.excel import ExcelOptions
from resto_analytics.parsing.errors import ParseError
from resto_analytics.service import summarize, summarize_to_excel


def test_summarize_uses_given_config(sample_xlsx: bytes) -> None:
    default = summarize(sample_xlsx)
    merged = summarize(sample_xlsx, SummaryConfig(group_overrides={}))
    assert "Лагман" in {g.name for g in default.groups}
    assert "Лагман" not in {g.name for g in merged.groups}


def test_summarize_to_excel(sample_xlsx: bytes) -> None:
    result = summarize_to_excel(sample_xlsx, options=ExcelOptions(formulas=True))
    assert result.filename == "Сводка_продаж_01.11.26-30.11.26.xlsx"
    assert result.summary.total.sales == 87371
    assert load_workbook(io.BytesIO(result.content))["Сводка"]["E5"].value == "=C5-D5"


def test_errors_bubble_up_as_parse_error() -> None:
    with pytest.raises(ParseError):
        summarize(b"not excel")
