import os

from pydantic_settings import BaseSettings
from pydantic import model_validator


def default_database_path() -> str:
    if os.getenv("VERCEL"):
        return "/tmp/talosly.db"
    return "./talosly.db"


class Settings(BaseSettings):
    alchemy_api_key: str = ""
    ethereum_rpc_url: str = "https://cloudflare-eth.com"
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_path: str = default_database_path()
    poll_interval_seconds: int = 15
    risk_alert_threshold: int = 70
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    @model_validator(mode="after")
    def use_tmp_database_on_vercel(self):
        if os.getenv("VERCEL") and not os.path.isabs(self.database_path):
            self.database_path = f"/tmp/{os.path.basename(self.database_path)}"
        return self

    class Config:
        env_file = ".env"


settings = Settings()
