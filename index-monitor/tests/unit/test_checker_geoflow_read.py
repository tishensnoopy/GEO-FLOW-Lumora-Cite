"""IndexChecker/CitationChecker 改造测试：读 GEOFlow + 手动表。

设计文档第 7.2 节。

覆盖目标（验收标准 10/11）：
- IndexChecker.get_pending_urls 读 GEOFlow public.article_distributions
- IndexChecker.get_pending_urls 读 monitor.manual_distributions
- 通过 domain 匹配 client_sites 获取 client_id
- 排除已检测的 URL（index_results / citation_results）
- 排除 action='delete' 的 GEOFlow 分发
- CitationChecker.get_pending_urls 对称行为
"""
import pytest

from app.services.index_checker import IndexChecker
from app.services.citation_checker import CitationChecker


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


# --------------------------------------------------------------------------- #
# 辅助：插入 client + client_site（domain 匹配 GEOFlow remote_url）            #
# --------------------------------------------------------------------------- #

async def _seed_client_and_site(db_session, client_id: str, username: str, domain: str):
    """插入 client + client_site，返回 (client, site)。"""
    from app.models.client import Client, ClientSite

    client = Client(
        client_id=client_id, username=username,
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()

    site = ClientSite(
        client_id=client_id, site_name="站", domain=domain,
        site_type="official", status="active",
    )
    db_session.add(site)
    await db_session.flush()
    return client, site


async def _seed_geoflow_article_and_distribution(
    db_session, remote_url: str, action: str = "publish", status: str = "synced",
):
    """插入 GEOFlow article + distribution，返回 (article, dist)。"""
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

    article = GeoflowArticle(
        title="测试文章", slug=f"slug-{remote_url}", content="x",
        category_id=1, author_id=1, status="published",
    )
    db_session.add(article)
    await db_session.flush()

    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action=action, status=status, remote_url=remote_url,
    )
    db_session.add(dist)
    await db_session.flush()
    return article, dist


