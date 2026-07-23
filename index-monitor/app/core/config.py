# index-monitor/app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "Index Monitor Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "geo_monitoring"
    POSTGRES_USER: str = "geo_user"
    POSTGRES_PASSWORD: str = "GeoLocal2026"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "RedisLocal2026"

    SECRET_KEY: str = "local-jwt-secret-key-for-testing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    SPIDER_CONCURRENT: int = 3
    SPIDER_INTERVAL_MIN: int = 2
    SPIDER_INTERVAL_MAX: int = 5

    API_5118_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
