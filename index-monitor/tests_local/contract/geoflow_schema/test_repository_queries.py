"""查询契约：每个仓储方法能对真实 GEOFlow DB 正常执行。

依赖 seed_contract_data 插入的固定数据。
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.integration.geoflow import GeoflowRepository
from app.integration.geoflow.dto import (
    DistributionDTO,
    DistributionWithArticleDTO,
)
from tests.contract.geoflow_schema.seed_contract_data import (
    TEST_DIST_ID_1,
    TEST_DIST_ID_2,
    TEST_REMOTE_URL_1,
    TEST_REMOTE_URL_2,
    cleanup_contract_data,
    seed_contract_data,
)


@pytest_asyncio.fixture
async def repo_with_seed(geoflow_engine):
    """插入测试数据 → 提供 repo → 测后清理。

    用 ``@pytest_asyncio.fixture`` 而非 ``@pytest.fixture``——项目 pytest-asyncio
    在 strict 模式下，async 生成器 fixture 必须用 ``pytest_asyncio.fixture``
    才能被正确 await（否则返回未消费的 async_generator 对象）。与
    ``tests/contract/geoflow_schema/conftest.py`` 中 ``geoflow_engine`` 实现策略一致。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async_session = async_sessionmaker(geoflow_engine, expire_on_commit=False)

    async with async_session() as session:
        await seed_contract_data(session)
        await session.commit()
        try:
            repo = GeoflowRepository(session)
            yield repo
        finally:
            await cleanup_contract_data(session)
            await session.commit()


@pytest.mark.asyncio
async def test_get_synced_distribution_urls(repo_with_seed):
    """get_synced_distribution_urls 应返回 seed 的 synced 记录，排除 delete 记录。"""
    urls = await repo_with_seed.get_synced_distribution_urls()
    assert TEST_REMOTE_URL_1 in urls
    # TEST_REMOTE_URL_2 的 action='delete'，不应出现
    assert "https://contract-test.example.com/article-2" not in urls


@pytest.mark.asyncio
async def test_get_distribution_by_ids(repo_with_seed):
    """get_distribution_by_ids 应返回 DTO。"""
    dtos = await repo_with_seed.get_distribution_by_ids([TEST_DIST_ID_1])
    assert len(dtos) == 1
    assert isinstance(dtos[0], DistributionDTO)
    assert dtos[0].id == TEST_DIST_ID_1
    assert dtos[0].remote_url == TEST_REMOTE_URL_1


@pytest.mark.asyncio
async def test_get_distribution_count_by_date(repo_with_seed):
    """get_distribution_count_by_date 应返回 dict。"""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    counts = await repo_with_seed.get_distribution_count_by_date(start)
    assert isinstance(counts, dict)
    # seed 数据显式插入 created_at=NOW()，应有至少一条
    assert len(counts) >= 1


@pytest.mark.asyncio
async def test_get_distributions_with_article(repo_with_seed):
    """get_distributions_with_article 应返回复合 DTO。"""
    dtos = await repo_with_seed.get_distributions_with_article()
    assert len(dtos) >= 1
    matched = [d for d in dtos if d.distribution.id == TEST_DIST_ID_1]
    assert len(matched) == 1
    assert isinstance(matched[0], DistributionWithArticleDTO)
    assert matched[0].article is not None
    assert matched[0].article.title == "契约测试文章"
    assert matched[0].channel is not None
    assert matched[0].channel.name == "契约测试渠道"


@pytest.mark.asyncio
async def test_get_deleted_distributions_with_article(repo_with_seed):
    """get_deleted_distributions_with_article 应返回 action='delete' 的记录。"""
    dtos = await repo_with_seed.get_deleted_distributions_with_article()
    matched = [d for d in dtos if d.distribution.id == TEST_DIST_ID_2]
    assert len(matched) == 1
    assert matched[0].distribution.action == "delete"


@pytest.mark.asyncio
async def test_get_synced_url_exists(repo_with_seed):
    """get_synced_url_exists 对 synced 且非 delete 的 url 返回 True，对不存在的返回 False。"""
    # TEST_REMOTE_URL_1 是 synced + publish → True
    assert await repo_with_seed.get_synced_url_exists(TEST_REMOTE_URL_1) is True
    # TEST_REMOTE_URL_2 是 synced + delete → False（action='delete' 被排除）
    assert await repo_with_seed.get_synced_url_exists(TEST_REMOTE_URL_2) is False
    # 不存在的 url → False
    assert await repo_with_seed.get_synced_url_exists("https://nonexistent.example.com/x") is False
