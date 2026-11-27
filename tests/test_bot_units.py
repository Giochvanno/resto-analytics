from datetime import date
from decimal import Decimal

import pytest
from aiogram.enums import ParseMode
from pydantic import SecretStr

from resto_analytics.bot import format as fmt
from resto_analytics.bot.app import BotConfigError, check_settings, create_bot
from resto_analytics.bot.store import InMemoryReportStore
from resto_analytics.bot.views import (
    MAX_ISSUES_PER_KIND,
    MAX_ITEMS_IN_GROUP,
    group_view,
    groups_view,
    issues_view,
    overview_view,
)
from resto_analytics.config import MarginBase, SummaryConfig
from resto_analytics.domain.models import SalesReport
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import SalesSummary, build_group_summary
from resto_analytics.settings import AppSettings
from tests.factories import SAMPLE_LINES, Line, make_iiko_xlsx


def summary_of(lines: list[Line], **kw: object) -> SalesSummary:
    return build_group_summary(parse_sales_report(make_iiko_xlsx(lines, **kw)))  # type: ignore[arg-type]


# ---------- числа ----------


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (Decimal("12345678.90"), 1, "12,3 млн"),
        (Decimal("2345678"), 2, "2,35 млн"),
        (Decimal("999999.6"), 1, "1,0 млн"),  # округление не даёт «1000 тыс»
        (Decimal("456789"), 1, "457 тыс"),
        (Decimal("2000"), 1, "2 тыс"),
        (Decimal("999.6"), 1, "1 тыс"),
        (Decimal("950"), 1, "950"),
        (Decimal("0"), 1, "0"),
        (Decimal("-1500"), 1, "−2 тыс"),
        (Decimal("1234567890"), 1, "1 234,6 млн"),
    ],
)
def test_money(value: Decimal, digits: int, expected: str) -> None:
    assert fmt.money(value, digits) == expected


def test_coef_and_pct() -> None:
    assert fmt.coef(Decimal("1.915")) == "1,92"  # половинки — вверх, как в бухгалтерии
    assert fmt.coef(None) == "—"
    assert fmt.coef_cell(Decimal("533.33")) == ">100"
    assert fmt.coef_cell(Decimal("99.99")) == "99,99"
    assert fmt.coef_cell(None) == "—"
    assert fmt.pct(Decimal("27.94")) == "27,9%"
    assert fmt.pct(None) == "—"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 11, 1), date(2026, 11, 30), "Ноябрь 2026"),
        (date(2026, 12, 1), date(2026, 12, 31), "Декабрь 2026"),
        (date(2028, 2, 1), date(2028, 2, 29), "Февраль 2028"),  # високосный
        (date(2026, 11, 1), date(2026, 11, 15), "01.11.2026 – 15.11.2026"),
        (date(2026, 10, 1), date(2026, 11, 30), "01.10.2026 – 30.11.2026"),
        (None, None, "Отчет"),
    ],
)
def test_period_title(start: date | None, end: date | None, expected: str) -> None:
    assert fmt.period_title(start, end, "Отчет") == expected


def test_clip() -> None:
    assert fmt.clip("Плов", 9) == "Плов"
    assert fmt.clip("Горячие напитки", 9) == "Горячие …"


# ---------- экраны ----------


def test_overview_without_issues_and_total() -> None:
    view = overview_view(
        summary_of([Line("Плов", "Плов", "Плов", 2, 1000, 400)], with_total=False), 1
    )
    assert "Проблем в учёте не найдено" in view.text
    assert "итогом iiko" not in view.text
    assert view.keyboard is not None
    buttons = [b.text for row in view.keyboard.inline_keyboard for b in row]
    assert not any("Проблемы" in b for b in buttons)


def test_overview_warns_when_totals_do_not_match() -> None:
    lines = [Line("Плов", "Плов", "Плов", 2, 1000, 400)]
    view = overview_view(summary_of(lines, total_override={"Выручка, тг.": 1.0}), 1)
    assert "⚠️ не сходится с итогом iiko" in view.text


def test_overview_with_service_offers_to_switch_back(sample_report: SalesReport) -> None:
    cfg = SummaryConfig(margin_base=MarginBase.WITH_SERVICE)
    view = overview_view(build_group_summary(sample_report, cfg), 1)
    assert view.keyboard is not None
    assert "🔁 Считать без обслуживания" in [
        b.text for r in view.keyboard.inline_keyboard for b in r
    ]


