import pytest
from pydantic import ValidationError

from civicripple.config import RuntimeMode, Settings


def test_default_mode_is_local_replay() -> None:
    settings = Settings()
    assert settings.mode is RuntimeMode.LOCAL_REPLAY


def test_mode_accepts_aws() -> None:
    settings = Settings(mode="aws")
    assert settings.mode is RuntimeMode.AWS


def test_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(mode="mock")


def test_aws_settings_defaults(monkeypatch) -> None:
    for var in ("AWS_REGION", "BEDROCK_MODEL_ID", "DYNAMODB_TABLE"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings()
    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id == "us.anthropic.claude-sonnet-4-6"
    assert settings.dynamodb_table == "civicripple"


def test_aws_settings_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5")
    monkeypatch.setenv("DYNAMODB_TABLE", "civicripple-demo")
    settings = Settings()
    assert settings.aws_region == "eu-west-1"
    assert settings.bedrock_model_id == "us.anthropic.claude-haiku-4-5"
    assert settings.dynamodb_table == "civicripple-demo"


def test_require_aws_passes_when_configured() -> None:
    settings = Settings(mode="aws")
    settings.require_aws()  # defaults are complete -> no raise


def test_require_aws_fails_closed_on_blank_setting(monkeypatch) -> None:
    monkeypatch.setenv("DYNAMODB_TABLE", "")
    settings = Settings(mode="aws")
    with pytest.raises(RuntimeError, match="DYNAMODB_TABLE"):
        settings.require_aws()


def test_require_aws_is_noop_in_replay() -> None:
    settings = Settings(mode="local_replay")
    settings.require_aws()  # never raises in replay
