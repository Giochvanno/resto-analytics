import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from resto_analytics import __version__
from resto_analytics.cli import EXIT_BAD_INPUT, EXIT_OK, EXIT_USAGE, main


@pytest.fixture
def report_file(tmp_path: Path, sample_xlsx: bytes) -> Path:
    path = tmp_path / "выгрузка.xlsx"
    path.write_bytes(sample_xlsx)
    return path


@pytest.fixture
def no_config(tmp_path: Path) -> list[str]:
    return ["--config", str(tmp_path / "none.toml")]


def test_prints_table(
    report_file: Path, no_config: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["summary", str(report_file), *no_config]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Отчет о продажах с 01.11.26 по 30.11.26" in out
    assert "Бар" in out
    assert "20 500" in out  # Бар без обслуживания
    assert "22 550" in out  # Бар с обслуживанием
    assert "80 010" in out
    assert "87 371" in out
    assert "38 036" in out  # валовый доход от продаж без обслуживания
    assert "от продаж без обслуживания" in out
    assert "Сверка с итогом файла: совпадает" in out
    assert "На что обратить внимание: 3" in out


def test_writes_excel(report_file: Path, no_config: list[str], tmp_path: Path) -> None:
    out = tmp_path / "сводка.xlsx"
    assert main(["summary", str(report_file), "-o", str(out), "--formulas", *no_config]) == EXIT_OK
    assert load_workbook(out)["Сводка"]["G5"].value == "=C5-F5"


def test_json_output(
    report_file: Path, no_config: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["summary", str(report_file), "--json", "--margin-base", "with_service", *no_config])
        == 0
    )
    body = json.loads(capsys.readouterr().out)
    assert body["settings"]["margin_base"] == "with_service"
    assert body["total"]["sales"] == 87371
    assert body["total"]["gross"] == 45397


def test_efficiency_column(
    report_file: Path, no_config: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "summary",
                str(report_file),
                "--last-column",
                "efficiency",
                "--service",
                "none",
                *no_config,
            ]
        )
        == 0
    )
    assert "эффективность" in capsys.readouterr().out


def test_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summary", str(tmp_path / "nope.xlsx")]) == EXIT_USAGE
    assert "Файл не найден" in capsys.readouterr().err


def test_broken_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"nope")
    assert main(["summary", str(bad)]) == EXIT_BAD_INPUT
    assert "Ошибка:" in capsys.readouterr().err


def test_broken_config(
    report_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "bad.toml"
    cfg.write_text("group_by = 42", encoding="utf-8")
    assert main(["summary", str(report_file), "--config", str(cfg)]) == EXIT_BAD_INPUT
    assert "bad.toml" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
