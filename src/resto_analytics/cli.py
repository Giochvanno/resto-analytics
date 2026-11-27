"""Командная строка.

resto-analytics summary выгрузка.xlsx                 # таблица в терминале
resto-analytics summary выгрузка.xlsx -o сводка.xlsx  # + Excel
resto-analytics summary выгрузка.xlsx --json          # JSON (как отдаёт API)
    resto-analytics summary выгрузка.xlsx --margin-base with_service  # доход с обслуживанием
resto-analytics serve --port 8000                     # веб-интерфейс
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from resto_analytics import __version__
from resto_analytics.config import (
    ConfigError,
    LastColumn,
    MarginBase,
    ServiceSource,
    SummaryConfig,
    load_config,
)
from resto_analytics.export.excel import (
    ExcelOptions,
    last_column_title,
    margin_base_label,
    write_summary_xlsx,
)
from resto_analytics.parsing.errors import ParseError
from resto_analytics.reports.group_summary import GroupRow, SalesSummary
from resto_analytics.service import summarize
from resto_analytics.settings import DEFAULT_CONFIG_PATH

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_BAD_INPUT = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resto-analytics", description="Отчёты из выгрузок iiko.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summary", help="сводка продаж по группам")
    s.add_argument("input", type=Path, help="выгрузка «Отчет о продажах» из iiko (.xlsx)")
    s.add_argument("-o", "--output", type=Path, help="куда сохранить сводку (.xlsx)")
    s.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="файл настроек TOML")
    s.add_argument(
        "--margin-base",
        choices=[v.value for v in MarginBase],
        help="от чего считать доход и коэффициент (по умолчанию without_service)",
    )
    s.add_argument("--service", dest="service_source", choices=[v.value for v in ServiceSource])
    s.add_argument("--last-column", choices=[v.value for v in LastColumn])
    s.add_argument("--formulas", action="store_true", help="писать формулы в Excel")
    s.add_argument("--json", action="store_true", help="вывести JSON вместо таблицы")

    srv = sub.add_parser("serve", help="запустить веб-интерфейс")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)

    sub.add_parser("bot", help="запустить Telegram-бота (настройки RESTO_BOT_* в .env)")
    return parser


def _config_from_args(args: argparse.Namespace) -> SummaryConfig:
    config = load_config(args.config)
    update = {
        key: value
        for key in ("margin_base", "service_source", "last_column")
        if (value := getattr(args, key)) is not None
    }
    return config.model_validate({**config.model_dump(), **update}) if update else config


def _fmt_money(value: Decimal) -> str:
    return f"{round(value):,}".replace(",", " ")


def _fmt_ratio(value: Decimal | None, digits: int) -> str:
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def render_table(summary: SalesSummary) -> str:
    heads = ["Группа", "Без обсл.", "Обсл.", "С обсл.", "Себест.", "Вал. доход", "Коэф.", "%"]
    rows: list[list[str]] = []

    def add(row: GroupRow) -> None:
        rows.append(
            [
                row.name,
                _fmt_money(row.sales_net),
                _fmt_money(row.service),
                _fmt_money(row.sales_total),
                _fmt_money(row.cost),
                _fmt_money(row.gross),
                _fmt_ratio(row.coefficient, 2),
                _fmt_ratio(summary.last_value(row), 1),
            ]
        )

    for group in summary.groups:
        add(group)
    add(summary.total)
    widths = [max(len(r[i]) for r in [heads, *rows]) for i in range(len(heads))]

    def line(cells: Sequence[str]) -> str:
        first = cells[0].ljust(widths[0])
        rest = (c.rjust(w) for c, w in zip(cells[1:], widths[1:], strict=True))
        return "  ".join([first, *rest])

    out = [summary.meta.title, line(heads), "-" * (sum(widths) + 2 * (len(widths) - 1))]
    out += [line(r) for r in rows[:-1]]
    out += ["-" * len(out[-1]), line(rows[-1])]
    out.append(f"Доход, коэффициент и % — от {margin_base_label(summary)}.")
    out.append(f"% — {last_column_title(summary).lower()}")
    rec = summary.reconciliation
    if rec is not None:
        out.append("Сверка с итогом файла: " + ("совпадает" if rec.ok else "НЕ совпадает"))
    if summary.issues:
        out.append(f"На что обратить внимание: {len(summary.issues)} позиц. (см. Excel)")
    return "\n".join(out)


def _summary(args: argparse.Namespace) -> int:
    if not args.input.exists():
        print(f"Файл не найден: {args.input}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = _config_from_args(args)
        summary = summarize(args.input.read_bytes(), config)
    except (ParseError, ConfigError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.json:
        from resto_analytics.web.schemas import SummaryOut  # noqa: PLC0415 — нужен только здесь

        print(SummaryOut.from_domain(summary).model_dump_json(indent=2))
    else:
        print(render_table(summary))
    if args.output:
        args.output.write_bytes(write_summary_xlsx(summary, ExcelOptions(formulas=args.formulas)))
        print(f"Сохранено: {args.output}", file=sys.stderr)
    return EXIT_OK


def _serve(args: argparse.Namespace) -> int:  # pragma: no cover — запускает сервер
    import uvicorn  # noqa: PLC0415

    uvicorn.run("resto_analytics.web.app:create_app", factory=True, host=args.host, port=args.port)
    return EXIT_OK


def _bot() -> int:
    import asyncio  # noqa: PLC0415
    import logging  # noqa: PLC0415

    from resto_analytics.bot.app import (  # noqa: PLC0415
        BotConfigError,
        check_settings,
        run_polling,
        setup_warning,
    )
    from resto_analytics.settings import AppSettings  # noqa: PLC0415

    settings = AppSettings()
    try:
        check_settings(settings)
    except BotConfigError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if warning := setup_warning(settings):
        print(f"Внимание: {warning}", file=sys.stderr)
    logging.basicConfig(  # pragma: no cover — дальше сеть Telegram
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_polling(settings))  # pragma: no cover
    return EXIT_OK  # pragma: no cover


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "summary":
        return _summary(args)
    if args.command == "bot":
        return _bot()
    return _serve(args)  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
