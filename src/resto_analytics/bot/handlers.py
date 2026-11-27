"""Обработчики aiogram. Тонкие: принять событие → вызвать ядро → показать экран из views."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import replace

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from resto_analytics.bot.answers import SEND_FILE, QuestionAnswerer
from resto_analytics.bot.store import ReportStore, StoredReport
from resto_analytics.bot.views import (
    HELP_TEXT,
    START_TEXT,
    Action,
    Nav,
    View,
    group_view,
    groups_view,
    issues_view,
    overview_view,
)
from resto_analytics.config import MarginBase, SummaryConfig
from resto_analytics.export.excel import summary_filename, write_summary_xlsx
from resto_analytics.parsing.errors import ParseError
from resto_analytics.parsing.iiko_sales import parse_sales_report
from resto_analytics.reports.group_summary import SalesSummary, build_group_summary

logger = logging.getLogger(__name__)

XLSX_SUFFIXES = (".xlsx", ".xlsm")
OLD_XLS = "Это старый формат .xls. Выгрузите отчёт из iiko в .xlsx и пришлите ещё раз."
NOT_EXCEL = "Нужен файл Excel (.xlsx) — выгрузка «Отчет о продажах» из iiko."
TOO_BIG = "Файл больше {limit:g} МБ. Это точно отчёт о продажах?"
CANT_READ = "Не получилось прочитать файл.\n\n{error}"
EXPIRED = "Отчёт уже не в памяти бота. Пришлите файл ещё раз."
STALE = "Это кнопки старого отчёта. Используйте последний обзор."


def build_router() -> Router:
    """Новый Router на каждый Dispatcher: один Router нельзя подключить дважды."""
    router = Router(name="sales")
    router.message.register(on_start, CommandStart())
    router.message.register(on_help, Command("help"))
    router.message.register(on_document, F.document)
    router.message.register(on_text, F.text)
    router.message.register(on_other)
    router.callback_query.register(on_nav, Nav.filter())
    return router


async def on_start(message: Message) -> None:
    await message.answer(START_TEXT)


async def on_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


async def on_document(
    message: Message,
    bot: Bot,
    store: ReportStore,
    config: SummaryConfig,
    max_upload_bytes: int,
) -> None:
    document = message.document
    assert document is not None  # гарантирует фильтр F.document
    name = document.file_name or ""
    lowered = name.lower()
    if lowered.endswith(".xls"):
        await message.answer(OLD_XLS)
        return
    if not lowered.endswith(XLSX_SUFFIXES):
        await message.answer(NOT_EXCEL)
        return
    if document.file_size and document.file_size > max_upload_bytes:
        await message.answer(TOO_BIG.format(limit=max_upload_bytes / 1024 / 1024))
        return

    started = time.perf_counter()
    buffer = io.BytesIO()
    await bot.download(document, destination=buffer)
    try:
        report = await asyncio.to_thread(parse_sales_report, buffer.getvalue())
    except ParseError as exc:
        await message.answer(CANT_READ.format(error=exc))
        return

    previous = store.get(message.chat.id)
    base = previous.margin_base if previous else config.margin_base
    stored = store.save(message.chat.id, report, name, base)
    summary = _summary(stored, config)
    logger.info(
        "bot report: chat=%s lines=%d groups=%d issues=%d %.0f ms",
        message.chat.id,
        summary.line_count,
        len(summary.groups),
        len(summary.issues),
        (time.perf_counter() - started) * 1000,
    )
    view = overview_view(summary, stored.report_id)
    await message.answer(view.text, reply_markup=view.keyboard)


async def on_text(message: Message, store: ReportStore, answerer: QuestionAnswerer) -> None:
    reply = await answerer.answer(message.text or "", store.get(message.chat.id))
    await message.answer(reply)


async def on_other(message: Message) -> None:
    await message.answer(SEND_FILE)


async def on_nav(
    callback: CallbackQuery,
    callback_data: Nav,
    store: ReportStore,
    config: SummaryConfig,
) -> None:
    message = callback.message
    if not isinstance(message, Message):  # сообщение слишком старое, Telegram его не отдаёт
        await callback.answer(EXPIRED, show_alert=True)
        return
    stored = store.get(message.chat.id)
    if stored is None:
        await callback.answer(EXPIRED, show_alert=True)
        return
    if stored.report_id != callback_data.report_id:
        await callback.answer(STALE, show_alert=True)
        return

    action = callback_data.action
    if action is Action.TOGGLE:
        other = (
            MarginBase.WITHOUT_SERVICE
            if stored.margin_base is MarginBase.WITH_SERVICE
            else MarginBase.WITH_SERVICE
        )
        stored = replace(stored, margin_base=other)
        store.update(message.chat.id, stored)

    summary = _summary(stored, config)
    if action is Action.EXCEL:
        content = await asyncio.to_thread(write_summary_xlsx, summary)
        await message.answer_document(
            BufferedInputFile(content, filename=summary_filename(summary))
        )
        await callback.answer()
        return

    await _show(message, _view_for(action, summary, stored.report_id, callback_data.index))
    await callback.answer()


def _view_for(action: Action, summary: SalesSummary, report_id: int, index: int) -> View:
    if action is Action.GROUPS:
        return groups_view(summary, report_id)
    if action is Action.GROUP:
        return group_view(summary, report_id, index)
    if action is Action.ISSUES:
        return issues_view(summary, report_id)
    return overview_view(summary, report_id)


async def _show(message: Message, view: View) -> None:
    try:
        await message.edit_text(view.text, reply_markup=view.keyboard)
    except TelegramBadRequest as exc:
        # Повторное нажатие той же кнопки — Telegram отвечает «message is not modified»
        if "message is not modified" not in str(exc):
            raise


def _summary(stored: StoredReport, config: SummaryConfig) -> SalesSummary:
    return build_group_summary(
        stored.report, config.model_copy(update={"margin_base": stored.margin_base})
    )
