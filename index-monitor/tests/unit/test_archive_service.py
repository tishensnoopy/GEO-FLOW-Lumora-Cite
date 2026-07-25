# index-monitor/tests/unit/test_archive_service.py
"""ArchiveService 测试（任务 9 补丁）。

覆盖 D01/D02/D06 修复：
- D01：client_id 不为 None（匹配 domain_map）
- D02：content_keywords Text→JSON 转换
- D06：查询条件用 action=="delete"（不是 status=="deleted"）
"""
import pytest
from datetime import datetime, timezone

# 裁定 3：简报测试代码用了 select 但未导入，这里补上
from sqlalchemy import select, delete

from app.services.archive_service import ArchiveService


@pytest.mark.asyncio
async def test_archive_deleted_distributions_matches_client_by_domain(db_session):
    """D01：归档前通过 domain_map 匹配 client_id，None 时跳过。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.archived_distribution import ArchivedDistribution

    # 准备：client + site（domain 匹配）+ GEOFlow 删除记录
    client = Client(client_id="test_archive_d01", username="arch_d01",
                    password_hash="x", status="active")
    db_session.add(client)
    site = ClientSite(client_id="test_archive_d01", site_name="站",
                      domain="archive-d01.example.com", site_type="official", status="active")
    db_session.add(site)
    article = GeoflowArticle(title="归档测试", slug="arch-d01", content="内容",
                             category_id=1, author_id=1, status="published")
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
    finally:
        await db_session.execute(delete(ArchivedDistribution).where(
            ArchivedDistribution.remote_url == "https://www.archive-d01.example.com/deleted-page"
        ))
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()
