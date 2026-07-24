# index-monitor/app/core/config.py
"""
监测系统配置——Task 4 起连接 GEOFlow 的 PG（monitor schema）。

设计要点
========

1. ``DATABASE_URL`` 是应用层连接 PG 的单一事实来源，默认指向 GEOFlow PG
   （容器名 ``geoflow-postgres``，库 ``geo_flow``）。生产部署可通过环境变量
   ``DATABASE_URL`` 覆盖，但默认值必须指向 GEOFlow PG，避免误连旧的
   ``postgres:15-alpine`` 独立容器。

2. ``POSTGRES_*`` 字段保留用于：
   - docker-compose.local.yml 通过 ``POSTGRES_HOST=postgres`` 等环境变量
     把测试流量导向本地 PG 容器（``geo-postgres-local``）。
   - conftest.py 的 ``db_session`` fixture 和 alembic/env.py 仍从
     ``POSTGRES_*`` 构造连接 URL，保证测试环境与生产环境解耦。

3. SSO 配置项（``SSO_GEOFLOW_BASE_URL`` 等）在本任务预先加入，后续 SSO
   认证任务可直接引用，避免届时再改 config.py。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "知氪AI全链路监测平台"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ------------------------------------------------------------------ #
    # 数据库配置                                                          #
    # ------------------------------------------------------------------ #
    # POSTGRES_* 默认值改为 GEOFlow PG，生产可被环境变量覆盖。
    # 本地开发通过 docker-compose.local.yml 注入 POSTGRES_HOST=postgres 等
    # 把连接重定向到 geo-postgres-local 容器。
    POSTGRES_HOST: str = "geoflow-postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "geo_flow"
    POSTGRES_USER: str = "geo_user"
    POSTGRES_PASSWORD: str = "geo_password"

    # 应用层实际使用的 DATABASE_URL——database.py 直接消费此值。
    # 默认指向 GEOFlow PG，确保生产开箱即用；环境变量 DATABASE_URL 可覆盖。
    # 使用 asyncpg 驱动以兼容 SQLAlchemy 2.0 async engine。
    DATABASE_URL: str = (
        "postgresql+asyncpg://geo_user:geo_password@geoflow-postgres:5432/geo_flow"
    )

    # ------------------------------------------------------------------ #
    # Redis 配置                                                          #
    # ------------------------------------------------------------------ #
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "RedisLocal2026"

    # ------------------------------------------------------------------ #
    # JWT / 应用安全                                                      #
    # ------------------------------------------------------------------ #
    SECRET_KEY: str = "local-jwt-secret-key-for-testing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ------------------------------------------------------------------ #
    # 爬虫调度                                                            #
    # ------------------------------------------------------------------ #
    SPIDER_CONCURRENT: int = 3
    SPIDER_INTERVAL_MIN: int = 2
    SPIDER_INTERVAL_MAX: int = 5

    API_5118_KEY: Optional[str] = None

    # ------------------------------------------------------------------ #
    # SSO 配置（与 GEOFlow 单点登录集成）                                  #
    # ------------------------------------------------------------------ #
    # 后续 SSO 任务会消费这些字段；本任务预先加入，避免届时再改 config.py。
    SSO_GEOFLOW_BASE_URL: str = "https://zkeeeai.com"
    SSO_GEOFLOW_USERINFO_URL: str = "https://zkeeeai.com/api/sso/userinfo"
    SSO_REDIRECT_URI: str = "https://monitor.zkeeeai.com/sso/callback"
    SSO_JWT_SECRET: str = "change-me-in-prod"
    SSO_JWT_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
