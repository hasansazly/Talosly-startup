from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    alchemy_api_key: str = ""
    ethereum_rpc_url: str = "https://cloudflare-eth.com"
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_path: str = "./talosly.db"
    poll_interval_seconds: int = 15
    risk_alert_threshold: int = 70
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


settings = Settings()
