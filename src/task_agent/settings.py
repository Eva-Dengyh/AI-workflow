from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude API
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str | None = Field(default=None, alias="ANTHROPIC_BASE_URL")

    # Agent 行为
    task_agent_model: str = Field(default="claude-opus-4-6", alias="TASK_AGENT_MODEL")
    task_agent_max_dev_retry: int = Field(default=5, alias="TASK_AGENT_MAX_DEV_RETRY")
    task_agent_tasks_dir: Path = Field(default=Path("./tasks"), alias="TASK_AGENT_TASKS_DIR")
    task_agent_log_level: str = Field(default="INFO", alias="TASK_AGENT_LOG_LEVEL")

    @model_validator(mode="after")
    def resolve_tasks_dir(self) -> "Settings":
        self.task_agent_tasks_dir = self.task_agent_tasks_dir.resolve()
        self.task_agent_tasks_dir.mkdir(parents=True, exist_ok=True)
        return self


settings = Settings()  # type: ignore[call-arg]