# --------------------------------------------------------------------------- #
# IndexChecker 正向测试                                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_get_pending_urls_reads_geoflow_distribution(db_session):
    """IndexChecker.get_pending_urls 读 GEOFlow 分发，通过 domain 匹配 client_id。

    这是验收标准 10 的核心：旧代码只读 monitor.article_distributions（旧表），
    不读 public.article_distributions，故会返回空列表。新代码应读到 URL 并
    通过 client_sites 匹配到 client_id。
    """
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

    client, site = await _seed_client_and_site(
        db_session, "idx_geoflow_test", "idx_geoflow", "geoflow-pending.example.com",
    )
    article, dist = await _seed_geoflow_article_and_distribution(
        db_session, "https://geoflow-pending.example.com/article/1",
    )
    await db_session.commit()

    try:
        checker = IndexChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_dict = dict(pending)

        target_url = "https://geoflow-pending.example.com/article/1"
        assert target_url in pending_dict, "GEOFlow 分发的 URL 应出现在 pending 中"
        assert pending_dict[target_url] == "idx_geoflow_test", (
            "通过 domain 匹配 client_sites 应得到正确 client_id"
        )
    finally:
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_pending_urls_reads_manual_distribution(db_session):
    """IndexChecker.get_pending_urls 读 monitor.manual_distributions。

    手动录入记录自带 client_id，无需 domain 匹配。
    """
    from app.models.client import Client
    from app.models.manual_distribution import ManualDistribution

    client = Client(
        client_id="idx_manual_test", username="idx_manual",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()

    manual = ManualDistribution(
        client_id="idx_manual_test",
        remote_url="https://manual-pending.example.com/page",
        status="synced",
    )
    db_session.add(manual)
    await db_session.commit()

    try:
        checker = IndexChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_dict = dict(pending)

        target_url = "https://manual-pending.example.com/page"
        assert target_url in pending_dict, "手动录入的 URL 应出现在 pending 中"
        assert pending_dict[target_url] == "idx_manual_test"
    finally:
        await db_session.delete(manual)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_already_checked(db_session):
    """已检测的 URL 不在 pending 列表中，但未检测的 GEOFlow URL 应在。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.index_result import IndexResult

    client, site = await _seed_client_and_site(
        db_session, "idx_checked_test", "idx_checked", "checked-example.com",
    )
    # 两条 GEOFlow 分发：一条已检测，一条未检测
    article_checked, dist_checked = await _seed_geoflow_article_and_distribution(
        db_session, "https://checked-example.com/checked",
    )
    article_pending, dist_pending = await _seed_geoflow_article_and_distribution(
        db_session, "https://checked-example.com/pending",
    )

    ir = IndexResult(
        url="https://checked-example.com/checked",
        client_id="idx_checked_test", site_type="official",
        baidu_status="indexed",
    )
    db_session.add(ir)
    await db_session.commit()

    try:
        checker = IndexChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_urls = [u for u, _ in pending]

        assert "https://checked-example.com/checked" not in pending_urls, (
            "已检测的 URL 不应出现在 pending 中"
        )
        assert "https://checked-example.com/pending" in pending_urls, (
            "未检测的 GEOFlow URL 应出现在 pending 中（对照验证）"
        )
    finally:
        await db_session.delete(ir)
        await db_session.delete(dist_checked)
        await db_session.delete(article_checked)
        await db_session.delete(dist_pending)
        await db_session.delete(article_pending)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_action_delete(db_session):
    """action='delete' 的 GEOFlow 分发不进入 pending。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

    client, site = await _seed_client_and_site(
        db_session, "idx_delete_test", "idx_delete", "delete-example.com",
    )
    article, dist = await _seed_geoflow_article_and_distribution(
        db_session, "https://delete-example.com/deleted", action="delete",
    )
    await db_session.commit()

    try:
        checker = IndexChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_urls = [u for u, _ in pending]

        assert "https://delete-example.com/deleted" not in pending_urls, (
            "action='delete' 的分发不应进入 pending"
        )
    finally:
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_pending_urls_skips_unregistered_domain(db_session):
    """GEOFlow 分发的 domain 未在 client_sites 登记时，跳过该 URL。"""
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

    article, dist = await _seed_geoflow_article_and_distribution(
        db_session, "https://unregistered-domain-xyz.com/article",
    )
    await db_session.commit()

    try:
        checker = IndexChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_urls = [u for u, _ in pending]

        assert "https://unregistered-domain-xyz.com/article" not in pending_urls, (
            "未登记 domain 的 GEOFlow URL 应被跳过"
        )
    finally:
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.commit()


# --------------------------------------------------------------------------- #
# CitationChecker 对称测试（验收标准 11）                                      #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_citation_checker_reads_geoflow_distribution(db_session):
    """CitationChecker.get_pending_urls 读 GEOFlow 分发。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

    client, site = await _seed_client_and_site(
        db_session, "cite_geoflow_test", "cite_geoflow", "cite-pending.example.com",
    )
    article, dist = await _seed_geoflow_article_and_distribution(
        db_session, "https://cite-pending.example.com/article/1",
    )
    await db_session.commit()

    try:
        checker = CitationChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_dict = dict(pending)

        target_url = "https://cite-pending.example.com/article/1"
        assert target_url in pending_dict, "CitationChecker 应读到 GEOFlow 分发的 URL"
        assert pending_dict[target_url] == "cite_geoflow_test"
    finally:
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()


@pytest.mark.asyncio
async def test_citation_checker_excludes_already_checked(db_session):
    """CitationChecker 排除已有 citation_results 记录的 URL。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.citation_result import CitationResult

    client, site = await _seed_client_and_site(
        db_session, "cite_checked_test", "cite_checked", "cite-checked.example.com",
    )
    article_checked, dist_checked = await _seed_geoflow_article_and_distribution(
        db_session, "https://cite-checked.example.com/checked",
    )
    article_pending, dist_pending = await _seed_geoflow_article_and_distribution(
        db_session, "https://cite-checked.example.com/pending",
    )

    cr = CitationResult(
        url="https://cite-checked.example.com/checked",
        model="deepseek-chat", question="测试问题",
        answer="x", hit_type="none", sources=[],
    )
    db_session.add(cr)
    await db_session.commit()

    try:
        checker = CitationChecker(db_session)
        pending = await checker.get_pending_urls()
        pending_urls = [u for u, _ in pending]

        assert "https://cite-checked.example.com/checked" not in pending_urls, (
            "已有 citation_results 的 URL 不应出现在 pending 中"
        )
        assert "https://cite-checked.example.com/pending" in pending_urls, (
            "未检测的 GEOFlow URL 应出现在 pending 中（对照验证）"
        )
    finally:
        await db_session.delete(cr)
        await db_session.delete(dist_checked)
        await db_session.delete(article_checked)
        await db_session.delete(dist_pending)
        await db_session.delete(article_pending)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()
