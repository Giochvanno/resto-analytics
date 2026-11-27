"""Сборка и запуск бота."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from resto_analytics.bot.access import AllowListMiddleware
from resto_analytics.bot.answers import HintAnswerer, QuestionAnswerer
from resto_analytics.bot.handlers import build_router
from resto_analytics.bot.store import InMemoryReportStore, ReportStore
from resto_analytics.config import SummaryConfig, load_config
from resto_analytics.settings import AppSettings

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="help", description="Как пользоваться"),
]


class BotConfigError(Exception):
    """Не хватает настроек, чтобы запустить бота."""


def create_dispatcher(
    *,
    config: SummaryConfig,
    allowed_user_ids: frozenset[int],
    max_upload_bytes: int,
    store: ReportStore | None = None,
    answerer: QuestionAnswerer | None = None,
) -> Dispatcher:
    """Dispatcher со всеми обработчиками. Зависимости попадают в обработчики по имени аргумента."""
    dp = Dispatcher(
        config=config,
        store=store if store is not None else InMemoryReportStore(),
        answerer=answerer if answerer is not None else HintAnswerer(),
        max_upload_bytes=max_upload_bytes,
    )
    access = AllowListMiddleware(allowed_user_ids)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(build_router())
    return dp


def create_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


SETUP_MODE = (
    "RESTO_BOT_ALLOWED_USERS пуст: бот никого не пускает и только сообщает Telegram ID. "
    "Напишите боту /start, впишите свой ID в .env и перезапустите бота."
)


def check_settings(settings: AppSettings) -> str:
    """Возвращает токен или объясняет, чего не хватает.

    Пустой белый список — не ошибка: так бот можно запустить первый раз и узнать
    свой ID. Данных он при этом никому не показывает.
    """
    if settings.bot_token is None or not settings.bot_token.get_secret_value():
        raise BotConfigError(
            "Не задан RESTO_BOT_TOKEN. Получите токен у @BotFather и пропишите его в .env."
        )
    return settings.bot_token.get_secret_value()


def setup_warning(settings: AppSettings) -> str | None:
    """Предупреждение для режима настройки, когда в белом списке никого нет."""
    return None if settings.allowed_user_ids else SETUP_MODE


async def run_polling(settings: AppSettings) -> None:  # pragma: no cover — сеть Telegram
    token = check_settings(settings)
    bot = create_bot(token)
    dp = create_dispatcher(
        config=load_config(settings.summary_config),
        allowed_user_ids=settings.allowed_user_ids,
        max_upload_bytes=settings.max_upload_bytes,
    )
    await bot.set_my_commands(COMMANDS)
    if warning := setup_warning(settings):
        logger.warning(warning)
    logger.info("bot started, allowed users: %d", len(settings.allowed_user_ids))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
