"""Где бот держит последний загруженный отчёт каждого чата.

Сейчас — в памяти процесса: после перезапуска бота файл нужно прислать заново.
Когда появится история в PostgreSQL, сюда встанет реализация на базе,
а обработчики не изменятся — они работают через протокол ReportStore.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from itertools import count
from typing import Protocol

from resto_analytics.config import MarginBase
from resto_analytics.domain.models import SalesReport

DEFAULT_MAX_CHATS = 100


@dataclass(frozen=True, slots=True)
class StoredReport:
    report_id: int
    """Номер загрузки: по нему кнопки под старыми сообщениями понимают, что отчёт уже другой."""
    report: SalesReport
    filename: str
    margin_base: MarginBase


class ReportStore(Protocol):
    def get(self, chat_id: int) -> StoredReport | None: ...

    def save(
        self, chat_id: int, report: SalesReport, filename: str, margin_base: MarginBase
    ) -> StoredReport:
        """Сохраняет новую загрузку и выдаёт ей номер."""
        ...

    def update(self, chat_id: int, stored: StoredReport) -> None:
        """Меняет настройки уже сохранённой загрузки (номер тот же)."""
        ...


class InMemoryReportStore:
    """Последний отчёт на чат; самые давние чаты вытесняются после max_chats."""

    def __init__(self, max_chats: int = DEFAULT_MAX_CHATS) -> None:
        if max_chats < 1:
            raise ValueError("max_chats должен быть больше нуля")
        self._items: OrderedDict[int, StoredReport] = OrderedDict()
        self._max = max_chats
        self._ids = count(1)

    def get(self, chat_id: int) -> StoredReport | None:
        stored = self._items.get(chat_id)
        if stored is not None:
            self._items.move_to_end(chat_id)
        return stored

    def save(
        self, chat_id: int, report: SalesReport, filename: str, margin_base: MarginBase
    ) -> StoredReport:
        stored = StoredReport(next(self._ids), report, filename, margin_base)
        self._items[chat_id] = stored
        self._items.move_to_end(chat_id)
        while len(self._items) > self._max:
            self._items.popitem(last=False)
        return stored

    def update(self, chat_id: int, stored: StoredReport) -> None:
        if chat_id in self._items:
            self._items[chat_id] = stored

    def __len__(self) -> int:
        return len(self._items)
