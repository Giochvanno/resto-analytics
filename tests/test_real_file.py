"""Проверка на настоящей выгрузке iiko.

Реальный файл в репозиторий не кладём (там деньги ресторана). Запуск локально:

    RESTO_REAL_FILE=data/Отчет_ноябрь.xlsx pytest -m real_data
"""

import os
from pathlib import Path

import pytest

from resto_analytics.export.excel import write_summary_xlsx
from resto_analytics.service import summarize

REAL_FILE = os.environ.get("RESTO_REAL_FILE")

pytestmark = [
    pytest.mark.real_data,
    pytest.mark.skipif(not REAL_FILE, reason="задайте RESTO_REAL_FILE=путь/к/выгрузке.xlsx"),
]


@pytest.fixture(scope="module")
def real_bytes() -> bytes:
    assert REAL_FILE is not None
    return Path(REAL_FILE).read_bytes()


def test_real_export_reconciles_with_its_own_total(real_bytes: bytes) -> None:
    summary = summarize(real_bytes)
    assert summary.line_count > 0
    assert summary.reconciliation is not None, "в выгрузке нет строки «Итого»"
    assert summary.reconciliation.ok
    assert summary.total.sales_total == summary.reconciliation.file_revenue


def test_real_export_builds_excel(real_bytes: bytes) -> None:
    assert write_summary_xlsx(summarize(real_bytes))[:2] == b"PK"
