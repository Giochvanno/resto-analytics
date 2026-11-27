"""Доступ к боту только по белому списку Telegram ID: в отчётах деньги заведения."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

logger = logging.getLogger(__name__)

DENIED = (
    "Нет доступа.\n\n"
    "Ваш Telegram ID: <code>{user_id}</code>\n"
    "Передайте его владельцу бота, чтобы он добавил вас в RESTO_BOT_ALLOWED_USERS."
)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AllowListMiddleware(BaseMiddleware):
    """Пропускает только пользователей из списка. Пустой список — не пускает никого."""

    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self._allowed = allowed_user_ids

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and user.id in self._allowed:
            return await handler(event, data)

        user_id = user.id if user is not None else "неизвестен"
        logger.warning("access denied: user_id=%s", user_id)
        text = DENIED.format(user_id=user_id)
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(f"Нет доступа. Ваш Telegram ID: {user_id}", show_alert=True)
        return None
