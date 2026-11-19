from __future__ import annotations

import pytest

from resto_analytics.domain.models import SalesReport
from resto_analytics.parsing.iiko_sales import parse_sales_report
from tests.factories import SAMPLE_LINES, make_iiko_xlsx


@pytest.fixture(scope="session")
def sample_xlsx() -> bytes:
    return make_iiko_xlsx(SAMPLE_LINES)


@pytest.fixture
def sample_report(sample_xlsx: bytes) -> SalesReport:
    return parse_sales_report(sample_xlsx)
