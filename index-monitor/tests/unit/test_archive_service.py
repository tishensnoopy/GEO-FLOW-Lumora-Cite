# index-monitor/tests/unit/test_archive_service.py
"""ArchiveService 测试（任务 9 补丁）。

覆盖 D01/D02/D06 修复：
- D01：client_id 不为 None（匹配 domain_map）；未匹配 domain 时跳过
- D02：content_keywords Text→JSON 转换（json.loads + 逗号分割回退）
- D06：查询条件用 action=="delete"（不是 status=="deleted"）

修复轮 1：
- 重要问题 1：D02 测试实际验证 JSON 解析路径（keywords='["kw1","kw2"]'）
- 重要问题 2：归档去重（NOT EXISTS 子查询）—— 通过重复调用验证不重复归档
- 重要问题 3：D01 跳过路径负向用例
"""
import pytest

# 裁定 3：简报测试代码用了 select 但未导入，这里补上
from sqlalchemy import select, delete

from app.services.archive_service import ArchiveService


@pytest.fixture(autouse=True, scope="module")
def ensure_geoflow_tables():
    """Module 级 autouse fixture：确保 GEOFlow public schema 表存在。

    ``tests/integration/test_cross_schema_join.py`` 和
    ``test_manual_distribution_endpoint.py`` 的 module fixture teardown
    会 DROP ``public.articles`` + ``public.article_distributions``。
    本 fixture 在模块开始时用 ``GeoflowBase.metadata.create_all`` 建表
    （IF NOT EXISTS 幂等），保证本模块测试可运行。

    参考 ``test_checker_geoflow_read.py`` 的同类处理。
    """
    from sqlalchemy import create_engine
    from app.core.config import settings
    from tests._geoflow_test_models import GeoflowBase

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
async def test_archive_deleted_distributions_matches_client_by_domain(db_session):
    """D01：归档前通过 domain_map 匹配 client_id，None 时跳过。

    D02：content_keywords 走 json.loads 路径（keywords 为 JSON 字符串）。
    """
    from app.models.client import Client, ClientSite
    from tests._geoflow_test_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.archived_distribution import ArchivedDistribution

    # 准备：client + site（domain 匹配）+ GEOFlow 删除记录
    client = Client(client_id="test_archive_d01", username="arch_d01",
                    password_hash="x", status="active")
    db_session.add(client)
    site = ClientSite(client_id="test_archive_d01", site_name="站",
                      domain="archive-d01.example.com", site_type="official", status="active")
    db_session.add(site)
    # D02 修复：keywords 设为 JSON 字符串，让 _parse_keywords 走 json.loads 路径
    article = GeoflowArticle(title="归档测试", slug="arch-d01", content="内容",
                             category_id=1, author_id=1, status="published",
                             keywords='["kw1","kw2"]')
    db_session.add(article)
    # 注：简报原测试在此处直接读 article.id，但 BigInteger 主键需 flush 后才填充。
    # 加 flush 是对简报测试 setup 的最小修复（不影响断言意图）。
    await db_session.flush()
    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="delete", status="synced",  # D06：action="delete" 是删除标记
        remote_url="https://www.archive-d01.example.com/deleted-page",
    )
    db_session.add(dist)
    await db_session.commit()

    try:
        service = ArchiveService(db_session)
        count = await service.archive_deleted_distributions()
        assert count >= 1

        # D01 验证：归档记录的 client_id 不为 None
        result = await db_session.execute(
            select(ArchivedDistribution).where(
                ArchivedDistribution.remote_url == "https://www.archive-d01.example.com/deleted-page"
            )
        )
        archived = result.scalar_one_or_none()
        assert archived is not None
        assert archived.client_id == "test_archive_d01"  # D01：不为 None
        # D02 验证：content_keywords 走 json.loads 路径，得到 list
        assert archived.content_keywords == ["kw1", "kw2"]

        # 去重验证（重要问题 2）：再次调用应跳过已归档的 remote_url
        count_second = await service.archive_deleted_distributions()
        assert count_second == 0
    finally:
        await db_session.execute(delete(ArchivedDistribution).where(
            ArchivedDistribution.remote_url == "https://www.archive-d01.example.com/deleted-page"
        ))
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_archive_parse_keywords_fallback_comma(db_session):
    """D02 回退路径：keywords 为逗号分割字符串时，_parse_keywords 走 except 分支。

    构造一个无法被 json.loads 解析的字符串（无方括号），验证回退到逗号分割。
    """
    from app.models.client import Client, ClientSite
    from tests._geoflow_test_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.archived_distribution import ArchivedDistribution

    client = Client(client_id="test_archive_d02_comma", username="arch_d02_comma",
                    password_hash="x", status="active")
    db_session.add(client)
    site = ClientSite(client_id="test_archive_d02_comma", site_name="站",
                      domain="archive-d02-comma.example.com", site_type="official", status="active")
    db_session.add(site)
    # keywords 是逗号分割字符串（非 JSON），json.loads 会抛 JSONDecodeError，
    # 走 except 分支回退到 split(",") + strip
    article = GeoflowArticle(title="归档测试-逗号", slug="arch-d02-comma", content="内容",
                             category_id=1, author_id=1, status="published",
                             keywords="kw1, kw2")
    db_session.add(article)
    await db_session.flush()
    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="delete", status="synced",
        remote_url="https://www.archive-d02-comma.example.com/deleted-page",
    )
    db_session.add(dist)
    await db_session.commit()

    try:
        service = ArchiveService(db_session)
        count = await service.archive_deleted_distributions()
        assert count >= 1

        result = await db_session.execute(
            select(ArchivedDistribution).where(
                ArchivedDistribution.remote_url == "https://www.archive-d02-comma.example.com/deleted-page"
            )
        )
        archived = result.scalar_one_or_none()
        assert archived is not None
        # D02 回退路径：逗号分割后 strip 空格
        assert archived.content_keywords == ["kw1", "kw2"]
    finally:
        await db_session.execute(delete(ArchivedDistribution).where(
            ArchivedDistribution.remote_url == "https://www.archive-d02-comma.example.com/deleted-page"
        ))
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_archive_skips_unmatched_domain(db_session):
    """D01 负向用例：remote_url 的 domain 未登记任何 ClientSite 时跳过。

    断言：
    - count == 0
    - ArchivedDistribution 表中不存在该 remote_url 的记录
    """
    from app.models.client import Client, ClientSite
    from tests._geoflow_test_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.archived_distribution import ArchivedDistribution

    # 准备：client + site（domain="matched.example.com"），但 dist 的 URL
    # 用 "unmatched.example.com"——domain 不匹配任何 ClientSite
    client = Client(client_id="test_archive_d01_skip", username="arch_d01_skip",
                    password_hash="x", status="active")
    db_session.add(client)
    site = ClientSite(client_id="test_archive_d01_skip", site_name="站",
                      domain="matched.example.com", site_type="official", status="active")
    db_session.add(site)
    article = GeoflowArticle(title="归档测试-跳过", slug="arch-d01-skip", content="内容",
                             category_id=1, author_id=1, status="published",
                             keywords='["kw1","kw2"]')
    db_session.add(article)
    await db_session.flush()
    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="delete", status="synced",
        remote_url="https://unmatched.example.com/page",
    )
    db_session.add(dist)
    await db_session.commit()

    try:
        service = ArchiveService(db_session)
        count = await service.archive_deleted_distributions()
        # D01 负向：未匹配 domain，跳过，count == 0
        assert count == 0

        # D01 负向：ArchivedDistribution 表中不存在该 remote_url
        result = await db_session.execute(
            select(ArchivedDistribution).where(
                ArchivedDistribution.remote_url == "https://unmatched.example.com/page"
            )
        )
        archived = result.scalar_one_or_none()
        assert archived is None
    finally:
        await db_session.execute(delete(ArchivedDistribution).where(
            ArchivedDistribution.remote_url == "https://unmatched.example.com/page"
        ))
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()
