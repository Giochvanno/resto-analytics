"""Настройки сводки: какие группы показывать, откуда брать суммы, пороги проверок.

Хранятся в TOML (config/summary.toml), чтобы отец мог поменять группы без программиста.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class SalesSource(StrEnum):
    REVENUE = "revenue"
    """«Выручка» — с надбавкой за обслуживание (реально полученные деньги)."""
    REVENUE_GROSS = "revenue_gross"
    """«Выручка без вычета скидок» — по ценам меню, без обслуживания."""


class ServiceSource(StrEnum):
    FILE = "file"
    """Брать надбавку из столбца «Сумма скидок» (там она со знаком минус)."""
    PERCENT = "percent"
    """Считать как service_percent % от суммы продаж."""
    NONE = "none"


class LastColumn(StrEnum):
    SHARE = "share"
    """Доля группы в общих продажах, % (так считает формула в примере отца)."""
    EFFICIENCY = "efficiency"
    """Продажи / себестоимость × 100 (так написано в заголовке примера)."""


class GroupBy(StrEnum):
    CATEGORY = "category"
    GROUP = "group"


class ChecksConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    low_margin_coefficient: Decimal = Field(default=Decimal("1.3"), gt=0)
    """Позиции с коэффициентом (продажи / себестоимость) ниже порога попадают в «низкая наценка»."""
    suspicious_cost_ratio: Decimal = Field(default=Decimal("0.02"), ge=0, lt=1)
    """Себестоимость единицы меньше этой доли от цены — скорее всего, ошибка в техкарте."""
    skip_groups: tuple[str, ...] = ("Штрафы",)
    """Группы, которые не проверяем (у штрафов себестоимость 0 — это нормально)."""


class SummaryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    group_by: GroupBy = GroupBy.CATEGORY
    group_overrides: dict[str, str] = Field(default_factory=lambda: {"Лагман": "Лагман"})
    """«Группа» из iiko → строка сводки. По умолчанию Лагман отдельно, как в примере."""
    exclude_groups: tuple[str, ...] = ()
    """«Группы» или «Категории», которые не попадают в сводку вообще."""
    row_order: tuple[str, ...] = ("Бар", "Плов", "Салаты", "Самса", "Лагман", "Шашлыки")
    """Порядок строк. Остальные группы идут следом по убыванию продаж."""
    sales_source: SalesSource = SalesSource.REVENUE
    service_source: ServiceSource = ServiceSource.FILE
    service_percent: Decimal = Field(default=Decimal(10), ge=0, le=100)
    last_column: LastColumn = LastColumn.SHARE
    checks: ChecksConfig = Field(default_factory=ChecksConfig)

    @field_validator("group_overrides")
    @classmethod
    def _no_empty_targets(cls, value: dict[str, str]) -> dict[str, str]:
        empty = [src for src, dst in value.items() if not dst.strip()]
        if empty:
            raise ValueError(f"пустое имя строки сводки для групп: {', '.join(empty)}")
        return value


class ConfigError(Exception):
    """Файл настроек не читается или содержит ошибки."""


def load_config(path: Path | None) -> SummaryConfig:
    """Читает TOML. Нет пути или файла — возвращает настройки по умолчанию."""
    if path is None or not path.exists():
        return SummaryConfig()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        return SummaryConfig.model_validate(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: ошибка синтаксиса TOML — {exc}") from exc
    except ValidationError as exc:
        raise ConfigError(f"{path}: неверные настройки — {exc}") from exc
