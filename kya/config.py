from pydantic_settings import BaseSettings


class KYASettings(BaseSettings):
    enable_kya: bool = False
    kya_poll_interval_seconds: int = 3600
    kya_alert_threshold: int = 80

    class Config:
        env_file = ".env"
        extra = "ignore"
        protected_namespaces = ("settings_",)


kya_settings = KYASettings()
