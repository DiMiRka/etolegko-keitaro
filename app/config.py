from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_user_agent: str = "etolegko-keitaro-wrapper/0.1"
    keitaro_timeout: float = 20.0
    keitaro_timezone: str = "Europe/Moscow"

    database_url: str = "sqlite+aiosqlite:///./app.db"

    campaign_prefix: str = "test_mironov_"
    keitaro_domain_id: int = 1813
    keitaro_group_id: int = 10332
    keitaro_traffic_source_id: int = 836
    geo_redirect_url: str = "https://google.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
