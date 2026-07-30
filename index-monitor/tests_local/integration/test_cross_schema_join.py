"""Task 5：跨 schema JOIN 查询测试。

验证目标
========

1. 监测系统能跨 ``public``（GEOFlow）与 ``monitor``（监测系统）schema 进行 JOIN 查询。
2. ``public.articles.keywords`` 字段（``TEXT`` 类型，任务 3 已确认）能正确存储与读取
   JSON 格式字符串，由应用层解析。
3. 跨 schema JOIN 在无匹配数据时也能正常执行（不报错）。

设计说明
========

- 监测 PG 容器（``geo-postgres-local``）的 ``public`` schema 没有 GEOFlow 真实表
  （只有 ``alembic_version``）。本模块用 module 级 sync fixture 创建与 GEOFlow
  迁移结构等价的 mock 表（``public.articles``、``public.article_distributions``），
  模块结束时 DROP 清理。
- 每个 test 在独立事务中运行，结束时 rollback，DDL 在 module fixture 中已 COMMIT，
  不会被回滚；DML 全部回滚，避免污染数据库。
- 简报中 ``from app.models.client_site import ClientSite`` 实际不存在——``ClientSite``
  定义在 ``app.models.client`` 模块中，这里按实际路径导入。
- 简报假设 ``keywords`` 是 JSON 字段，但任务 3 已确认其为 ``TEXT``——存 JSON 格式
  字符串、应用层 ``json.loads`` 解析。``test_keywords_*`` 用例据此调整。
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.client import ClientSite
from tests._geoflow_test_models import (
    GeoflowArticle,
    GeoflowArticleDistribution,
)


# --------------------------------------------------------------------------- #
# Mock 表 DDL：与 GEOFlow migration 字段对齐                                  #
# --------------------------------------------------------------------------- #
_CREATE_ARTICLES_SQL = """
CREATE TABLE IF NOT EXISTS public.articles (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL UNIQUE,
    excerpt TEXT DEFAULT '',
    content TEXT NOT NULL,
    category_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    task_id BIGINT,
    original_keyword VARCHAR(200) DEFAULT '',
    keywords TEXT DEFAULT '',
    meta_description TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'draft',
    review_status VARCHAR(20) DEFAULT 'pending',
    view_count INTEGER DEFAULT 0,
    is_ai_generated INTEGER DEFAULT 0,
    is_hot BOOLEAN DEFAULT FALSE,
    is_featured BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
)
"""

_CREATE_ARTICLE_DISTRIBUTIONS_SQL = """
CREATE TABLE IF NOT EXISTS public.article_distributions (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT NOT NULL,
    distribution_channel_id BIGINT NOT NULL,
    action VARCHAR(30) DEFAULT 'publish',
    status VARCHAR(30) DEFAULT 'queued',
    remote_id VARCHAR(120),
    remote_url VARCHAR(500),
    remote_meta JSON,
    idempotency_key VARCHAR(120) UNIQUE,
    attempt_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_error_message TEXT,
    payload_hash VARCHAR(64),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
"""

_DROP_ARTICLE_DISTRIBUTIONS_SQL = "DROP TABLE IF EXISTS public.article_distributions"
_DROP_ARTICLES_SQL = "DROP TABLE IF EXISTS public.articles"


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def geoflow_mock_tables():
    """Module 级 sync fixture：在 public schema 创建 GEOFlow mock 表，结束 DROP。

    用 ``psycopg2`` 同步连接（独立于 asyncio 事件循环），避免 strict 模式下
    模块级 async fixture 与 per-test 事件循环冲突。DDL 用 ``autocommit`` 提交，
    不会被 per-test 事务回滚影响。
    """
    import psycopg2

    conn = psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_ARTICLES_SQL)
            cur.execute(_CREATE_ARTICLE_DISTRIBUTIONS_SQL)
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(_DROP_ARTICLE_DISTRIBUTIONS_SQL)
            cur.execute(_DROP_ARTICLES_SQL)
        conn.close()


@pytest_asyncio.fixture
async def db_session(geoflow_mock_tables):
    """Per-test async fixture：在事务中运行，测试结束 rollback。

    覆盖 ``tests/conftest.py::db_session``，为本模块提供事务隔离。每个 test 在
    独立事务中执行 DML，结束统一 rollback，避免污染数据库。
    """
    url = (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                    yield session
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cross_schema_join_geoflow_and_monitor(db_session):
    """验证可跨 schema JOIN 查询 GEOFlow 与 monitor 的表。

    场景：插入 1 篇 article + 1 条 article_distribution（status='synced'）
    + 1 条 monitor.client_sites，跨 schema JOIN 应至少返回 1 行。
    """
    # 插入 GEOFlow 侧测试数据（public schema）
    await db_session.execute(
        text(
            "INSERT INTO public.articles "
            "(title, slug, content, category_id, author_id, status) "
            "VALUES ('测试文章', 'test-article', '内容', 1, 1, 'published') "
            "ON CONFLICT (slug) DO NOTHING"
        )
    )
    article_row = (
        await db_session.execute(
            text("SELECT id FROM public.articles WHERE slug = 'test-article'")
        )
    ).scalar_one()

    await db_session.execute(
        text(
            "INSERT INTO public.article_distributions "
            "(article_id, distribution_channel_id, action, status) "
            "VALUES (:aid, 1, 'publish', 'synced')"
        ),
        {"aid": article_row},
    )

    # 插入监测系统侧测试数据（monitor schema）
    await db_session.execute(
        text(
            "INSERT INTO monitor.client_sites "
            "(client_id, domain, site_name, site_type) "
            "VALUES ('test-client', 'example.com', '测试站点', 'official') "
            "ON CONFLICT DO NOTHING"
        )
    )

    await db_session.flush()

    # 跨 schema JOIN 查询：public.article_distributions ⨝ public.articles
    # ⨝ monitor.client_sites（LEFT JOIN，按 domain 匹配）
    result = await db_session.execute(
        select(GeoflowArticleDistribution, GeoflowArticle, ClientSite)
        .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
        .outerjoin(ClientSite, ClientSite.domain == "example.com")
        .where(GeoflowArticleDistribution.status == "synced")
    )
    rows = result.all()

    # 验证查询不报错且返回预期数据
    assert isinstance(rows, list)
    assert len(rows) >= 1, "跨 schema JOIN 应至少返回 1 行（已插入测试数据）"

    # 验证三个 schema 的实体都能正确 materialize
    dist, article, site = rows[0]
    assert isinstance(dist, GeoflowArticleDistribution)
    assert isinstance(article, GeoflowArticle)
    assert isinstance(site, ClientSite)
    assert article.slug == "test-article"
    assert dist.status == "synced"
    assert site.domain == "example.com"


@pytest.mark.asyncio
async def test_keywords_text_field_holds_json_string(db_session):
    """验证 ``keywords`` TEXT 字段能存 JSON 格式字符串并由应用层解析为数组。

    任务 3 已确认 ``articles.keywords`` 是 ``TEXT``（不是 JSON）。本用例验证：
    1. 可写入 JSON 格式字符串；
    2. ORM 读出为 ``str``；
    3. 应用层 ``json.loads`` 能解析为 ``list``。
    """
    await db_session.execute(
        text(
            "INSERT INTO public.articles "
            "(title, slug, content, category_id, author_id, keywords) "
            "VALUES ('测试 keywords', 'test-keywords', '内容', 1, 1, :kw) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"kw": '["关键词1", "关键词2"]'},
    )

    result = await db_session.execute(
        select(GeoflowArticle).where(GeoflowArticle.slug == "test-keywords")
    )
    article = result.scalar_one_or_none()
    assert article is not None, "应能查到刚插入的 article"

    # keywords 在模型中映射为 TEXT，读出应为 str
    keywords = article.keywords
    assert isinstance(keywords, str), f"keywords 应为 TEXT/str，实际: {type(keywords).__name__}"

    # 应用层解析为 list
    parsed = json.loads(keywords)
    assert isinstance(parsed, list)
    assert parsed == ["关键词1", "关键词2"]


@pytest.mark.asyncio
async def test_cross_schema_join_empty_result(db_session):
    """验证跨 schema JOIN 在无匹配数据时也能正常执行（不报错）。

    无任何 article_distributions.status='synced' 的数据时，JOIN 应返回空列表。
    """
    result = await db_session.execute(
        select(GeoflowArticleDistribution, GeoflowArticle, ClientSite)
        .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
        .outerjoin(ClientSite, ClientSite.domain == "nonexistent.example")
        .where(GeoflowArticleDistribution.status == "synced")
    )
    rows = result.all()

    assert isinstance(rows, list)
    assert rows == [], "无匹配数据时 JOIN 应返回空列表"


@pytest.mark.asyncio
async def test_cross_schema_join_monitor_to_geoflow(db_session):
    """验证反向 JOIN：monitor.client_sites ⨝ public.articles（无外键关系，仅 domain 关联）。

    实际业务中 GEOFlow 的 ``distribution_channels.domain`` 与监测系统的
    ``client_sites.domain`` 可对应。这里直接验证跨 schema SQL 执行无障碍。
    """
    await db_session.execute(
        text(
            "INSERT INTO public.articles "
            "(title, slug, content, category_id, author_id) "
            "VALUES ('反向 JOIN 测试', 'reverse-join', '内容', 1, 1) "
            "ON CONFLICT (slug) DO NOTHING"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO monitor.client_sites "
            "(client_id, domain, site_name, site_type) "
            "VALUES ('reverse-client', 'reverse.example', '反向站点', 'official') "
            "ON CONFLICT DO NOTHING"
        )
    )
    await db_session.flush()

    # 用原生 SQL 验证跨 schema JOIN（绕过 ORM 关系定义）
    result = await db_session.execute(
        text(
            "SELECT a.slug, cs.domain "
            "FROM public.articles a "
            "LEFT JOIN monitor.client_sites cs ON cs.client_id = 'reverse-client' "
            "WHERE a.slug = 'reverse-join'"
        )
    )
    rows = result.all()

    assert len(rows) == 1
    slug, domain = rows[0]
    assert slug == "reverse-join"
    assert domain == "reverse.example"
