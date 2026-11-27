"""Экраны бота: текст в HTML-разметке Telegram + кнопки.

Чистые функции от сводки — без сети и без aiogram Bot, поэтому легко тестируются.
Главный экран отвечает на вопрос «как прошёл месяц?» за 10 секунд;
детали — по кнопкам, точные цифры — в Excel.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html import escape

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from resto_analytics.bot import format as fmt
from resto_analytics.config import MarginBase
from resto_analytics.insights import GroupFact, IssueFact, MonthOverview, build_overview
from resto_analytics.insights.overview import IssueExample
from resto_analytics.reports.data_checks import IssueKind
from resto_analytics.reports.group_summary import SalesSummary

MAX_ITEMS_IN_GROUP = 20
MAX_ISSUES_PER_KIND = 8
GROUP_BUTTONS_PER_ROW = 3


class Action(StrEnum):
    OVERVIEW = "o"
    GROUPS = "g"
    GROUP = "d"
    ISSUES = "i"
    EXCEL = "x"
    TOGGLE = "t"


class Nav(CallbackData, prefix="nav"):
    """Данные кнопки. report_id — чтобы кнопки старого отчёта не показывали новый."""

    action: Action
    report_id: int
    index: int = -1


@dataclass(frozen=True, slots=True)
class View:
    text: str
    keyboard: InlineKeyboardMarkup | None = None


SHORT_ISSUE = {
    IssueKind.ZERO_COST: "нет себестоимости",
    IssueKind.SUSPICIOUS_COST: "подозрительно низкая себестоимость",
    IssueKind.LOW_MARGIN: "почти без наценки",
}

START_TEXT = (
    "Здравствуйте! Я считаю сводку продаж по выгрузке из iiko.\n\n"
    "Пришлите файл «Отчет о продажах» (.xlsx) — в ответ будет обзор месяца: "
    "выручка, доход, что продаётся лучше всего и что проверить в учёте. "
    "Подробности и Excel — по кнопкам под обзором."
)
HELP_TEXT = (
    "<b>Как пользоваться</b>\n"
    "1. В iiko выгрузите «Отчет о продажах» в Excel.\n"
    "2. Перешлите файл сюда.\n"
    "3. Под обзором есть кнопки: все группы, проблемы в учёте, Excel "
    "и пересчёт с обслуживанием или без.\n\n"
    "Доход и коэффициент по умолчанию считаются от продаж без обслуживания: "
    "10% — плата за работу зала, а не за блюдо."
)


# ---------- главный экран ----------


def overview_view(summary: SalesSummary, report_id: int) -> View:
    ov = build_overview(summary)
    title = fmt.period_title(ov.date_from, ov.date_to, ov.title)
    lines = [f"<b>📊 {escape(title)}</b>"]
    if ov.reconciled is True:
        lines.append("✓ сходится с итогом iiko")
    elif ov.reconciled is False:
        lines.append("⚠️ не сходится с итогом iiko — проверьте выгрузку")

    lines += [
        "",
        f"Выручка <b>{fmt.money(ov.sales_total)}</b> тг",
        f"Валовый доход <b>{fmt.money(ov.gross)}</b> · "
        f"коэффициент <b>{fmt.coef(ov.coefficient)}</b>",
        f"<i>Доход и коэффициент — от {_base_label(ov.margin_base)}.</i>",
    ]
    if ov.top_sellers:
        sellers = " · ".join(f"{escape(g.name)} {fmt.money(g.sales)}" for g in ov.top_sellers)
        lines += ["", "<b>Больше всего продаж</b>", sellers]
    if ov.best_margin:
        lines += ["", f"Выгоднее всего: {_margins(ov.best_margin)}"]
    if ov.worst_margin:
        lines.append(f"Слабее всего: {_margins(ov.worst_margin)}")

    lines.append("")
    if ov.issues:
        lines.append("<b>⚠️ Проверьте в iiko</b>")
        lines += [f"• {_issue_line(issue)}" for issue in ov.issues]
    else:
        lines.append("✓ Проблем в учёте не найдено")
    return View("\n".join(lines), _overview_keyboard(ov, report_id))


def _base_label(base: MarginBase) -> str:
    if base is MarginBase.WITH_SERVICE:
        return "продаж с обслуживанием"
    return "продаж без обслуживания"


def _base_short(base: MarginBase) -> str:
    return "с обслуживанием" if base is MarginBase.WITH_SERVICE else "без обслуживания"


def _margins(groups: tuple[GroupFact, ...]) -> str:
    return " · ".join(f"{escape(g.name)} {fmt.coef_cell(g.coefficient)}" for g in groups)


def _issue_line(issue: IssueFact) -> str:
    def example(e: IssueExample) -> str:
        if issue.kind is IssueKind.LOW_MARGIN and e.coefficient is not None:
            return f"{escape(e.item)} {fmt.coef(e.coefficient)}"
        return escape(e.item)

    names = ", ".join(example(e) for e in issue.examples)
    rest = issue.count - len(issue.examples)
    more = f" и ещё {rest}" if rest > 0 else ""
    return f"{SHORT_ISSUE[issue.kind]}: {names}{more}"


def _overview_keyboard(ov: MonthOverview, report_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Все группы", callback_data=Nav(action=Action.GROUPS, report_id=report_id))
    if ov.issues:
        kb.button(
            text=f"⚠️ Проблемы ({ov.issue_count})",
            callback_data=Nav(action=Action.ISSUES, report_id=report_id),
        )
    kb.button(text="📎 Excel", callback_data=Nav(action=Action.EXCEL, report_id=report_id))
    toggle = (
        "Считать без обслуживания"
        if ov.margin_base is MarginBase.WITH_SERVICE
        else "Считать с обслуживанием"
    )
    kb.button(text=f"🔁 {toggle}", callback_data=Nav(action=Action.TOGGLE, report_id=report_id))
    kb.adjust(2)
    return kb.as_markup()


# ---------- все группы ----------


def groups_view(summary: SalesSummary, report_id: int) -> View:
    title = fmt.period_title(summary.meta.date_from, summary.meta.date_to, summary.meta.title)
    rows = [f"{'Группа':<9} {'Продажи':>9} {'Коэф':>5} {'Доля':>6}"]
    for g in sorted(summary.groups, key=lambda g: -g.sales):
        rows.append(
            f"{fmt.clip(g.name, 9):<9} {fmt.money(g.sales, 2):>9} "
            f"{fmt.coef_cell(g.coefficient):>5} {fmt.pct(g.share):>6}"
        )
    t = summary.total
    rows.append(
        f"{'Итого':<9} {fmt.money(t.sales, 2):>9} {fmt.coef_cell(t.coefficient):>5} {'100%':>6}"
    )
    text = "\n".join(
        [
            f"<b>{escape(title)} · все группы</b>",
            f"<pre>{escape(chr(10).join(rows))}</pre>",
            f"Продажи — {_base_short(summary.config.margin_base)}. "
            "Нажмите на группу, чтобы увидеть её позиции.",
        ]
    )
    kb = InlineKeyboardBuilder()
    order = sorted(range(len(summary.groups)), key=lambda i: -summary.groups[i].sales)
    for index in order:
        kb.button(
            text=summary.groups[index].name,
            callback_data=Nav(action=Action.GROUP, report_id=report_id, index=index),
        )
    kb.adjust(GROUP_BUTTONS_PER_ROW)
    back = InlineKeyboardBuilder()
    _back(back, report_id)
    kb.attach(back)
    return View(text, kb.as_markup())


# ---------- одна группа ----------


def group_view(summary: SalesSummary, report_id: int, index: int) -> View:
    if not 0 <= index < len(summary.groups):
        return groups_view(summary, report_id)
    g = summary.groups[index]
    head = (
        f"<b>{escape(g.name)}</b> · {fmt.money(g.sales)} · "
        f"коэф. {fmt.coef(g.coefficient)} · {fmt.pct(g.share)}"
    )
    lines = [head]
    if len(g.sources) > 1 or (g.sources and g.sources[0] != g.name):
        lines.append(f"<i>Из групп iiko: {escape(', '.join(g.sources))}</i>")
    rows = [f"{'Позиция':<15} {'Продажи':>8} {'Коэф':>5}"]
    for item in g.items[:MAX_ITEMS_IN_GROUP]:
        rows.append(
            f"{fmt.clip(item.name, 15):<15} {fmt.money(item.sales, 2):>8} "
            f"{fmt.coef_cell(item.coefficient):>5}"
        )
    lines.append(f"<pre>{escape(chr(10).join(rows))}</pre>")
    rest = len(g.items) - MAX_ITEMS_IN_GROUP
    if rest > 0:
        lines.append(f"и ещё {rest} — в Excel, лист «Позиции»")

    kb = InlineKeyboardBuilder()
    kb.button(text="« Все группы", callback_data=Nav(action=Action.GROUPS, report_id=report_id))
    _back(kb, report_id, text="« К обзору")
    kb.adjust(2)
    return View("\n".join(lines), kb.as_markup())


# ---------- проблемы ----------


def issues_view(summary: SalesSummary, report_id: int) -> View:
    lines = ["<b>⚠️ Что проверить в iiko</b>"]
    if not summary.issues:
        lines.append("Проблем в учёте не найдено.")
    for kind in IssueKind:
        found = [i for i in summary.issues if i.kind is kind]
        if not found:
            continue
        lines += ["", f"<b>{kind.label}</b> ({len(found)})", f"<i>{escape(kind.hint)}</i>"]
        for issue in found[:MAX_ISSUES_PER_KIND]:
            detail = fmt.money(issue.sales)
            if issue.coefficient is not None:
                detail = f"коэф. {fmt.coef(issue.coefficient)} · {detail}"
            lines.append(f"• {escape(issue.item)} — {detail}")
        rest = len(found) - MAX_ISSUES_PER_KIND
        if rest > 0:
            lines.append(f"и ещё {rest} — в Excel, лист «Проверка данных»")
    kb = InlineKeyboardBuilder()
    _back(kb, report_id)
    return View("\n".join(lines), kb.as_markup())


def _back(kb: InlineKeyboardBuilder, report_id: int, text: str = "« Назад") -> None:
    kb.button(text=text, callback_data=Nav(action=Action.OVERVIEW, report_id=report_id))
