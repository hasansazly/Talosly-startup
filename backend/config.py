from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    alchemy_api_key: str = ""
    alchemy_wss_url: str = ""
    alchemy_ws_url: str = ""
    enable_mempool_subscriber: bool = False
    mempool_backoff_max_seconds: int = 900
    mempool_rate_limit_backoff_seconds: int = 900
    enable_rpc_polling: bool = False
    etherscan_api_key: str = ""
    ethereum_rpc_url: str = "https://cloudflare-eth.com"
    ethereum_blocks_per_poll: int = 1
    ethereum_initial_lookback_blocks: int = 0
    ethereum_rpc_min_interval_seconds: float = 5.0
    ethereum_rpc_max_retries: int = 1
    ethereum_rpc_rate_limit_backoff_seconds: int = 3600
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gpt_daily_spend_alert_usd: float = 5.00
    ml_gate_threshold: int = 65
    ml_confidence_gate: int = 20
    enable_layer3_ml: bool = True
    layer3_model_dir: str = "models"
    layer3_escalation_threshold: float = 0.55
    layer4_enabled: bool = False
    layer4_llm_enabled: bool = False
    layer4_model: str = "gpt-4o-mini"
    layer4_timeout_seconds: float = 8.0
    layer4_max_tokens: int = 600
    layer4_cost_log_file: str = "logs/layer4_costs.jsonl"
    layer5_dedupe_window_s: int = 300
    layer5_confidence_gate: bool = True
    model_retrain_interval_days: int = 7
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    database_url: str = "postgresql://talosly:talosly_secret@localhost:5432/talosly"
    database_public_url: str = ""
    postgres_password: str = ""
    poll_interval_seconds: int = 3600
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
    protocol_flow_enabled: bool = False

    @computed_field
    @property
    def ethereum_ws_url(self) -> str:
        if self.alchemy_wss_url:
            return self.alchemy_wss_url
        if self.alchemy_ws_url:
            return self.alchemy_ws_url
        if self.alchemy_api_key:
            return f"wss://eth-mainnet.g.alchemy.com/v2/{self.alchemy_api_key}"
        return ""

    @computed_field
    @property
    def ethereum_http_url(self) -> str:
        if "${ALCHEMY_API_KEY}" in self.ethereum_rpc_url and self.alchemy_api_key:
            return self.ethereum_rpc_url.replace("${ALCHEMY_API_KEY}", self.alchemy_api_key)
        if self.ethereum_rpc_url == "https://cloudflare-eth.com" and self.alchemy_api_key:
            return f"https://eth-mainnet.g.alchemy.com/v2/{self.alchemy_api_key}"
        return self.ethereum_rpc_url

    @model_validator(mode="after")
    def validate_launch_settings(self):
        if self.app_env == "production" and len(self.admin_secret) < 32:
            raise ValueError("ADMIN_SECRET must be at least 32 characters in production")
        return self

    class Config:
        env_file = ".env"
        protected_namespaces = ("settings_",)


settings = Settings()