def test_names_are_html_escaped() -> None:
    lines = [Line("<b>Акции</b>", "Бар & кухня", "Чай <с> молоком", 2, 1000, 0)]
    summary = summary_of(lines)
    for view in (
        overview_view(summary, 1),
        groups_view(summary, 1),
        group_view(summary, 1, 0),
        issues_view(summary, 1),
    ):
        assert "<с>" not in view.text
        assert "<b>Акции</b>" not in view.text
    assert "Бар &amp; кухня" in overview_view(summary, 1).text


def test_group_view_out_of_range_falls_back_to_all_groups(sample_report: SalesReport) -> None:
    summary = build_group_summary(sample_report)
    assert group_view(summary, 1, 99).text == groups_view(summary, 1).text


def test_long_group_is_truncated() -> None:
    lines = [Line("Бар", "Бар", f"Напиток {n:02d}", n, 100, 50) for n in range(1, 31)]
    text = group_view(summary_of(lines), 1, 0).text
    assert text.count("Напиток") == MAX_ITEMS_IN_GROUP
    assert f"и ещё {30 - MAX_ITEMS_IN_GROUP} — в Excel" in text


def test_long_issue_list_is_truncated() -> None:
    lines = [Line("Лагман", "Лагман", f"Лагман {n:02d}", n, 1000, 0) for n in range(1, 13)]
    text = issues_view(summary_of(lines), 1).text
    assert text.count("• ") == MAX_ISSUES_PER_KIND
    assert f"и ещё {12 - MAX_ISSUES_PER_KIND} — в Excel" in text


def test_issues_view_without_issues() -> None:
    text = issues_view(summary_of([Line("Плов", "Плов", "Плов", 2, 1000, 400)]), 1).text
    assert "Проблем в учёте не найдено" in text


def test_messages_fit_telegram_limit() -> None:
    lines = [
        Line(f"Группа {g}", f"Категория {g}", f"Блюдо с длинным названием {g}-{n}", n, 900, 0)
        for g in range(12)
        for n in range(1, 40)
    ]
    summary = summary_of(lines)
    for view in (overview_view(summary, 1), groups_view(summary, 1), issues_view(summary, 1)):
        assert len(view.text) < 4096


def test_sample_overview_lines(sample_report: SalesReport) -> None:
    text = overview_view(build_group_summary(sample_report), 7).text
    assert "Самса 35 тыс · Бар 21 тыс · Плов 17 тыс" in text  # 20 500 → «21 тыс»
    assert "Выгоднее всего: Супы >100 · Плов 2,24" in text
    assert "Слабее всего: Самса 1,45 · Бар 2,03" in text
    assert "• нет себестоимости: Гуйру Лагман" in text
    assert "• почти без наценки: Куырдак 1,12" in text
    assert len(SAMPLE_LINES) == 10


# ---------- хранилище ----------


def test_store_evicts_oldest_chat(sample_report: SalesReport) -> None:
    store = InMemoryReportStore(max_chats=2)
    store.save(1, sample_report, "a.xlsx", MarginBase.WITHOUT_SERVICE)
    store.save(2, sample_report, "b.xlsx", MarginBase.WITHOUT_SERVICE)
    store.get(1)  # чат 1 снова активен
    store.save(3, sample_report, "c.xlsx", MarginBase.WITHOUT_SERVICE)
    assert len(store) == 2
    assert store.get(2) is None
    assert store.get(1) is not None


def test_store_ids_and_update(sample_report: SalesReport) -> None:
    store = InMemoryReportStore()
    first = store.save(1, sample_report, "a.xlsx", MarginBase.WITHOUT_SERVICE)
    second = store.save(1, sample_report, "b.xlsx", MarginBase.WITHOUT_SERVICE)
    assert second.report_id == first.report_id + 1
    store.update(5, first)  # чата 5 нет — ничего не создаём
    assert store.get(5) is None


def test_store_rejects_zero_size() -> None:
    with pytest.raises(ValueError, match="max_chats"):
        InMemoryReportStore(max_chats=0)


# ---------- запуск ----------


def test_check_settings() -> None:
    with pytest.raises(BotConfigError, match="RESTO_BOT_TOKEN"):
        check_settings(AppSettings(bot_token=None, bot_allowed_users="1"))
    with pytest.raises(BotConfigError, match="RESTO_BOT_TOKEN"):
        check_settings(AppSettings(bot_token=SecretStr(""), bot_allowed_users="1"))
    with pytest.raises(BotConfigError, match="RESTO_BOT_ALLOWED_USERS"):
        check_settings(AppSettings(bot_token=SecretStr("42:TEST"), bot_allowed_users=""))
    ok = AppSettings(bot_token=SecretStr("42:TEST"), bot_allowed_users="1")
    assert check_settings(ok) == "42:TEST"


def test_create_bot_uses_html() -> None:
    bot = create_bot("42:TEST")
    assert bot.default.parse_mode == ParseMode.HTML
