from pydantic_settings import BaseSettings


class KYASettings(BaseSettings):
    enable_kya: bool = False
    kya_poll_interval_seconds: int = 3600
    kya_alert_threshold: int = 80
    kya_enable_mahalanobis: bool = True
    kya_enable_changepoint: bool = True
    kya_cusum_drift: float = 0.01
    kya_cusum_threshold: float = 0.25
    kya_w_base: float = 1.0
    kya_w_mahalanobis: float = 1.0
    kya_w_changepoint: float = 1.0
    kya_enable_conformal: bool = True
    kya_conformal_alpha: float = 0.05
    kya_conformal_window_size: int = 200
    kya_conformal_min_samples: int = 20
    kya_supported_chains: str = "ethereum,base"

    class Config:
        env_file = ".env"
        extra = "ignore"
        protected_namespaces = ("settings_",)


kya_settings = KYASettings()
