"""Ответ на свободный текст в чате.

Сейчас бот только подсказывает, что делать. Это место, куда встанет ИИ-агент:
достаточно написать класс с тем же методом answer() — он получит вопрос и
последний загруженный отчёт, а для фактов будет вызывать те же функции,
что и кнопки (insights.build_overview, reports.build_group_summary).
"""

from __future__ import annotations

from typing import Protocol

from resto_analytics.bot.store import StoredReport

SEND_FILE = (
    "Пришлите выгрузку «Отчет о продажах» из iiko в формате .xlsx — "
    "посчитаю продажи, себестоимость и доход по группам."
)
USE_BUTTONS = (
    "Пока я понимаю только файлы и кнопки под отчётом. "
    "Пришлите новую выгрузку или нажмите кнопку под последним отчётом."
)


class QuestionAnswerer(Protocol):
    async def answer(self, question: str, stored: StoredReport | None) -> str: ...


class HintAnswerer:
    """Без ИИ: подсказывает, что прислать или куда нажать."""

    async def answer(self, question: str, stored: StoredReport | None) -> str:  # noqa: ARG002
        # Вопрос пока не разбираем — это работа будущего ИИ-агента.
        return SEND_FILE if stored is None else USE_BUTTONS
