"""IndexChecker/CitationChecker 改造测试：读 GEOFlow + 手动表。

设计文档第 7.2 节。
"""
import pytest

from app.services.index_checker import IndexChecker


@pytest.fixture(autouse=True, scope="module")
def ensure_geoflow_tables():
    """Module 级 autouse fixture：确保 GEOFlow public schema 表存在。

    测试 DB（geo_monitoring）public schema 默认无 GEOFlow 真实表，
    且 ``tests/integration/test_cross_schema_join.py`` 的 module fixture
    teardown 会 DROP ``public.articles`` + ``public.article_distributions``。
    本 fixture 在模块开始时用 ``GeoflowBase.metadata.create_all`` 建表
    （IF NOT EXISTS 幂等），保证本模块测试可运行。

    用 sync engine（psycopg2）避免 strict asyncio 模式下 module 级
    async fixture 与 per-test 事件循环冲突（参考 test_cross_schema_join.py
    的同类处理）。
    """
    from sqlalchemy import create_engine
    from app.core.config import settings
    from app.models.geoflow_models import GeoflowBase

    url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(url)
    try:
        GeoflowBase.metadata.create_all(engine)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_get_pending_urls_reads_geoflow_and_manual(db_session):
    """get_pending_urls 合并 GEOFlow 分发 + 手动录入的 URL。"""
    checker = IndexChecker(db_session)
    pending = await checker.get_pending_urls()

    # 返回格式：[(url, client_id), ...]
    assert isinstance(pending, list)
    for item in pending:
        assert len(item) == 2  # (url, client_id)


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_already_checked(db_session):
    """已检测的 URL 不在 pending 列表中。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.index_result import IndexResult

    # 插入 GEOFlow 分发记录
    article = GeoflowArticle(title="已检测", slug="checked", content="x", category_id=1, author_id=1, status="published")
    db_session.add(article)
    await db_session.flush()

    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="publish", status="synced",
        remote_url="https://checked-example.com/test",
    )
    db_session.add(dist)
    await db_session.flush()

    # 插入 client_site（domain 匹配）
    client = Client(client_id="checker_test", username="checker", password_hash="x", status="active")
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(client_id="checker_test", site_name="站", domain="checked-example.com", site_type="official", status="active")
    db_session.add(site)
    await db_session.flush()

    # 插入已检测的 index_result
    ir = IndexResult(url="https://checked-example.com/test", client_id="checker_test", site_type="official", baidu_status="indexed")
    db_session.add(ir)
    await db_session.commit()

    checker = IndexChecker(db_session)
    pending = await checker.get_pending_urls()
    pending_urls = [u for u, _ in pending]
    assert "https://checked-example.com/test" not in pending_urls

    # 清理
    await db_session.delete(ir)
    await db_session.delete(dist)
    await db_session.delete(article)
    await db_session.delete(site)
    await db_session.delete(client)
    await db_session.commit()
