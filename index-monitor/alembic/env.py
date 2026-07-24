"""Alembic 运行环境配置。

监测系统使用 monitor schema（GEOFlow 使用 public schema）。
为保持与 app.core.database 一致的连接配置，URL 从 app.core.config.settings 构造。

本 env.py 使用同步 driver（psycopg2），因为 DDL 迁移（CREATE SCHEMA 等）
不需要异步；同步 engine 更便于 alembic 标准流程。
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 加载应用配置（环境变量优先于 .env）
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 同步 URL：postgresql+psycopg2://user:pass@host:port/db
SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)

# 监测系统的元数据——后续迁移若需要 autogenerate，可从这里取
# 当前 task 1 仅创建 schema，不涉及表结构 autogenerate。
try:
    from app.models.base import Base  # noqa: F401
    target_metadata = Base.metadata
except Exception:  # pragma: no cover - 仅在 models 未就绪时降级
    target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
