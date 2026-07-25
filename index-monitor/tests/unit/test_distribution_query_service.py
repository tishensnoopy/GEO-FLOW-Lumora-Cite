# index-monitor/tests/unit/test_distribution_query_service.py
"""DistributionQueryService 测试。

跨 schema JOIN 查询 GEOFlow 分发记录 + 手动录入记录。
设计文档第 7 节。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.distribution_query import DistributionQueryService


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
async def test_query_geoflow_distributions_returns_empty_when_no_data(db_session):
    """无分发记录时返回空列表。"""
    service = DistributionQueryService(db_session)
    result = await service._query_geoflow_distributions(client_id=None)
    assert result == []


@pytest.mark.asyncio
async def test_query_geoflow_distributions_filters_by_client(db_session):
    """按 client_id 过滤（通过 domain 匹配 client_sites）。"""
    # 前置：插入 client_sites + geoflow article_distributions
    # 这里用真实 DB（db_session fixture），需先插入测试数据
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import (
        GeoflowArticle, GeoflowArticleDistribution, GeoflowDistributionChannel
    )

    # 插入 client + site
    client = Client(
        client_id="test_client_m2", username="test_m2",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()

    site = ClientSite(
        client_id="test_client_m2", site_name="测试站",
        domain="m2-task2.example.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.flush()

    # 插入 GEOFlow 文章 + 分发记录（public schema）
    article = GeoflowArticle(
        title="测试文章", slug="test-article", content="内容",
        category_id=1, author_id=1, status="published",
    )
    db_session.add(article)
    await db_session.flush()

    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="publish", status="synced",
        remote_url="https://www.m2-task2.example.com/test-article",
    )
    db_session.add(dist)
    await db_session.commit()

    try:
        service = DistributionQueryService(db_session)
        result = await service._query_geoflow_distributions(client_id="test_client_m2")
        assert len(result) == 1
        assert result[0]["source"] == "geoflow"
        assert result[0]["client_id"] == "test_client_m2"
        assert result[0]["content_title"] == "测试文章"
    finally:
        # 裁定 1：即使断言失败也要清理，避免污染 DB
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_query_geoflow_skips_deleted_action(db_session):
    """action='delete' 的分发记录不返回。"""
    service = DistributionQueryService(db_session)
    # 如果有 delete 记录，应被过滤
    result = await service._query_geoflow_distributions(client_id=None)
    for record in result:
        assert record.get("action") != "delete"


@pytest.mark.asyncio
async def test_list_distributions_merges_geoflow_and_manual(db_session):
    """list_distributions 合并 GEOFlow + 手动录入，按时间降序。"""
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution

    # 插入测试数据
    client = Client(client_id="test_merge", username="merge", password_hash="x", status="active")
    db_session.add(client)
    await db_session.flush()

    site = ClientSite(client_id="test_merge", site_name="站", domain="merge.com", site_type="official", status="active")
    db_session.add(site)
    await db_session.flush()

    manual = ManualDistribution(client_id="test_merge", remote_url="https://merge.com/manual", status="synced")
    db_session.add(manual)
    await db_session.commit()

    try:
        service = DistributionQueryService(db_session)
        result = await service.list_distributions(client_id="test_merge")
        # 至少有 1 条手动记录
        manual_records = [r for r in result if r["source"] == "manual"]
        assert len(manual_records) >= 1
        assert manual_records[0]["remote_url"] == "https://merge.com/manual"
    finally:
        # 清理（用 try/finally 包裹，确保断言失败也能清理，避免污染 DB）
        await db_session.delete(manual)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_list_distributions_filters_by_source(db_session):
    """source='manual' 只返回手动记录。

    先插入 client + client_site + 一条 manual 记录，确保结果非空
    （避免空列表 vacuous pass），再断言所有记录 source == 'manual'。
    """
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution

    client = Client(
        client_id="test_source_filter", username="source_filter",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()

    site = ClientSite(
        client_id="test_source_filter", site_name="源过滤测试站",
        domain="source-filter.example.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.flush()

    manual = ManualDistribution(
        client_id="test_source_filter",
        remote_url="https://source-filter.example.com/manual",
        status="synced",
    )
    db_session.add(manual)
    await db_session.commit()

    try:
        service = DistributionQueryService(db_session)
        result = await service.list_distributions(source="manual")
        # 必须有数据可验证，避免空列表 vacuous pass
        assert len(result) >= 1
        # 所有返回记录都必须是 manual 源
        for r in result:
            assert r["source"] == "manual"
    finally:
        # 清理（try/finally 确保断言失败也能清理，避免污染 DB）
        await db_session.delete(manual)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_manual_distribution_success(db_session):
    """手动录入 URL 成功（client_id 显式指定）。"""
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import select

    client = Client(
        client_id="test_manual_create", username="mc",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(
        client_id="test_manual_create", site_name="站",
        domain="manual-create.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    try:
        result = await service.create_manual_distribution(
            remote_url="https://www.manual-create.com/article/1",
            admin_user_id=1,
            admin_name="测试管理员",
            client_id="test_manual_create",
            note="测试录入",
        )
        assert result["action"] == "created"
        assert result["source"] == "manual"
    finally:
        # 清理（含被新建的 manual 记录；scalar_one_or_none 避免断言失败时
        # 还未写入记录导致 cleanup 二次抛错）
        md_result = await db_session.execute(
            select(ManualDistribution).where(
                ManualDistribution.remote_url == "https://www.manual-create.com/article/1"
            )
        )
        md = md_result.scalar_one_or_none()
        if md is not None:
            await db_session.delete(md)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_manual_duplicate_url_raises_409(db_session):
    """重复录入同一 URL 返回 409。"""
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution
    from fastapi import HTTPException

    client = Client(
        client_id="test_dup", username="dup",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(
        client_id="test_dup", site_name="站",
        domain="dup.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.flush()
    existing = ManualDistribution(
        client_id="test_dup",
        remote_url="https://dup.com/existing",
        status="synced",
    )
    db_session.add(existing)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    try:
        with pytest.raises(HTTPException) as exc:
            await service.create_manual_distribution(
                remote_url="https://dup.com/existing",
                admin_user_id=1, admin_name="admin",
                client_id="test_dup",
            )
        assert exc.value.status_code == 409
    finally:
        # 清理（断言失败时仍执行）
        await db_session.delete(existing)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_manual_distribution_auto_match_by_domain(db_session):
    """client_id=None 时通过 domain 自动匹配 client_sites。

    覆盖 _match_client_by_domain 路径（核心需求）：
    URL 的 domain 命中 active client_sites 时自动取 client_id。
    """
    from app.models.client import Client, ClientSite
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import select

    client = Client(
        client_id="test_auto_match", username="auto_match",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(
        client_id="test_auto_match", site_name="自动匹配测试站",
        domain="auto-match.example.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    try:
        # 不传 client_id，触发 domain 自动匹配
        result = await service.create_manual_distribution(
            remote_url="https://www.auto-match.example.com/post/1",
            admin_user_id=1,
            admin_name="admin",
            client_id=None,
            note="auto",
        )
        assert result["action"] == "created"
        assert result["client_id"] == "test_auto_match"
        assert result["source"] == "manual"
    finally:
        # 清理：删 ManualDistribution（若写入）→ site → client
        md_result = await db_session.execute(
            select(ManualDistribution).where(
                ManualDistribution.remote_url == "https://www.auto-match.example.com/post/1"
            )
        )
        md = md_result.scalar_one_or_none()
        if md is not None:
            await db_session.delete(md)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_manual_distribution_unknown_domain_raises_400(db_session):
    """client_id=None 且 URL 的 domain 未登记返回 400。

    覆盖 _match_client_by_domain 抛 HTTPException(400) 路径。
    """
    from app.models.client import Client, ClientSite
    from fastapi import HTTPException

    client = Client(
        client_id="test_unknown_domain", username="unknown_domain",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(
        client_id="test_unknown_domain", site_name="已登记域名站",
        domain="known.example.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    try:
        # URL 的 domain 未登记 → 400
        with pytest.raises(HTTPException) as exc:
            await service.create_manual_distribution(
                remote_url="https://www.unknown-domain.example.com/post",
                admin_user_id=1,
                admin_name="admin",
                client_id=None,
            )
        assert exc.value.status_code == 400
        assert "未在客户站点中登记" in exc.value.detail
    finally:
        # 清理：无 ManualDistribution 写入；仅删 site + client
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_manual_duplicate_url_in_geoflow_raises_409(db_session):
    """URL 已在 GEOFlow article_distributions 表（status='synced'）→ 409。

    覆盖 create_manual_distribution 中 GEOFlow 表重复检测分支。
    """
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import (
        GeoflowArticle, GeoflowArticleDistribution,
    )
    from fastapi import HTTPException

    client = Client(
        client_id="test_geo_dup", username="geo_dup",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(
        client_id="test_geo_dup", site_name="GEOFlow 去重测试站",
        domain="geo-dup.example.com", site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.flush()

    article = GeoflowArticle(
        title="GEO 去重测试", slug="geo-dup-test",
        content="内容", category_id=1, author_id=1, status="published",
    )
    db_session.add(article)
    await db_session.flush()
    existing_geoflow = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="publish", status="synced",
        remote_url="https://www.geo-dup.example.com/existing",
    )
    db_session.add(existing_geoflow)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    try:
        with pytest.raises(HTTPException) as exc:
            await service.create_manual_distribution(
                remote_url="https://www.geo-dup.example.com/existing",
                admin_user_id=1, admin_name="admin",
                client_id="test_geo_dup",
            )
        assert exc.value.status_code == 409
        assert "GEOFlow" in exc.value.detail
    finally:
        # 清理：删 GeoflowArticleDistribution → GeoflowArticle → site → client
        await db_session.delete(existing_geoflow)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()
