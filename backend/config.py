from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    alchemy_api_key: str = ""
    ethereum_rpc_url: str = "https://cloudflare-eth.com"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_url: str = "postgresql://talosly:talosly_secret@localhost:5432/talosly"
    database_public_url: str = ""
    poll_interval_seconds: int = 15
    risk_alert_threshold: int = 70
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    public_url: str = "http://localhost"
    api_key_secret_salt: str = "development_only_change_this_32_chars"
    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 5000
    admin_secret: str = "development_admin_secret_32_chars"
    log_level: str = "INFO"
    log_format: str = "pretty"
    app_env: str = "development"
    resend_api_key: str = ""

    @model_validator(mode="after")
    def validate_launch_settings(self):
        if self.app_env == "production" and len(self.admin_secret) < 32:
            raise ValueError("ADMIN_SECRET must be at least 32 characters in production")
        return self

    class Config:
        env_file = ".env"


settings = Settings()
