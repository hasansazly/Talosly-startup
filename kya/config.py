from pydantic_settings import BaseSettings


class KYASettings(BaseSettings):
    enable_kya: bool = False
    kya_poll_interval_seconds: int = 3600
    kya_alert_threshold: int = 80
    kya_enable_changepoint: bool = False
    kya_cusum_drift: float = 0.01
    kya_cusum_threshold: float = 0.25

    class Config:
        env_file = ".env"
        extra = "ignore"
        protected_namespaces = ("settings_",)


kya_settings = KYASettings()
