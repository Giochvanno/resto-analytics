from decimal import Decimal
from pathlib import Path

import pytest

from resto_analytics.config import (
    ConfigError,
    GroupBy,
    LastColumn,
    MarginBase,
    SummaryConfig,
    load_config,
)

PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "summary.toml"


def test_defaults_match_fathers_example() -> None:
    cfg = SummaryConfig()
    assert cfg.group_by is GroupBy.CATEGORY
    assert cfg.group_overrides == {"Лагман": "Лагман"}
    assert cfg.row_order[:6] == ("Бар", "Плов", "Салаты", "Самса", "Лагман", "Шашлыки")
    assert cfg.last_column is LastColumn.SHARE
    assert cfg.margin_base is MarginBase.WITHOUT_SERVICE


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.toml") == SummaryConfig()
    assert load_config(None) == SummaryConfig()


def test_shipped_config_is_valid_and_equals_defaults() -> None:
    assert load_config(PROJECT_CONFIG) == SummaryConfig()


def test_load_custom_config(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_text(
        'group_by = "group"\n'
        'margin_base = "with_service"\n'
        'exclude_groups = ["Штрафы"]\n'
        "[group_overrides]\n"
        '"Десерты" = "Бар"\n'
        "[checks]\n"
        "low_margin_coefficient = 1.5\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.group_by is GroupBy.GROUP
    assert cfg.margin_base is MarginBase.WITH_SERVICE
    assert cfg.exclude_groups == ("Штрафы",)
    assert cfg.group_overrides == {"Десерты": "Бар"}
    assert cfg.checks.low_margin_coefficient == Decimal("1.5")


@pytest.mark.parametrize(
    "content",
    [
        "group_by = ",  # сломанный TOML
        'group_by = "dish"',  # неизвестное значение
        "unknown_key = 1",  # опечатка в имени настройки
        'sales_source = "revenue"',  # настройка из версии 0.1 — теперь margin_base
        '[group_overrides]\n"Лагман" = " "',  # пустое имя строки
    ],
)
def test_bad_config_raises_readable_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"bad\.toml"):
        load_config(path)
