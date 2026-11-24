import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from resto_analytics import __version__
from resto_analytics.config import SummaryConfig
from resto_analytics.settings import AppSettings
from resto_analytics.web.app import XLSX_MEDIA_TYPE, content_disposition, create_app

SUMMARY_URL = "/api/v1/sales-summary"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = AppSettings(summary_config=tmp_path / "none.toml", max_upload_mb=1)
    with TestClient(create_app(settings)) as c:
        yield c


def upload(data: bytes, name: str = "Отчет о продажах.xlsx") -> dict[str, tuple[str, bytes]]:
    return {"file": (name, data)}


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_index_page(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Сводка продаж по&nbsp;группам" in resp.text
    assert "/static/app.js" in resp.text
    assert client.get("/static/style.css").status_code == 200


def test_summary_json(client: TestClient, sample_xlsx: bytes) -> None:
    resp = client.post(SUMMARY_URL, files=upload(sample_xlsx))
    assert resp.status_code == 200
    body = resp.json()
    assert [g["name"] for g in body["groups"]] == [
        "Бар",
        "Плов",
        "Самса",
        "Лагман",
        "Супы",
        "Штрафы",
    ]
    total = body["total"]
    assert (total["sales_net"], total["service"], total["sales_total"]) == (80010, 7361, 87371)
    assert total["sales"] == 80010.0  # база для дохода — без обслуживания
    assert total["gross"] == 38036.0
    assert total["coefficient"] == pytest.approx(80010 / 41974, abs=1e-4)
    assert body["reconciliation"]["ok"] is True
    assert body["meta"]["date_from"] == "2026-11-01"
    assert body["margin_base_label"] == "продаж без обслуживания"
    assert body["settings"]["margin_base"] == "without_service"
    bar = body["groups"][0]
    assert bar["sources"] == ["Горячие напитки", "Десерты", "Куырдак"]
    assert bar["items"][0]["name"] == "Куырдак"
    assert bar["items"][0]["sales_total"] == 10120.0
    lagman = body["groups"][3]
    assert lagman["coefficient"] is None
    assert [i["kind"] for i in body["issues"]] == ["zero_cost", "suspicious_cost", "low_margin"]
    assert body["issues"][0]["severity"] == "critical"


def test_settings_from_form_override_config(client: TestClient, sample_xlsx: bytes) -> None:
    resp = client.post(
        SUMMARY_URL,
        files=upload(sample_xlsx),
        data={"margin_base": "with_service", "last_column": "efficiency"},
    )
    body = resp.json()
    assert body["settings"] == {
        "margin_base": "with_service",
        "service_source": "file",
        "last_column": "efficiency",
    }
    assert body["total"]["sales"] == 87371.0
    assert body["total"]["gross"] == 45397.0
    assert body["margin_base_label"] == "продаж с обслуживанием"
    assert body["last_column_title"].startswith("Эффективность")


def test_service_can_be_switched_off(client: TestClient, sample_xlsx: bytes) -> None:
    body = client.post(
        SUMMARY_URL, files=upload(sample_xlsx), data={"service_source": "none"}
    ).json()
    assert body["total"]["service"] == 0
    assert body["total"]["sales_total"] == body["total"]["sales_net"] == 80010.0


def test_bad_setting_value_is_rejected(client: TestClient, sample_xlsx: bytes) -> None:
    resp = client.post(SUMMARY_URL, files=upload(sample_xlsx), data={"margin_base": "profit"})
    assert resp.status_code == 422


def test_xlsx_download(client: TestClient, sample_xlsx: bytes) -> None:
    resp = client.post(f"{SUMMARY_URL}/xlsx", files=upload(sample_xlsx), data={"formulas": "true"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == XLSX_MEDIA_TYPE
    assert (
        "filename*=UTF-8''%D0%A1%D0%B2%D0%BE%D0%B4%D0%BA%D0%B0"
        in resp.headers["content-disposition"]
    )
    ws = load_workbook(io.BytesIO(resp.content))["Сводка"]
    assert ws["E5"].value == "=C5+D5"
    assert ws["G5"].value == "=C5-F5"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("report.xls", "Старый формат .xls"),
        ("report.csv", "Нужен файл Excel"),
        ("", "Нужен файл Excel"),
    ],
)
def test_wrong_file_type(client: TestClient, name: str, message: str) -> None:
    resp = client.post(SUMMARY_URL, files=upload(b"data", name=name or "noname"))
    if name == "":
        resp = client.post(SUMMARY_URL, files={"file": ("noname", b"data")})
    assert resp.status_code == 415
    assert message in resp.json()["detail"]


def test_file_too_large(client: TestClient) -> None:
    resp = client.post(SUMMARY_URL, files=upload(b"0" * (1024 * 1024 + 1)))
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Файл больше 1 МБ."


def test_not_an_iiko_report(client: TestClient) -> None:
    resp = client.post(SUMMARY_URL, files=upload(b"definitely not xlsx"))
    assert resp.status_code == 422
    assert "Excel" in resp.json()["detail"]


def test_missing_file_field(client: TestClient) -> None:
    assert client.post(SUMMARY_URL).status_code == 422


def test_config_is_loaded_from_settings(tmp_path: Path, sample_xlsx: bytes) -> None:
    path = tmp_path / "summary.toml"
    path.write_text('exclude_groups = ["Штрафы"]\n', encoding="utf-8")
    with TestClient(create_app(AppSettings(summary_config=path))) as c:
        body = c.post(SUMMARY_URL, files=upload(sample_xlsx)).json()
    assert body["excluded_lines"] == 1


def test_explicit_config_wins(sample_xlsx: bytes) -> None:
    app = create_app(AppSettings(summary_config=None), SummaryConfig(group_overrides={}))
    with TestClient(app) as c:
        names = [g["name"] for g in c.post(SUMMARY_URL, files=upload(sample_xlsx)).json()["groups"]]
    assert "Лагман" not in names


def test_content_disposition_is_ascii_safe() -> None:
    header = content_disposition("Сводка продаж.xlsx")
    header.encode("latin-1")  # заголовки HTTP должны быть в latin-1
    assert 'filename="svodka.xlsx"' in header
    assert "%D0%A1" in header
