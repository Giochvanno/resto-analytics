from pathlib import Path

import pytest

from resto_analytics.settings import DEFAULT_CONFIG_PATH, AppSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key in (
        "RESTO_MAX_UPLOAD_MB",
        "RESTO_SUMMARY_CONFIG",
        "RESTO_LOG_LEVEL",
        "RESTO_BOT_TOKEN",
        "RESTO_BOT_ALLOWED_USERS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_defaults(clean_env: Path) -> None:
    settings = AppSettings()
    assert settings.max_upload_mb == 10
    assert settings.max_upload_bytes == 10 * 1024 * 1024
    assert settings.summary_config == DEFAULT_CONFIG_PATH
    assert settings.log_level == "INFO"


def test_reads_dotenv_file(clean_env: Path) -> None:
    (clean_env / ".env").write_text(
        "RESTO_MAX_UPLOAD_MB=2\nRESTO_SUMMARY_CONFIG=my.toml\nRESTO_LOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )
    settings = AppSettings()
    assert settings.max_upload_mb == 2
    assert settings.summary_config == Path("my.toml")
    assert settings.log_level == "DEBUG"


def test_environment_beats_dotenv(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (clean_env / ".env").write_text("RESTO_MAX_UPLOAD_MB=2\n", encoding="utf-8")
    monkeypatch.setenv("RESTO_MAX_UPLOAD_MB", "5")
    assert AppSettings().max_upload_mb == 5


def test_rejects_absurd_limit(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTO_MAX_UPLOAD_MB", "1000")
    with pytest.raises(ValueError, match="max_upload_mb"):
        AppSettings()


def test_env_example_lists_every_setting() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for name in AppSettings.model_fields:
        assert f"RESTO_{name.upper()}=" in example, f"добавьте RESTO_{name.upper()} в .env.example"


def test_bot_allowed_users_parsing(clean_env: Path) -> None:
    settings = AppSettings(bot_allowed_users=" 111, 222;333 ,")
    assert settings.allowed_user_ids == frozenset({111, 222, 333})
    assert AppSettings().allowed_user_ids == frozenset()


def test_bot_allowed_users_must_be_numbers(clean_env: Path) -> None:
    with pytest.raises(ValueError, match="@papa"):
        AppSettings(bot_allowed_users="111, @papa")


def test_bot_token_is_hidden_in_repr(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESTO_BOT_TOKEN", "42:SECRET")
    settings = AppSettings()
    assert "SECRET" not in repr(settings)
    assert settings.bot_token is not None
    assert settings.bot_token.get_secret_value() == "42:SECRET"
