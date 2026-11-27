"""Фейковый Telegram для тестов бота.

FakeSession подменяет сетевой слой aiogram: бот «отправляет» запросы, а сессия
их записывает и отвечает правдоподобными объектами. Апдейты прогоняются через
настоящий Dispatcher — с фильтрами, middleware и внедрением зависимостей.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from datetime import UTC, datetime
from itertools import count
from typing import Any, TypeVar

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, GetFile, SendDocument, SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    File,
    InaccessibleMessage,
    Location,
    Message,
    Update,
    User,
)

T = TypeVar("T")
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
OWNER = User(id=111, is_bot=False, first_name="Папа")
STRANGER = User(id=999, is_bot=False, first_name="Кто-то")
BOT_USER = User(id=42, is_bot=True, first_name="Resto")
CHAT = Chat(id=111, type="private")
_ids = count(1)


class FakeSession(BaseSession):
    # Сигнатуры повторяют BaseSession, поэтому часть аргументов не используется.
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.files: dict[str, bytes] = {}
        self.edit_error: str | None = None

    async def make_request(
        self,
        bot: Bot,  # noqa: ARG002
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ARG002
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, GetFile):
            return File(
                file_id=method.file_id,
                file_unique_id=method.file_id,
                file_path=f"documents/{method.file_id}",
            )
        if isinstance(method, EditMessageText) and self.edit_error:
            raise TelegramBadRequest(method=method, message=self.edit_error)
        if isinstance(method, SendMessage | SendDocument):
            return Message(message_id=next(_ids), date=NOW, chat=CHAT, from_user=BOT_USER)
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,  # noqa: ARG002
        timeout: int = 30,  # noqa: ARG002
        chunk_size: int = 65536,  # noqa: ARG002
        raise_for_status: bool = True,  # noqa: ARG002
    ) -> AsyncGenerator[bytes, None]:
        yield self.files[url.rsplit("/", 1)[-1]]

    async def close(self) -> None:
        return None

    # --- удобные выборки для проверок ---

    def sent(self, kind: type[TelegramMethod[Any]]) -> list[Any]:
        return [r for r in self.requests if isinstance(r, kind)]

    def last_text(self) -> str:
        texts = [r.text for r in self.requests if isinstance(r, SendMessage | EditMessageText)]
        return str(texts[-1])

    def clear(self) -> None:
        self.requests.clear()


def make_bot(session: FakeSession) -> Bot:
    return Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def feed(dp: Dispatcher, bot: Bot, update: Update) -> None:
    await dp.feed_update(bot, update)


def text_update(text: str, user: User = OWNER) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(message_id=next(_ids), date=NOW, chat=CHAT, from_user=user, text=text),
    )


def document_update(
    file_id: str, file_name: str = "Отчет о продажах.xlsx", file_size: int | None = None
) -> Update:
    document = Document(
        file_id=file_id, file_unique_id=file_id, file_name=file_name, file_size=file_size
    )
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids), date=NOW, chat=CHAT, from_user=OWNER, document=document
        ),
    )


def location_update() -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=NOW,
            chat=CHAT,
            from_user=OWNER,
            location=Location(latitude=43.24, longitude=76.89),
        ),
    )


def callback_update(data: str, user: User = OWNER, *, inaccessible: bool = False) -> Update:
    message: Message | InaccessibleMessage
    if inaccessible:
        message = InaccessibleMessage(chat=CHAT, message_id=next(_ids))
    else:
        message = Message(
            message_id=next(_ids), date=NOW, chat=CHAT, from_user=BOT_USER, text="обзор"
        )
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)), from_user=user, chat_instance="ci", data=data, message=message
        ),
    )
