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
from pydantic import model_validator
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
    # DB 层权限隔离（改进 2）                                             #
    # ------------------------------------------------------------------ #
    # 可选：启用后应用改用专用 monitor_user 连接 PG（对 public 只读、对
    # monitor 读写），DB 层强制隔离防误写 GEOFlow 数据。
    # - 未设（默认）→ 继续用 POSTGRES_USER（geo_user），向后兼容；
    # - 设 MONITOR_DB_USER → 下方 _apply_monitor_db_user validator 重建
    #   DATABASE_URL 使用 monitor_user 凭据（host/port/db 仍取自 POSTGRES_*）。
    # 密码未设时回退 POSTGRES_PASSWORD（便利场景）。
    # 角色 + 权限由 deploy/scripts/setup-db-roles.sh 创建。
    MONITOR_DB_USER: Optional[str] = None
    MONITOR_DB_PASSWORD: Optional[str] = None

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
    # - SSO_GEOFLOW_BASE_URL：GEOFlow 站点根 URL（authorize + userinfo 共用）。
    # - SSO_GEOFLOW_USERINFO_URL：从 BASE_URL 派生，避免两处硬编码 URL 不一致
    #   （Task 4 审查建议：原实现把 BASE_URL 和 USERINFO_URL 都硬编码，BASE_URL
    #    改了之后 USERINFO_URL 不会自动跟随）。env 仍可显式覆盖 USERINFO_URL。
    SSO_GEOFLOW_BASE_URL: str = "https://zkeeeai.com"
    SSO_GEOFLOW_USERINFO_URL: Optional[str] = None
    SSO_REDIRECT_URI: str = "https://monitor.zkeeeai.com/sso/callback"
    SSO_JWT_SECRET: str = "change-me-in-prod"
    SSO_JWT_EXPIRE_DAYS: int = 7

    # ------------------------------------------------------------------ #
    # 检测频率控制（设计文档第 21.1 节）                                  #
    # ------------------------------------------------------------------ #
    SCAN_MIN_INTERVAL_HOURS: int = 6
    SCAN_MAX_CONCURRENCY: int = 5
    SCAN_REQUEST_DELAY_MIN: int = 2
    SCAN_REQUEST_DELAY_MAX: int = 5
    SCAN_TIMEOUT_SECONDS: int = 30
    SCAN_DAILY_QUOTA_PER_CLIENT: int = 100

    @model_validator(mode="after")
    def _derive_sso_userinfo_url(self) -> "Settings":
        """如果 USERINFO_URL 未显式注入，则从 BASE_URL 派生。

        - BASE_URL 末尾斜杠会被规整掉，避免 ``https://x//api`` 这种重复斜杠；
        - 若 env 显式设置了 SSO_GEOFLOW_USERINFO_URL，则尊重该值（向后兼容
          旧部署 / 内网代理场景）。
        """
        if not self.SSO_GEOFLOW_USERINFO_URL:
            base = self.SSO_GEOFLOW_BASE_URL.rstrip("/")
            object.__setattr__(self, "SSO_GEOFLOW_USERINFO_URL", f"{base}/api/sso/userinfo")
        return self

    @model_validator(mode="after")
    def _apply_monitor_db_user(self) -> "Settings":
        """启用 DB 层权限隔离时，重建 DATABASE_URL 使用 monitor_user 凭据。

        - ``MONITOR_DB_USER`` 为空（默认）→ 不动 ``DATABASE_URL``，继续用
          ``POSTGRES_USER``（geo_user），向后兼容；
        - ``MONITOR_DB_USER`` 非空 → 用 monitor_user + 密码重建 URL，host/port/db
          仍取自 ``POSTGRES_*``。密码未设时回退 ``POSTGRES_PASSWORD``。

        设计要点：
        1. ``MONITOR_DB_USER`` 是启用 DB 层隔离的开关——设了就覆盖默认 URL，
           确保操作者明确选择隔离用户（不会与 geo_user 默认 URL 冲突）；
        2. 用 ``object.__setattr__`` 在 validator 中派生字段值（与
           ``_derive_sso_userinfo_url`` 同模式——pydantic v2 推荐的 after
           validator 修改字段方式，避免触发重新验证）；
        3. host/port/db 沿用 ``POSTGRES_*`` 而非从原 DATABASE_URL 解析，避免
           URL 解析复杂度，且与 docker-compose 注入的 POSTGRES_* 一致。
        """
        if self.MONITOR_DB_USER:
            password = self.MONITOR_DB_PASSWORD or self.POSTGRES_PASSWORD
            object.__setattr__(self, "DATABASE_URL", (
                f"postgresql+asyncpg://{self.MONITOR_DB_USER}:{password}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            ))
        return self

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
