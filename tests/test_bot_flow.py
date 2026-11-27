"""Бот целиком: апдейт → Dispatcher (фильтры, доступ, зависимости) → что ушло в Telegram."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetFile, SendDocument, SendMessage

from resto_analytics.bot.answers import SEND_FILE, USE_BUTTONS
from resto_analytics.bot.app import create_dispatcher
from resto_analytics.bot.handlers import EXPIRED, NOT_EXCEL, OLD_XLS, STALE
from resto_analytics.bot.store import InMemoryReportStore, StoredReport
from resto_analytics.bot.views import HELP_TEXT, START_TEXT, Action, Nav
from resto_analytics.config import MarginBase, SummaryConfig
from tests.factories import SAMPLE_LINES, make_iiko_xlsx
from tests.telegram_fakes import (
    CHAT,
    OWNER,
    STRANGER,
    FakeSession,
    callback_update,
    document_update,
    feed,
    location_update,
    make_bot,
    run,
    text_update,
)


@dataclass
class BotEnv:
    dp: Dispatcher
    bot: Bot
    session: FakeSession
    store: InMemoryReportStore

    def send(self, update: object) -> None:
        run(feed(self.dp, self.bot, update))  # type: ignore[arg-type]

    def upload(self, data: bytes, file_id: str = "f1", name: str = "Отчет о продажах.xlsx") -> None:
        self.session.files[file_id] = data
        self.send(document_update(file_id, name))

    def press(self, action: Action, index: int = -1, report_id: int | None = None) -> None:
        stored = self.store.get(CHAT.id)
        rid = report_id if report_id is not None else (stored.report_id if stored else 1)
        self.send(callback_update(Nav(action=action, report_id=rid, index=index).pack()))

    def stored(self) -> StoredReport:
        stored = self.store.get(CHAT.id)
        assert stored is not None
        return stored

    def alert(self) -> AnswerCallbackQuery:
        answers = self.session.sent(AnswerCallbackQuery)
        assert answers, "бот не ответил на нажатие кнопки"
        return answers[-1]  # type: ignore[no-any-return]


@pytest.fixture
def env() -> BotEnv:
    session = FakeSession()
    store = InMemoryReportStore()
    dp = create_dispatcher(
        config=SummaryConfig(),
        allowed_user_ids=frozenset({OWNER.id}),
        max_upload_bytes=1024 * 1024,
        store=store,
    )
    return BotEnv(dp, make_bot(session), session, store)


@pytest.fixture
def uploaded(env: BotEnv, sample_xlsx: bytes) -> BotEnv:
    env.upload(sample_xlsx)
    env.session.clear()
    return env


# ---------- команды и текст ----------


def test_start_and_help(env: BotEnv) -> None:
    env.send(text_update("/start"))
    assert env.session.last_text() == START_TEXT
    env.send(text_update("/help"))
    assert env.session.last_text() == HELP_TEXT


def test_text_before_and_after_file(env: BotEnv, sample_xlsx: bytes) -> None:
    env.send(text_update("сколько самсы продали?"))
    assert env.session.last_text() == SEND_FILE
    env.upload(sample_xlsx)
    env.send(text_update("сколько самсы продали?"))
    assert env.session.last_text() == USE_BUTTONS


def test_other_content_gets_a_hint(env: BotEnv) -> None:
    env.send(location_update())
    assert env.session.last_text() == SEND_FILE


def test_custom_answerer_is_used(sample_xlsx: bytes) -> None:
    """Сюда потом встанет ИИ-агент: бот отдаёт ему вопрос и последний отчёт."""

    class EchoAgent:
        async def answer(self, question: str, stored: StoredReport | None) -> str:
            lines = len(stored.report.lines) if stored else 0
            return f"{question} | позиций: {lines}"

    session = FakeSession()
    dp = create_dispatcher(
        config=SummaryConfig(),
        allowed_user_ids=frozenset({OWNER.id}),
        max_upload_bytes=1024 * 1024,
        answerer=EchoAgent(),
    )
    bot = make_bot(session)
    session.files["f1"] = sample_xlsx
    run(feed(dp, bot, document_update("f1")))
    run(feed(dp, bot, text_update("как плов?")))
    assert session.last_text() == "как плов? | позиций: 10"


# ---------- загрузка файла ----------


def test_upload_shows_overview(env: BotEnv, sample_xlsx: bytes) -> None:
    env.upload(sample_xlsx)
    assert len(env.session.sent(GetFile)) == 1
    reply = env.session.sent(SendMessage)[-1]
    assert "<b>📊 Ноябрь 2026</b>" in reply.text
    assert "✓ сходится с итогом iiko" in reply.text
    assert "Выручка <b>87 тыс</b> тг" in reply.text
    buttons = [b.text for row in reply.reply_markup.inline_keyboard for b in row]
    assert buttons == ["📋 Все группы", "⚠️ Проблемы (3)", "📎 Excel", "🔁 Считать с обслуживанием"]
    stored = env.stored()
    assert stored.filename == "Отчет о продажах.xlsx"
    assert stored.margin_base is MarginBase.WITHOUT_SERVICE


@pytest.mark.parametrize(
    ("name", "expected"),
    [("отчет.xls", OLD_XLS), ("отчет.pdf", NOT_EXCEL), ("без расширения", NOT_EXCEL)],
)
def test_wrong_file_type(env: BotEnv, name: str, expected: str) -> None:
    env.upload(b"whatever", name=name)
    assert env.session.last_text() == expected
    assert not env.session.sent(GetFile)  # даже не скачиваем


def test_too_big_file_is_not_downloaded(env: BotEnv) -> None:
    env.send(document_update("big", file_size=5 * 1024 * 1024))
    assert "больше 1 МБ" in env.session.last_text()
    assert not env.session.sent(GetFile)


def test_broken_file(env: BotEnv) -> None:
    env.upload(b"not an excel file")
    text = env.session.last_text()
    assert text.startswith("Не получилось прочитать файл.")
    assert "Excel" in text
    assert env.store.get(CHAT.id) is None


def test_new_upload_gets_new_report_id(env: BotEnv, sample_xlsx: bytes) -> None:
    env.upload(sample_xlsx)
    first = env.stored().report_id
    env.upload(sample_xlsx, file_id="f2")
    assert env.stored().report_id == first + 1


# ---------- доступ ----------


def test_stranger_gets_their_id_and_nothing_else(env: BotEnv, sample_xlsx: bytes) -> None:
    env.session.files["f1"] = sample_xlsx
    env.send(text_update("/start", user=STRANGER))
    assert "Нет доступа" in env.session.last_text()
    assert f"<code>{STRANGER.id}</code>" in env.session.last_text()
    assert not env.session.sent(GetFile)


def test_stranger_cannot_press_buttons(uploaded: BotEnv) -> None:
    nav = Nav(action=Action.GROUPS, report_id=uploaded.stored().report_id).pack()
    uploaded.send(callback_update(nav, user=STRANGER))
    assert not uploaded.session.sent(EditMessageText)
    alert = uploaded.alert()
    assert alert.show_alert
    assert str(STRANGER.id) in (alert.text or "")


def test_empty_allow_list_lets_nobody_in() -> None:
    session = FakeSession()
    dp = create_dispatcher(
        config=SummaryConfig(), allowed_user_ids=frozenset(), max_upload_bytes=1024
    )
    run(feed(dp, make_bot(session), text_update("/start")))
    assert "Нет доступа" in session.last_text()


# ---------- кнопки ----------


def test_all_groups(uploaded: BotEnv) -> None:
    uploaded.press(Action.GROUPS)
    edit = uploaded.session.sent(EditMessageText)[-1]
    assert "все группы" in edit.text
    assert "<pre>" in edit.text
    buttons = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert buttons[:3] == ["Самса", "Бар", "Плов"]  # по убыванию продаж
    assert buttons[-1] == "« Назад"
    assert uploaded.alert().text is None  # просто «нажатие принято», без всплывашки


def test_one_group(uploaded: BotEnv) -> None:
    uploaded.press(Action.GROUP, index=0)  # Бар — первая строка сводки
    text = uploaded.session.last_text()
    assert text.startswith("<b>Бар</b>")
    assert "Из групп iiko: Горячие напитки, Десерты, Куырдак" in text


def test_issues(uploaded: BotEnv) -> None:
    uploaded.press(Action.ISSUES)
    text = uploaded.session.last_text()
    assert "Что проверить в iiko" in text
    assert "Куырдак — коэф. 1,12" in text


def test_back_to_overview(uploaded: BotEnv) -> None:
    uploaded.press(Action.GROUPS)
    uploaded.press(Action.OVERVIEW)
    assert "📊 Ноябрь 2026" in uploaded.session.last_text()


def test_excel(uploaded: BotEnv) -> None:
    uploaded.press(Action.EXCEL)
    doc = uploaded.session.sent(SendDocument)[-1]
    assert doc.document.filename == "Сводка_продаж_01.11.26-30.11.26.xlsx"
    assert doc.document.data[:2] == b"PK"  # это zip, то есть xlsx


def test_toggle_service_and_back(uploaded: BotEnv, sample_xlsx: bytes) -> None:
    rid = uploaded.stored().report_id
    uploaded.press(Action.TOGGLE)
    text = uploaded.session.last_text()
    assert "от продаж с обслуживанием" in text
    assert uploaded.stored().margin_base is MarginBase.WITH_SERVICE
    assert uploaded.stored().report_id == rid  # тот же отчёт, кнопки не устарели

    # выбор запоминается и для следующего файла
    uploaded.upload(sample_xlsx, file_id="f2")
    assert "от продаж с обслуживанием" in uploaded.session.last_text()

    uploaded.press(Action.TOGGLE)
    assert "от продаж без обслуживания" in uploaded.session.last_text()


def test_buttons_of_old_report(uploaded: BotEnv, sample_xlsx: bytes) -> None:
    old = uploaded.stored().report_id
    uploaded.upload(sample_xlsx, file_id="f2")
    uploaded.session.clear()
    uploaded.press(Action.GROUPS, report_id=old)
    assert not uploaded.session.sent(EditMessageText)
    assert uploaded.alert().text == STALE


def test_buttons_after_restart(env: BotEnv) -> None:
    env.press(Action.GROUPS, report_id=1)  # в памяти ничего нет — как после перезапуска
    assert env.alert().text == EXPIRED


def test_too_old_message(uploaded: BotEnv) -> None:
    nav = Nav(action=Action.GROUPS, report_id=uploaded.stored().report_id).pack()
    uploaded.send(callback_update(nav, inaccessible=True))
    assert uploaded.alert().text == EXPIRED


def test_pressing_same_button_twice_is_fine(uploaded: BotEnv) -> None:
    uploaded.session.edit_error = "Bad Request: message is not modified"
    uploaded.press(Action.OVERVIEW)
    assert uploaded.alert().text is None


def test_other_telegram_errors_are_not_swallowed(uploaded: BotEnv) -> None:
    uploaded.session.edit_error = "Bad Request: message to edit not found"
    with pytest.raises(TelegramBadRequest):
        uploaded.press(Action.OVERVIEW)


def test_full_sample_report_round_trip(env: BotEnv) -> None:
    env.upload(make_iiko_xlsx(SAMPLE_LINES[:3]))
    assert "Больше всего продаж" in env.session.last_text()
