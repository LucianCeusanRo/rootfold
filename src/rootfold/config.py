from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ROOTFOLD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/rootfold.db")
    jwt_secret: str = Field(default="dev-only-change-me")
    jwt_expire_minutes: int = 480
    admin_username: str = "admin"
    admin_password: str = "changeme"
    webhook_key: str = "lab-webhook-key"
    night_username: str = "night"
    night_password: str = "changeme"
    recovery_sweep_seconds: int = 300
    # 0 disables the background sweep loop (tests). Lab compose sets 15.
    sweep_interval_seconds: int = 15
    log_level: str = "INFO"
    app_name: str = "Rootfold"
    # When True, the public-facing copy must keep the lab disclaimer visible.
    lab_mode: bool = True
    # NetBox (optional). A fixture path skips HTTP and is how tests run offline.
    netbox_url: str = ""
    netbox_token: str = ""
    netbox_fixture: str = ""
    # Ticket exporters (optional). Empty means dry-run only.
    jira_url: str = ""
    jira_user: str = ""
    jira_token: str = ""
    jira_project: str = "NOC"
    jira_issue_type: str = "Incident"
    snow_url: str = ""
    snow_user: str = ""
    snow_password: str = ""
    # Monthly availability SLA threshold (percent). Below this is a breach.
    sla_percent: float = 99.9


def get_settings() -> Settings:
    return Settings()
