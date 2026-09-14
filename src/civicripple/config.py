from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeMode(StrEnum):
    LOCAL_REPLAY = "local_replay"
    AWS = "aws"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mode: RuntimeMode = RuntimeMode.LOCAL_REPLAY
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-6"
    dynamodb_table: str = "civicripple"

    def require_aws(self) -> None:
        """Fail closed: aws mode with incomplete configuration never runs."""
        if self.mode is not RuntimeMode.AWS:
            return
        for name in ("aws_region", "bedrock_model_id", "dynamodb_table"):
            if not getattr(self, name):
                raise RuntimeError(
                    f"MODE=aws requires a non-empty {name.upper()} setting"
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
