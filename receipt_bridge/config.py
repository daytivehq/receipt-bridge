from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .runner_auth import runner_token

CREDENTIAL_FIELDS = ("telegram_token", "ledger_password")


def configured(secret: SecretStr) -> bool:
    value = secret.get_secret_value().strip()
    return bool(value) and not value.startswith("REPLACE_")


def valid_runner_token(value: str) -> bool:
    return 32 <= len(value) <= 256 and all(33 <= ord(char) <= 126 for char in value)


def telegram_identity(value: SecretStr) -> str:
    token = value.get_secret_value()
    if not token:
        return ""
    return token.split(":", 1)[0]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    web_enabled: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8092, ge=1, le=65535)
    web_secure_cookie: bool = False
    data_dir: Path = Path("data")
    timezone: str = "Asia/Seoul"
    telegram_token: SecretStr = SecretStr("")
    ledger_password: SecretStr = SecretStr("")
    ledger_url: str = "http://duet-ledger:8080/api/v1"
    allowed_users: list[int] = Field(default_factory=list)
    allowed_chats: list[int] = Field(default_factory=list)
    user_accounts: dict[str, str] = Field(default_factory=dict)
    chat_accounts: dict[str, str] = Field(default_factory=dict)
    ai_provider: Literal["ollama", "codex", "claude", "agy"] = "ollama"
    ai_model: str = ""
    allow_external_ai: bool = False
    ollama_url: str = "http://host.docker.internal:11434"
    ai_runner_token: SecretStr = SecretStr("")
    ai_runner_url: str = "http://ai-runner:8090"
    ai_timeout: int = Field(default=180, ge=10, le=1800)
    max_download_mb: int = Field(default=20, ge=1, le=20)
    max_attempts: int = Field(default=5, ge=1, le=20)
    retry_seconds: int = Field(default=30, ge=1)
    max_amount_minor: int = Field(default=9000000000000, ge=1, le=9000000000000)
    auto_save: bool = False
    auto_max_amount_minor: int = Field(default=50000, ge=1)
    auto_max_age_days: int = Field(default=7, ge=0, le=365)
    ocr_languages: str = "kor+eng"

    @model_validator(mode="after")
    def validate_settings(self):
        from urllib.parse import urlsplit

        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("올바른 IANA 시간대를 지정하세요") from None
        for value in (self.ledger_url, self.ollama_url, self.ai_runner_url):
            u = urlsplit(value)
            if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
                raise ValueError("주소는 인증 정보 없는 http 또는 https 주소여야 합니다")
            if u.query or u.fragment:
                raise ValueError("주소에 쿼리나 fragment를 넣지 마세요")
        if not self.ledger_url.rstrip("/").endswith("/api/v1"):
            raise ValueError("ledger_url은 /api/v1로 끝나야 합니다")
        return self

    def authorized(self, user: int, chat: int) -> bool:
        # Both lists must match; an empty list never permits everyone.
        return user in self.allowed_users and chat in self.allowed_chats

    def account_for(self, user: int, chat: int) -> str:
        return self.user_accounts.get(str(user)) or self.chat_accounts.get(str(chat), "")

    def account_allowed(self, user: int, chat: int, account: str) -> bool:
        return bool(account) and account == self.account_for(user, chat)

    def readiness(self):
        checks = {
            "telegram": configured(self.telegram_token),
            "ledger": configured(self.ledger_password),
            "allowlist": bool(self.allowed_users and self.allowed_chats),
            "account": bool(self.user_accounts or self.chat_accounts)
            and all(
                self.account_for(user, chat) for user in self.allowed_users for chat in self.allowed_chats
            ),
            "ai": bool(
                self.ai_model.strip()
                and (
                    self.ai_provider == "ollama"
                    or (
                        self.allow_external_ai and valid_runner_token(self.ai_runner_token.get_secret_value())
                    )
                )
            ),
        }
        return checks

    def check_runtime(self):
        if self.ai_provider != "ollama" and not self.allow_external_ai:
            raise ValueError("외부 CLI AI에는 allow_external_ai=true가 필요합니다")
        if not all(self.readiness().values()):
            raise ValueError("접속 키·허용 사용자·채팅·저장 계좌·AI 설정을 확인하세요")


def load_settings(path: str | Path = "config.toml") -> Settings:
    with open(path, "rb") as f:
        values = tomllib.load(f)
    for env, field in (
        ("TELEGRAM_BOT_TOKEN", "telegram_token"),
        ("DUET_APP_PASSWORD", "ledger_password"),
    ):
        secret_file = os.getenv(env + "_FILE")
        values[field] = Path(secret_file).read_text().strip() if secret_file else os.getenv(env, "")
    values["ai_runner_token"] = runner_token(create=True)
    return Settings(**values)
