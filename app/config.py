from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    ebay_env: str = "production"
    ebay_client_id: str
    ebay_client_secret: str
    ebay_ru_name: str
    ebay_oauth_redirect_uri: str
    ebay_trading_site_id: int = 71
    ebay_trading_compatibility_level: int = 1413
    ebay_marketplace_id: str = "EBAY_FR"

    # Protege /oauth/login (HTTP Basic) et signe le parametre state.
    admin_password: str = Field(min_length=16)

    alerting_backend: str = "log"  # "log" ou "email"
    smtp_host: str = ""
    smtp_port: int = 587  # 587 = STARTTLS, 465 = TLS implicite
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    alert_email_from: str = ""
    alert_email_to: str = ""

    app_timezone: str = "Europe/Paris"

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_alerting(self) -> "Settings":
        if self.alerting_backend not in ("log", "email"):
            raise ValueError("ALERTING_BACKEND doit valoir 'log' ou 'email'")
        if self.alerting_backend == "email":
            required = ("smtp_host", "alert_email_from", "alert_email_to")
            missing = [name.upper() for name in required if not getattr(self, name)]
            if missing:
                raise ValueError(f"ALERTING_BACKEND=email : variables manquantes {missing}")
        return self

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def ebay_api_base(self) -> str:
        return (
            "https://api.ebay.com"
            if self.ebay_env == "production"
            else "https://api.sandbox.ebay.com"
        )

    @property
    def ebay_auth_base(self) -> str:
        return (
            "https://auth.ebay.com"
            if self.ebay_env == "production"
            else "https://auth.sandbox.ebay.com"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
