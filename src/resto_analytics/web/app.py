"""FastAPI-приложение: страница загрузки + API.

    GET  /                              страница: загрузить выгрузку и посмотреть сводку
    GET  /health                        проверка, что сервис жив
    POST /api/v1/sales-summary          файл → сводка в JSON
    POST /api/v1/sales-summary/xlsx     файл → сводка в Excel

API без состояния: файл не сохраняется на сервере, всё считается в памяти.
Поэтому сервис можно запускать в нескольких копиях за балансировщиком.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from resto_analytics import __version__
from resto_analytics.config import (
    LastColumn,
    SalesSource,
    ServiceSource,
    SummaryConfig,
    load_config,
)
from resto_analytics.export.excel import ExcelOptions
from resto_analytics.parsing.errors import ParseError
from resto_analytics.service import summarize, summarize_to_excel
from resto_analytics.settings import AppSettings
from resto_analytics.web.schemas import ErrorOut, HealthOut, SummaryOut

logger = logging.getLogger("resto_analytics")

_HERE = Path(__file__).parent
ALLOWED_SUFFIXES = (".xlsx", ".xlsm")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ERRORS: dict[int | str, dict[str, object]] = {
    413: {"model": ErrorOut, "description": "Файл больше лимита"},
    415: {"model": ErrorOut, "description": "Не .xlsx"},
    422: {"model": ErrorOut, "description": "Файл не похож на отчёт о продажах iiko"},
}


def create_app(settings: AppSettings | None = None, config: SummaryConfig | None = None) -> FastAPI:
    settings = settings or AppSettings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = FastAPI(
        title="Resto Analytics",
        version=__version__,
        description="Сводные отчёты из выгрузок iiko.",
    )
    app.state.settings = settings
    app.state.config = config or load_config(settings.summary_config)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")

    @app.exception_handler(ParseError)
    async def _parse_error(_: Request, exc: ParseError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"max_upload_mb": settings.max_upload_mb, "version": __version__},
        )

    @app.get("/health", response_model=HealthOut)
    async def health() -> HealthOut:
        return HealthOut(status="ok", version=__version__)

    @app.post("/api/v1/sales-summary", response_model=SummaryOut, responses=_ERRORS)
    async def sales_summary(
        data: Annotated[bytes, Depends(read_upload)],
        cfg: Annotated[SummaryConfig, Depends(request_config)],
    ) -> SummaryOut:
        started = time.perf_counter()
        result = await run_in_threadpool(summarize, data, cfg)
        logger.info(
            "summary: %d lines, %d groups, %d issues, %.0f ms",
            result.line_count,
            len(result.groups),
            len(result.issues),
            (time.perf_counter() - started) * 1000,
        )
        return SummaryOut.from_domain(result)

    @app.post(
        "/api/v1/sales-summary/xlsx",
        responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}, **_ERRORS},
        response_class=Response,
    )
    async def sales_summary_xlsx(
        data: Annotated[bytes, Depends(read_upload)],
        cfg: Annotated[SummaryConfig, Depends(request_config)],
        formulas: Annotated[bool, Form()] = False,
    ) -> Response:
        result = await run_in_threadpool(
            summarize_to_excel, data, cfg, ExcelOptions(formulas=formulas)
        )
        return Response(
            content=result.content,
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": content_disposition(result.filename)},
        )

    return app


async def read_upload(request: Request, file: Annotated[UploadFile, File()]) -> bytes:
    """Проверяет расширение и размер, возвращает байты файла."""
    settings: AppSettings = request.app.state.settings
    name = (file.filename or "").lower()
    if name.endswith(".xls"):
        raise HTTPException(
            415,
            "Старый формат .xls не поддерживается. Выгрузите отчёт из iiko в .xlsx.",
        )
    if not name.endswith(ALLOWED_SUFFIXES):
        raise HTTPException(
            415,
            "Нужен файл Excel (.xlsx) — выгрузка «Отчет о продажах» из iiko.",
        )
    limit = settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            413,
            f"Файл больше {settings.max_upload_mb:g} МБ.",
        )
    return data


def request_config(
    request: Request,
    sales_source: Annotated[SalesSource | None, Form()] = None,
    service_source: Annotated[ServiceSource | None, Form()] = None,
    last_column: Annotated[LastColumn | None, Form()] = None,
) -> SummaryConfig:
    """Настройки из файла конфигурации, поверх — то, что пользователь выбрал на странице."""
    base: SummaryConfig = request.app.state.config
    update = {
        key: value
        for key, value in (
            ("sales_source", sales_source),
            ("service_source", service_source),
            ("last_column", last_column),
        )
        if value is not None
    }
    return base.model_copy(update=update) if update else base


def content_disposition(filename: str) -> str:
    """Имя файла на кириллице: ASCII-запасной вариант + filename* по RFC 5987."""
    return f"attachment; filename=\"svodka.xlsx\"; filename*=UTF-8''{quote(filename)}"
