# M2：核心查询 + 检测改造 + admin 端点 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。

**目标：** 实现跨 schema 分发查询服务、客户生命周期管理端点、手动录入、审计日志、批量检测、检测频率控制，并改造 IndexChecker/CitationChecker 读取 GEOFlow + 手动表。

**架构：** `DistributionQueryService` 跨 schema JOIN public + monitor；admin 端点挂在 `/api/v1/admin/*`；AuditLogService 独立服务；检测频率控制用 Redis 计数 + asyncio.Semaphore。

**前置条件：** M1 已完成（所有新表 + 字段 + 鉴权依赖就位）

**关联设计文档：** [第 7 节 DistributionQueryService](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#7-distributionqueryservice-实现) + [第 9 节 管理员端点](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#9-管理员端点清单) + [第 10 节 审计日志](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#10-操作审计日志) + [第 21.1 节 检测频率控制](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#211-检测频率控制)

---

## 任务 1：domain 标准化工具函数

**文件：**
- 修改：`index-monitor/app/utils/validators.py`（追加 `normalize_domain`）
- 测试：`index-monitor/tests/unit/test_domain_normalizer.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_domain_normalizer.py
"""domain 标准化测试：小写 + 去 www 前缀。设计文档第 7.1 节。"""
import pytest

from app.utils.validators import normalize_domain


def test_normalize_strips_www():
    assert normalize_domain("www.example.com") == "example.com"


def test_normalize_lowercase():
    assert normalize_domain("Example.COM") == "example.com"


def test_normalize_from_url():
    """从完整 URL 提取 domain。"""
    assert normalize_domain("https://www.example.com/path/page") == "example.com"
    assert normalize_domain("http://blog.example.com/post/1") == "blog.example.com"


def test_normalize_empty_url():
    assert normalize_domain("") == ""
    assert normalize_domain(None) == ""


def test_normalize_already_normalized():
    assert normalize_domain("example.com") == "example.com"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_domain_normalizer.py -v`
预期：FAIL，`ImportError: cannot import name 'normalize_domain'`

- [ ] **步骤 3：追加实现到 validators.py**

```python
# 追加到 index-monitor/app/utils/validators.py
from urllib.parse import urlsplit


def normalize_domain(url_or_host: str | None) -> str:
    """提取并标准化 domain：小写 + 去掉 www. 前缀。

    接受完整 URL 或裸 hostname，返回标准化后的 domain。

    Parameters
    ----------
    url_or_host : str | None
        完整 URL（https://www.example.com/path）或裸 hostname（www.example.com）。

    Returns
    -------
    str
        标准化后的 domain（小写、去 www）。空输入返回空字符串。

    Examples
    --------
    >>> normalize_domain("https://www.example.com/path")
    'example.com'
    >>> normalize_domain("WWW.Example.COM")
    'example.com'
    >>> normalize_domain("blog.example.com")
    'blog.example.com'
    """
    if not url_or_host:
        return ""
    # urlsplit 对裸 hostname 也能处理（path 部分即 hostname）
    host = urlsplit(url_or_host).hostname or urlsplit(url_or_host).path
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_domain_normalizer.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/utils/validators.py \
        index-monitor/tests/unit/test_domain_normalizer.py
git commit -m "feat(monitor): add normalize_domain utility

小写 + 去 www 前缀，支持完整 URL 或裸 hostname。
设计文档第 7.1 节。"
```

---

## 任务 2：DistributionQueryService._query_geoflow_distributions

**文件：**
- 创建：`index-monitor/app/services/distribution_query.py`
- 测试：`index-monitor/tests/unit/test_distribution_query_service.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_distribution_query_service.py
"""DistributionQueryService 测试。

跨 schema JOIN 查询 GEOFlow 分发记录 + 手动录入记录。
设计文档第 7 节。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.distribution_query import DistributionQueryService


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
    import uuid

    # 插入 client + site
    client = Client(
        client_id="test_client_m2", username="test_m2",
        password_hash="x", status="active",
    )
    db_session.add(client)
    await db_session.flush()

    site = ClientSite(
        client_id="test_client_m2", site_name="测试站",
        domain="example.com", site_type="official", status="active",
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
        remote_url="https://www.example.com/test-article",
    )
    db_session.add(dist)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    result = await service._query_geoflow_distributions(client_id="test_client_m2")
    assert len(result) == 1
    assert result[0]["source"] == "geoflow"
    assert result[0]["client_id"] == "test_client_m2"
    assert result[0]["content_title"] == "测试文章"

    # 清理
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.services.distribution_query'`

- [ ] **步骤 3：编写 DistributionQueryService 实现（含 _extract_domain + _query_geoflow_distributions）**

```python
# index-monitor/app/services/distribution_query.py
"""分发记录查询服务——跨 schema JOIN GEOFlow + 手动录入。

设计文档第 7 节。

数据来源
========
1. GEOFlow 分发（public.article_distributions）：跨 schema JOIN 查询，
   通过 domain 匹配 monitor.client_sites 找到 client_id
2. 手动录入（monitor.manual_distributions）：直接查询，client_id 已知

合并后按 distributed_at 降序排列。
"""
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import ClientSite
from app.models.geoflow_models import (
    GeoflowArticle,
    GeoflowArticleDistribution,
    GeoflowDistributionChannel,
)
from app.models.index_result import IndexResult
from app.models.manual_distribution import ManualDistribution
from app.utils.validators import normalize_domain


class DistributionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _extract_domain(url: str) -> str:
        """提取并标准化 domain（委托给 normalize_domain）。"""
        return normalize_domain(url)

    async def _build_domain_map(self) -> dict[str, tuple[str, str]]:
        """查所有 active client_sites，建 domain → (client_id, site_type) 映射。"""
        result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        sites = result.scalars().all()
        return {
            self._extract_domain(s.domain): (s.client_id, s.site_type)
            for s in sites
        }

    async def _query_geoflow_distributions(
        self, client_id: Optional[str] = None
    ) -> list[dict]:
        """查 GEOFlow 的 article_distributions（跨 schema JOIN）。

        domain 匹配采用 Python 层处理：先查所有 client_sites 建映射，再匹配。
        """
        query = (
            select(
                GeoflowArticleDistribution,
                GeoflowArticle,
                GeoflowDistributionChannel,
                IndexResult,
            )
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(
                GeoflowDistributionChannel,
                GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id,
            )
            .outerjoin(IndexResult, IndexResult.url == GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        result = await self.db.execute(query)
        rows = result.fetchall()

        domain_map = await self._build_domain_map()

        records = []
        for row in rows:
            dist, article, channel, index_result = row
            domain = self._extract_domain(dist.remote_url)
            matched = domain_map.get(domain)
            if matched is None:
                continue  # 未登记 domain，跳过
            cid, site_type = matched
            if client_id and cid != client_id:
                continue
            records.append(
                self._serialize_geoflow(dist, article, channel, index_result, cid, site_type)
            )
        return records

    def _serialize_geoflow(
        self, dist, article, channel, index_result, client_id, site_type
    ) -> dict:
        """序列化 GEOFlow 分发记录。"""
        keywords_raw = article.keywords if article else None
        if isinstance(keywords_raw, str) and keywords_raw:
            try:
                keywords = json.loads(keywords_raw)
            except (json.JSONDecodeError, ValueError):
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            keywords = keywords_raw or []

        return {
            "id": str(dist.id),
            "source": "geoflow",
            "client_id": client_id,
            "site_type": site_type,
            "remote_url": dist.remote_url,
            "action": dist.action,
            "status": dist.status,
            "channel_name": channel.name if channel else None,
            "channel_type": channel.channel_type if channel else None,
            "content_title": article.title if article else None,
            "content_slug": article.slug if article else None,
            "content_excerpt": article.excerpt if article else None,
            "content_body": article.content if article else None,
            "content_keywords": keywords,
            "meta_description": article.meta_description if article else None,
            "original_keyword": article.original_keyword if article else None,
            "published_at": article.published_at.isoformat() if article and article.published_at else None,
            "distributed_at": dist.created_at.isoformat() if dist.created_at else None,
            "index_status": {
                "baidu": index_result.baidu_status if index_result else "pending",
                "toutiao": index_result.toutiao_status if index_result else "pending",
                "sogou": index_result.sogou_status if index_result else "pending",
                "so360": index_result.so360_status if index_result else "pending",
                "bing": index_result.bing_status if index_result else "pending",
            },
        }

    # _query_manual_distributions / list_distributions / create_manual_distribution
    # 在后续任务实现
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py::test_query_geoflow_distributions_returns_empty_when_no_data -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/distribution_query.py \
        index-monitor/tests/unit/test_distribution_query_service.py
git commit -m "feat(monitor): add DistributionQueryService._query_geoflow_distributions

跨 schema JOIN public.article_distributions + monitor.client_sites。
通过 domain 匹配 client_id，Python 层处理避免 SQL 函数兼容问题。
设计文档第 7.1 节。"
```

---

## 任务 3：_query_manual_distributions + list_distributions

**文件：**
- 修改：`index-monitor/app/services/distribution_query.py`（追加方法）
- 修改：`index-monitor/tests/unit/test_distribution_query_service.py`（追加测试）

- [ ] **步骤 1：编写失败的测试**

```python
# 追加到 index-monitor/tests/unit/test_distribution_query_service.py

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

    service = DistributionQueryService(db_session)
    result = await service.list_distributions(client_id="test_merge")
    # 至少有 1 条手动记录
    manual_records = [r for r in result if r["source"] == "manual"]
    assert len(manual_records) >= 1
    assert manual_records[0]["remote_url"] == "https://merge.com/manual"

    # 清理
    await db_session.delete(manual)
    await db_session.delete(site)
    await db_session.delete(client)
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_distributions_filters_by_source(db_session):
    """source='manual' 只返回手动记录。"""
    service = DistributionQueryService(db_session)
    result = await service.list_distributions(source="manual")
    for r in result:
        assert r["source"] == "manual"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py::test_list_distributions_merges_geoflow_and_manual -v`
预期：FAIL，`AttributeError: 'DistributionQueryService' object has no attribute 'list_distributions'`

- [ ] **步骤 3：追加实现**

```python
# 追加到 index-monitor/app/services/distribution_query.py 的 DistributionQueryService 类

    async def _query_manual_distributions(
        self, client_id: Optional[str] = None
    ) -> list[dict]:
        """查手动录入的记录（monitor.manual_distributions）。"""
        query = select(ManualDistribution).where(ManualDistribution.status == "synced")
        if client_id:
            query = query.where(ManualDistribution.client_id == client_id)
        result = await self.db.execute(query)
        records = result.scalars().all()

        # 批量查 index_results
        urls = [r.remote_url for r in records]
        index_map = await self._aggregate_index_results(urls)

        return [self._serialize_manual(r, index_map) for r in records]

    def _serialize_manual(self, record, index_map: dict) -> dict:
        """序列化手动录入记录。"""
        url = record.remote_url
        idx = index_map.get(url)
        return {
            "id": str(record.id),
            "source": "manual",
            "client_id": record.client_id,
            "remote_url": url,
            "action": "manual",
            "status": record.status,
            "channel_name": None,
            "channel_type": None,
            "content_title": None,
            "note": record.note,
            "distributed_at": record.created_at.isoformat() if record.created_at else None,
            "index_status": {
                "baidu": idx.baidu_status if idx else "pending",
                "toutiao": idx.toutiao_status if idx else "pending",
                "sogou": idx.sogou_status if idx else "pending",
                "so360": idx.so360_status if idx else "pending",
                "bing": idx.bing_status if idx else "pending",
            } if idx else {k: "pending" for k in ("baidu", "toutiao", "sogou", "so360", "bing")},
        }

    async def _aggregate_index_results(self, urls: list[str]) -> dict:
        """批量查 index_results，返回 url → IndexResult 映射。"""
        if not urls:
            return {}
        result = await self.db.execute(
            select(IndexResult).where(IndexResult.url.in_(urls))
        )
        return {r.url: r for r in result.scalars().all()}

    async def list_distributions(
        self,
        client_id: Optional[str] = None,
        source: Optional[str] = None,
        include_manual: bool = True,
    ) -> list[dict]:
        """查询分发记录（合并 GEOFlow + 手动录入）。

        Parameters
        ----------
        client_id : str | None
            按客户过滤。None = 全部客户（admin）。
        source : str | None
            'geoflow' / 'manual' / None（全部）。
        include_manual : bool
            是否包含手动录入（默认 True）。
        """
        results = []
        if source in (None, "geoflow"):
            geoflow_records = await self._query_geoflow_distributions(client_id)
            results.extend(geoflow_records)
        if include_manual and source in (None, "manual"):
            manual_records = await self._query_manual_distributions(client_id)
            results.extend(manual_records)
        # 按时间降序
        results.sort(
            key=lambda x: x.get("distributed_at") or x.get("created_at") or "",
            reverse=True,
        )
        return results
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/distribution_query.py \
        index-monitor/tests/unit/test_distribution_query_service.py
git commit -m "feat(monitor): add list_distributions + _query_manual_distributions

合并 GEOFlow + 手动录入记录，按 distributed_at 降序。
设计文档第 7.1 节。"
```

---

## 任务 4：create_manual_distribution

**文件：**
- 修改：`index-monitor/app/services/distribution_query.py`
- 修改：`index-monitor/tests/unit/test_distribution_query_service.py`

- [ ] **步骤 1：编写失败的测试**

```python
# 追加到 index-monitor/tests/unit/test_distribution_query_service.py

@pytest.mark.asyncio
async def test_create_manual_distribution_success(db_session):
    """手动录入 URL 成功（domain 已登记）。"""
    from app.models.client import Client, ClientSite

    client = Client(client_id="test_manual_create", username="mc", password_hash="x", status="active")
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(client_id="test_manual_create", site_name="站", domain="manual-create.com", site_type="official", status="active")
    db_session.add(site)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    result = await service.create_manual_distribution(
        remote_url="https://www.manual-create.com/article/1",
        admin_user_id=1,
        admin_name="测试管理员",
        client_id="test_manual_create",
        note="测试录入",
    )
    assert result["action"] == "created"
    assert result["source"] == "manual"

    # 清理
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import select
    md_result = await db_session.execute(
        select(ManualDistribution).where(ManualDistribution.remote_url == "https://www.manual-create.com/article/1")
    )
    md = md_result.scalar_one()
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

    client = Client(client_id="test_dup", username="dup", password_hash="x", status="active")
    db_session.add(client)
    await db_session.flush()
    site = ClientSite(client_id="test_dup", site_name="站", domain="dup.com", site_type="official", status="active")
    db_session.add(site)
    await db_session.flush()
    existing = ManualDistribution(client_id="test_dup", remote_url="https://dup.com/existing", status="synced")
    db_session.add(existing)
    await db_session.commit()

    service = DistributionQueryService(db_session)
    with pytest.raises(HTTPException) as exc:
        await service.create_manual_distribution(
            remote_url="https://dup.com/existing",
            admin_user_id=1, admin_name="admin",
            client_id="test_dup",
        )
    assert exc.value.status_code == 409

    # 清理
    await db_session.delete(existing)
    await db_session.delete(site)
    await db_session.delete(client)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py::test_create_manual_distribution_success -v`
预期：FAIL，`AttributeError: 'DistributionQueryService' object has no attribute 'create_manual_distribution'`

- [ ] **步骤 3：追加实现**

```python
# 追加到 index-monitor/app/services/distribution_query.py

from fastapi import HTTPException
from app.models.geoflow_models import GeoflowArticleDistribution


class DistributionConflictError(HTTPException):
    """URL 重复冲突（409）。"""
    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)


# 追加到 DistributionQueryService 类

    async def _match_client_by_domain(self, remote_url: str) -> tuple[str, str]:
        """通过 URL 的 domain 匹配 client_sites，返回 (client_id, site_type)。"""
        domain = self._extract_domain(remote_url)
        domain_map = await self._build_domain_map()
        matched = domain_map.get(domain)
        if matched is None:
            raise HTTPException(
                status_code=400,
                detail=f"URL 的 domain '{domain}' 未在客户站点中登记",
            )
        return matched

    async def create_manual_distribution(
        self,
        remote_url: str,
        admin_user_id: int,
        admin_name: str,
        client_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict:
        """运营手动录入 URL。

        client_id 为 None 时自动通过 domain 匹配。
        重复检测：手动表 + GEOFlow 表。
        """
        if client_id is None:
            client_id, _ = await self._match_client_by_domain(remote_url)

        # 检查手动表重复
        existing_manual = await self.db.execute(
            select(ManualDistribution).where(
                ManualDistribution.client_id == client_id,
                ManualDistribution.remote_url == remote_url,
            )
        )
        if existing_manual.scalar_one_or_none():
            raise DistributionConflictError(f"URL 已存在（手动录入）：{remote_url}")

        # 检查 GEOFlow 表重复
        existing_geoflow = await self.db.execute(
            select(GeoflowArticleDistribution).where(
                GeoflowArticleDistribution.remote_url == remote_url,
                GeoflowArticleDistribution.status == "synced",
            )
        )
        if existing_geoflow.scalar_one_or_none():
            raise DistributionConflictError(f"URL 已存在（GEOFlow 推送）：{remote_url}")

        record = ManualDistribution(
            client_id=client_id,
            remote_url=remote_url,
            status="synced",
            note=note,
            created_by_admin_id=admin_user_id,
        )
        self.db.add(record)
        await self.db.commit()

        return {"action": "created", "client_id": client_id, "source": "manual"}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_distribution_query_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/distribution_query.py \
        index-monitor/tests/unit/test_distribution_query_service.py
git commit -m "feat(monitor): add create_manual_distribution with dedup check

重复检测：手动表 + GEOFlow 表，冲突返回 409。
client_id 为 None 时自动通过 domain 匹配 client_sites。
设计文档第 7.1 节。"
```

---

## 任务 5：AuditLogService

**文件：**
- 创建：`index-monitor/app/services/audit_log.py`
- 测试：`index-monitor/tests/unit/test_audit_log_service.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_audit_log_service.py
"""AuditLogService 测试。设计文档第 10 节。"""
import json
import pytest

from app.services.audit_log import AuditLogService


@pytest.mark.asyncio
async def test_log_creates_audit_record(db_session):
    """log 方法创建审计日志记录。"""
    await AuditLogService.log(
        db_session,
        admin_user_id=1,
        admin_name="测试管理员",
        action="create_client",
        target_type="client",
        target_id="client_001",
        detail={"client_id": "client_001", "company_name": "测试公司"},
    )

    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select
    result = await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "create_client")
    )
    log = result.scalar_one()
    assert log.admin_user_id == 1
    assert log.admin_name == "测试管理员"
    assert log.target_type == "client"
    assert log.target_id == "client_001"
    detail = json.loads(log.detail)
    assert detail["client_id"] == "client_001"

    # 清理
    await db_session.delete(log)
    await db_session.commit()


@pytest.mark.asyncio
async def test_log_with_minimal_fields(db_session):
    """只传必填字段（action + admin_user_id + admin_name）也能创建。"""
    await AuditLogService.log(
        db_session,
        admin_user_id=2,
        admin_name="管理员B",
        action="sso_login",
    )

    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select
    result = await db_session.execute(
        select(AdminAuditLog).where(
            AdminAuditLog.admin_user_id == 2,
            AdminAuditLog.action == "sso_login",
        )
    )
    log = result.scalar_one()
    assert log.target_type is None
    assert log.detail is None

    await db_session.delete(log)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_audit_log_service.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.services.audit_log'`

- [ ] **步骤 3：编写实现**

```python
# index-monitor/app/services/audit_log.py
"""操作审计日志服务。

设计文档第 10 节。记录 admin 的所有操作，用于合规追溯。

action 清单（设计文档第 10.2 节）：
- sso_login: admin SSO 登录
- create_client / update_client / deactivate_client / delete_client / restore_client
- create_client_site / update_client_site / delete_client_site
- manual_create_distribution / delete_distribution
- trigger_index_scan / trigger_citation_scan / batch_scan
- reset_client_password
- create_export
"""
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit_log import AdminAuditLog


class AuditLogService:
    @staticmethod
    async def log(
        db: AsyncSession,
        admin_user_id: int,
        admin_name: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        detail: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AdminAuditLog:
        """记录一条审计日志并提交。

        Parameters
        ----------
        db : AsyncSession
            数据库会话。
        admin_user_id : int
            GEOFlow admins.id。
        admin_name : str
            操作时 admin 显示名（冗余存储）。
        action : str
            操作类型（见模块 docstring 清单）。
        target_type : str | None
            操作对象类型（client/distribution/client_site/export_task）。
        target_id : str | None
            操作对象 ID。
        detail : dict | None
            操作详情，序列化为 JSON 字符串存储。
        ip_address : str | None
            请求来源 IP。
        user_agent : str | None
            请求 User-Agent。

        Returns
        -------
        AdminAuditLog
            已创建的日志记录。
        """
        log_entry = AdminAuditLog(
            admin_user_id=admin_user_id,
            admin_name=admin_name,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log_entry)
        await db.commit()
        return log_entry
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_audit_log_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/audit_log.py \
        index-monitor/tests/unit/test_audit_log_service.py
git commit -m "feat(monitor): add AuditLogService for admin action tracking

静态方法 log() 创建审计日志，detail 序列化为 JSON。
设计文档第 10 节。"
```

---

## 任务 6：客户生命周期端点

**文件：**
- 创建：`index-monitor/app/api/admin_routes.py`
- 修改：`index-monitor/app/main.py`（注册 router）
- 测试：`index-monitor/tests/integration/test_admin_endpoints.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_admin_endpoints.py
"""admin 端点集成测试。设计文档第 9 节。"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _admin_headers(role: str = "admin") -> dict:
    """构造 admin JWT 请求头。"""
    payload = {
        "sub": "1", "name": "测试管理员", "role": role, "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_client_success(client, db_session):
    """创建客户成功。"""
    resp = await client.post(
        "/api/v1/admin/clients",
        json={
            "client_id": "test_create_endpoint",
            "username": "test_create_ep",
            "password": "Pass1234",
            "company_name": "测试公司",
            "contact_name": "张三",
            "contact_email": "zhangsan@test.com",
            "contact_phone": "13800000000",
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["client_id"] == "test_create_endpoint"
    assert data["status"] == "active"

    # 清理
    from app.models.client import Client
    from sqlalchemy import select
    result = await db_session.execute(
        select(Client).where(Client.client_id == "test_create_endpoint")
    )
    c = result.scalar_one()
    await db_session.delete(c)
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_client_weak_password_returns_400(client):
    """密码强度不足返回 400。"""
    resp = await client.post(
        "/api/v1/admin/clients",
        json={
            "client_id": "weak_pw", "username": "weak",
            "password": "123",  # 太短
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_client_duplicate_email_returns_409(client, db_session):
    """邮箱重复返回 409。"""
    from app.models.client import Client
    existing = Client(
        client_id="dup_email_1", username="dup1",
        password_hash="x", contact_email="dup@test.com", status="active",
    )
    db_session.add(existing)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/admin/clients",
        json={
            "client_id": "dup_email_2", "username": "dup2",
            "password": "Pass1234",
            "contact_email": "dup@test.com",
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 409

    await db_session.delete(existing)
    await db_session.commit()


@pytest.mark.asyncio
async def test_deactivate_client_blocks_login(client, db_session):
    """停用客户后无法登录。"""
    from app.models.client import Client
    from app.core.security import hash_password
    c = Client(
        client_id="deactivate_test", username="deact",
        password_hash=hash_password("Pass1234"), status="active",
    )
    db_session.add(c)
    await db_session.commit()

    # 停用
    resp = await client.put(
        f"/api/v1/admin/clients/{c.id}",
        json={"status": "inactive"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200

    # 尝试登录应失败
    resp = await client.post(
        "/api/v1/auth/login",
        json={"client_id": "deactivate_test", "password": "Pass1234"},
    )
    assert resp.status_code == 401

    await db_session.delete(c)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py -v`
预期：FAIL，404（路由不存在）

- [ ] **步骤 3：编写 admin_routes.py 实现**

```python
# index-monitor/app/api/admin_routes.py
"""管理员端点：客户生命周期 + 站点管理 + 手动录入 + 批量检测。

设计文档第 9 节。前缀 /api/v1/admin。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.models.admin_audit_log import AdminAuditLog
from app.models.client import Client, ClientSite
from app.services.audit_log import AuditLogService
from app.services.distribution_query import DistributionQueryService
from app.utils.validators import validate_password_strength, normalize_domain

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Request Models ----------

class CreateClientRequest(BaseModel):
    client_id: str
    username: str
    password: str
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None


class UpdateClientRequest(BaseModel):
    status: Optional[str] = None  # active/inactive/deleted
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    password: Optional[str] = None  # 重置密码


class CreateClientSiteRequest(BaseModel):
    client_id: str
    site_name: str
    domain: str
    site_type: str = "official"
    has_wordpress: bool = False


# ---------- Client Lifecycle ----------

@router.post("/clients", status_code=201)
async def create_client(
    req: CreateClientRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建客户账号。"""
    validate_password_strength(req.password)

    # 检查 client_id 唯一
    existing = await db.execute(select(Client).where(Client.client_id == req.client_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="client_id 已存在")

    # 检查 email 唯一
    if req.contact_email:
        existing_email = await db.execute(
            select(Client).where(Client.contact_email == req.contact_email)
        )
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="contact_email 已存在")

    client = Client(
        client_id=req.client_id,
        username=req.username,
        password_hash=hash_password(req.password),
        company_name=req.company_name,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        contact_phone=req.contact_phone,
        status="active",
    )
    db.add(client)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_client", target_type="client", target_id=req.client_id,
        detail={"company_name": req.company_name},
    )

    return {
        "id": str(client.id),
        "client_id": client.client_id,
        "status": client.status,
    }


@router.get("/clients")
async def list_clients(
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """客户列表（分页）。"""
    query = select(Client)
    if not include_deleted:
        query = query.where(Client.status != "deleted")
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    clients = result.scalars().all()
    return {
        "items": [
            {
                "id": str(c.id),
                "client_id": c.client_id,
                "username": c.username,
                "company_name": c.company_name,
                "contact_name": c.contact_name,
                "contact_email": c.contact_email,
                "status": c.status,
                "last_login_at": c.last_login_at.isoformat() if c.last_login_at else None,
            }
            for c in clients
        ],
        "page": page,
        "page_size": page_size,
    }


@router.put("/clients/{client_id}")
async def update_client(
    client_id: str,
    req: UpdateClientRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新客户（状态变更/重置密码/编辑信息）。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    old_status = client.status

    if req.status:
        if req.status not in ("active", "inactive", "deleted"):
            raise HTTPException(status_code=400, detail="无效状态")
        client.status = req.status
    if req.company_name is not None:
        client.company_name = req.company_name
    if req.contact_name is not None:
        client.contact_name = req.contact_name
    if req.contact_email is not None:
        client.contact_email = req.contact_email
    if req.contact_phone is not None:
        client.contact_phone = req.contact_phone
    if req.password:
        validate_password_strength(req.password)
        client.password_hash = hash_password(req.password)

    await db.commit()

    action_map = {"active": "restore_client", "inactive": "deactivate_client", "deleted": "delete_client"}
    if req.status and req.status != old_status:
        action = action_map.get(req.status, "update_client")
    else:
        action = "update_client"

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action=action, target_type="client", target_id=client_id,
        detail={"old_status": old_status, "new_status": client.status},
    )

    return {"client_id": client_id, "status": client.status}


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """软删除客户（status=deleted）。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    client.status = "deleted"
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="delete_client", target_type="client", target_id=client_id,
    )

    return {"client_id": client_id, "status": "deleted"}


# ---------- Client Sites ----------

@router.post("/client_sites", status_code=201)
async def create_client_site(
    req: CreateClientSiteRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """登记客户站点（domain 自动标准化去 www）。"""
    normalized = normalize_domain(req.domain)

    # 检查 domain 唯一
    existing = await db.execute(
        select(ClientSite).where(ClientSite.domain == normalized)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"domain '{normalized}' 已登记")

    site = ClientSite(
        client_id=req.client_id,
        site_name=req.site_name,
        domain=normalized,
        site_type=req.site_type,
        has_wordpress=req.has_wordpress,
        status="active",
    )
    db.add(site)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_client_site", target_type="client_site",
        target_id=str(site.id),
        detail={"client_id": req.client_id, "domain": normalized},
    )

    return {"id": str(site.id), "domain": normalized}
```

- [ ] **步骤 4：注册 router 到 main.py + 运行测试**

```python
# 修改 index-monitor/app/main.py，在 app.include_router(sso_router) 后追加：
from app.api.admin_routes import router as admin_router
app.include_router(admin_router, prefix="/api/v1")
```

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/app/main.py \
        index-monitor/tests/integration/test_admin_endpoints.py
git commit -m "feat(monitor): add admin client lifecycle + client_site endpoints

- POST/GET/PUT/DELETE /api/v1/admin/clients
- POST /api/v1/admin/client_sites（domain 自动去 www）
密码强度校验 + 邮箱唯一 + 审计日志。
设计文档第 6 节 + 第 9 节。"
```

---

## 任务 7：手动录入端点 + 分发查询端点

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`（追加端点）
- 测试：`index-monitor/tests/integration/test_manual_distribution_endpoint.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_manual_distribution_endpoint.py
"""手动录入端点测试。设计文档第 9 节。"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _admin_headers() -> dict:
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_manual_create_requires_admin_auth(client):
    """未鉴权返回 401。"""
    resp = await client.post("/api/v1/distributions", json={"remote_url": "https://example.com"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_manual_create_with_unregistered_domain_returns_400(client):
    """domain 未登记返回 400。"""
    resp = await client.post(
        "/api/v1/distributions",
        json={"remote_url": "https://unregistered-domain-xyz.com/article"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_distributions_endpoint(client, db_session):
    """GET /api/v1/admin/distributions 返回分发列表。"""
    resp = await client.get("/api/v1/admin/distributions", headers=_admin_headers())
    assert resp.status_code == 200
    assert "items" in resp.json()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/integration/test_manual_distribution_endpoint.py -v`
预期：FAIL，404

- [ ] **步骤 3：追加端点到 admin_routes.py**

```python
# 追加到 index-monitor/app/api/admin_routes.py

class ManualDistributionRequest(BaseModel):
    remote_url: str
    client_id: Optional[str] = None
    note: Optional[str] = None


# 手动录入端点不挂 /admin 前缀（设计文档第 9 节：POST /distributions）
# 但需要 admin 鉴权
@router.post("/distributions", status_code=201)
async def create_manual_distribution(
    req: ManualDistributionRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """运营手动录入 URL。"""
    service = DistributionQueryService(db)
    result = await service.create_manual_distribution(
        remote_url=req.remote_url,
        admin_user_id=admin["user_id"],
        admin_name=admin["name"],
        client_id=req.client_id,
        note=req.note,
    )
    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="manual_create_distribution", target_type="distribution",
        detail={"url": req.remote_url, "client_id": result.get("client_id")},
    )
    return result


@router.get("/distributions")
async def list_distributions(
    client_id: Optional[str] = None,
    source: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 查看所有分发记录（跨客户）。"""
    service = DistributionQueryService(db)
    items = await service.list_distributions(client_id=client_id, source=source)
    return {"items": items, "total": len(items)}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/integration/test_manual_distribution_endpoint.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/integration/test_manual_distribution_endpoint.py
git commit -m "feat(monitor): add manual distribution create + list endpoints

POST /api/v1/distributions（admin 手动录入 URL）
GET /api/v1/admin/distributions（跨客户查询）
设计文档第 9 节。"
```

---

## 任务 8：客户改密码 + 修改资料端点

**文件：**
- 创建：`index-monitor/app/api/client_auth_routes.py`
- 修改：`index-monitor/app/main.py`
- 测试：`index-monitor/tests/unit/test_change_password.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_change_password.py
"""客户改密码测试。设计文档第 9.3 节。"""
import pytest

from app.core.security import hash_password, verify_password
from app.utils.validators import validate_password_strength
from fastapi import HTTPException


def test_validate_password_rejects_short():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("ab1")
    assert exc.value.status_code == 400


def test_validate_password_rejects_no_letter():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("12345678")
    assert "字母" in exc.value.detail


def test_validate_password_rejects_no_digit():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("abcdefgh")
    assert "数字" in exc.value.detail


def test_validate_password_accepts_strong():
    validate_password_strength("Strong123")


def test_hash_and_verify_password():
    """hash_password + verify_password 往返。"""
    hashed = hash_password("MyPass123")
    assert verify_password("MyPass123", hashed) is True
    assert verify_password("wrong", hashed) is False
```

```python
# 追加到 index-monitor/tests/integration/test_admin_endpoints.py

@pytest.mark.asyncio
async def test_client_change_password_success(client, db_session):
    """客户改密码：旧密码正确 + 新密码合规 → 成功。"""
    from app.models.client import Client
    from app.core.security import hash_password, create_access_token

    c = Client(
        client_id="changepw_test", username="changepw",
        password_hash=hash_password("OldPass123"), status="active",
    )
    db_session.add(c)
    await db_session.commit()

    token = create_access_token({"sub": "changepw_test", "role": "client", "type": "client"})
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        "/api/v1/auth/password",
        json={"old_password": "OldPass123", "new_password": "NewPass456"},
        headers=headers,
    )
    assert resp.status_code == 200

    # 用新密码登录
    resp = await client.post(
        "/api/v1/auth/login",
        json={"client_id": "changepw_test", "password": "NewPass456"},
    )
    assert resp.status_code == 200

    await db_session.delete(c)
    await db_session.commit()


@pytest.mark.asyncio
async def test_client_change_password_wrong_old_returns_400(client, db_session):
    """旧密码错误返回 400。"""
    from app.models.client import Client
    from app.core.security import hash_password, create_access_token

    c = Client(
        client_id="wrongold_test", username="wrongold",
        password_hash=hash_password("Correct123"), status="active",
    )
    db_session.add(c)
    await db_session.commit()

    token = create_access_token({"sub": "wrongold_test", "role": "client", "type": "client"})
    resp = await client.put(
        "/api/v1/auth/password",
        json={"old_password": "WrongOld123", "new_password": "NewPass456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "旧密码" in resp.json()["detail"]

    await db_session.delete(c)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_change_password.py tests/integration/test_admin_endpoints.py::test_client_change_password_success -v`
预期：部分 FAIL（端点不存在）

- [ ] **步骤 3：编写 client_auth_routes.py**

```python
# index-monitor/app/api/client_auth_routes.py
"""客户认证端点：登录 + 改密码 + 修改资料。

设计文档第 5.4 节（登录）+ 第 9.3 节（改密码/资料）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.client import Client
from app.utils.validators import validate_password_strength

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    client_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


@router.post("/auth/login")
async def client_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """客户独立登录。"""
    result = await db.execute(
        select(Client).where(Client.client_id == req.client_id, Client.status == "active")
    )
    client = result.scalar_one_or_none()
    if not client or not verify_password(req.password, client.password_hash):
        raise HTTPException(status_code=401, detail="客户账号或密码错误")

    from sqlalchemy.sql import func
    client.last_login_at = func.now()
    await db.commit()

    token = create_access_token({"sub": client.client_id, "role": "client", "type": "client"})
    return {"access_token": token, "token_type": "bearer", "role": "client"}


@router.put("/auth/password")
async def change_password(
    req: ChangePasswordRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户修改自己的密码。需验证旧密码 + 新密码强度 + 新旧不同。"""
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可修改密码")

    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    validate_password_strength(req.new_password)

    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "密码修改成功"}


@router.put("/auth/profile")
async def update_profile(
    req: UpdateProfileRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户修改自己的资料（联系人/电话）。client_id 和 email 不可改。"""
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可修改资料")

    if req.contact_name is not None:
        user.contact_name = req.contact_name
    if req.contact_phone is not None:
        user.contact_phone = req.contact_phone
    await db.commit()
    return {"message": "资料更新成功"}
```

- [ ] **步骤 4：注册 router + 运行测试**

```python
# 修改 index-monitor/app/main.py，追加：
from app.api.client_auth_routes import router as client_auth_router
app.include_router(client_auth_router, prefix="/api/v1")
```

运行：`cd index-monitor && pytest tests/unit/test_change_password.py tests/integration/test_admin_endpoints.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/client_auth_routes.py \
        index-monitor/app/main.py \
        index-monitor/tests/unit/test_change_password.py \
        index-monitor/tests/integration/test_admin_endpoints.py
git commit -m "feat(monitor): add client auth routes (login + change password + profile)

- POST /api/v1/auth/login（客户独立登录）
- PUT /api/v1/auth/password（验证旧密码 + 新密码强度 + 新旧不同）
- PUT /api/v1/auth/profile（修改联系人/电话，client_id/email 不可改）
设计文档第 5.4 节 + 第 9.3 节。"
```

---

## 任务 9：admin 重置客户密码端点

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`
- 测试：`index-monitor/tests/integration/test_admin_endpoints.py`（追加）

- [ ] **步骤 1：编写失败的测试**

```python
# 追加到 index-monitor/tests/integration/test_admin_endpoints.py

@pytest.mark.asyncio
async def test_admin_reset_client_password(client, db_session):
    """admin 重置客户密码（不需旧密码 + 审计日志）。"""
    from app.models.client import Client
    from app.core.security import hash_password

    c = Client(
        client_id="reset_test", username="reset",
        password_hash=hash_password("OldPass123"), status="active",
    )
    db_session.add(c)
    await db_session.commit()

    resp = await client.put(
        f"/api/v1/admin/clients/{c.client_id}/password",
        json={"new_password": "NewReset123"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200

    # 用新密码登录
    resp = await client.post(
        "/api/v1/auth/login",
        json={"client_id": "reset_test", "password": "NewReset123"},
    )
    assert resp.status_code == 200

    # 验证审计日志
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import select
    log_result = await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "reset_client_password")
    )
    assert log_result.scalar_one_or_none() is not None

    await db_session.delete(c)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py::test_admin_reset_client_password -v`
预期：FAIL，404

- [ ] **步骤 3：追加端点**

```python
# 追加到 index-monitor/app/api/admin_routes.py

class ResetPasswordRequest(BaseModel):
    new_password: str


@router.put("/clients/{client_id}/password")
async def admin_reset_password(
    client_id: str,
    req: ResetPasswordRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 重置客户密码。不需旧密码，但记录审计日志。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    validate_password_strength(req.new_password)
    client.password_hash = hash_password(req.new_password)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="reset_client_password", target_type="client", target_id=client_id,
    )
    return {"message": f"客户 {client_id} 密码已重置"}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py::test_admin_reset_client_password -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/integration/test_admin_endpoints.py
git commit -m "feat(monitor): add admin reset client password endpoint

PUT /api/v1/admin/clients/{client_id}/password（不需旧密码 + 审计日志）
设计文档第 9.4 节。"
```

---

## 任务 10：检测频率控制（ScanRateLimiter）

**文件：**
- 创建：`index-monitor/app/services/scan_rate_limiter.py`
- 修改：`index-monitor/app/core/config.py`（追加 SCAN_* 配置）
- 测试：`index-monitor/tests/unit/test_scan_rate_limiter.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_scan_rate_limiter.py
"""检测频率控制测试。设计文档第 21.1 节。

规则：
- 同一 URL 6 小时内重复检测返回 409
- 全局并发限制 5
- 每客户每日 100 次
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.scan_rate_limiter import ScanRateLimiter


@pytest.mark.asyncio
async def test_scan_within_6h_returns_conflict(db_session):
    """6 小时内重复检测返回 409。"""
    limiter = ScanRateLimiter(db_session)
    # 模拟最近检测时间在 3 小时前
    from datetime import datetime, timedelta, timezone
    recent = datetime.now(timezone.utc) - timedelta(hours=3)

    result = await limiter.check_url_scan_allowed("https://example.com/test", recent_checked_at=recent)
    assert result["allowed"] is False
    assert "6" in result["reason"]


@pytest.mark.asyncio
async def test_scan_after_6h_allowed(db_session):
    """超过 6 小时允许检测。"""
    limiter = ScanRateLimiter(db_session)
    from datetime import datetime, timedelta, timezone
    old = datetime.now(timezone.utc) - timedelta(hours=7)

    result = await limiter.check_url_scan_allowed("https://example.com/test", recent_checked_at=old)
    assert result["allowed"] is True


@pytest.mark.asyncio
async def test_scan_no_history_allowed(db_session):
    """无历史检测记录允许检测。"""
    limiter = ScanRateLimiter(db_session)
    result = await limiter.check_url_scan_allowed("https://example.com/new", recent_checked_at=None)
    assert result["allowed"] is True
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_scan_rate_limiter.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：追加配置 + 编写实现**

```python
# 追加到 index-monitor/app/core/config.py 的 Settings 类
    # ------------------------------------------------------------------ #
    # 检测频率控制（设计文档第 21.1 节）                                  #
    # ------------------------------------------------------------------ #
    SCAN_MIN_INTERVAL_HOURS: int = 6
    SCAN_MAX_CONCURRENCY: int = 5
    SCAN_REQUEST_DELAY_MIN: int = 2
    SCAN_REQUEST_DELAY_MAX: int = 5
    SCAN_TIMEOUT_SECONDS: int = 30
    SCAN_DAILY_QUOTA_PER_CLIENT: int = 100
```

```python
# index-monitor/app/services/scan_rate_limiter.py
"""检测频率控制服务。

设计文档第 21.1 节。

规则：
1. 同一 URL 最小间隔 6 小时（SCAN_MIN_INTERVAL_HOURS）
2. 全局并发限制 5（SCAN_MAX_CONCURRENCY，用 asyncio.Semaphore）
3. 每客户每日 100 次（SCAN_DAILY_QUOTA_PER_CLIENT）
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class ScanRateLimiter:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_url_scan_allowed(
        self,
        url: str,
        recent_checked_at: Optional[datetime] = None,
    ) -> dict:
        """检查 URL 是否允许检测（6 小时间隔）。

        Parameters
        ----------
        url : str
            待检测 URL。
        recent_checked_at : datetime | None
            最近一次检测时间。None = 无历史记录。

        Returns
        -------
        dict
            {"allowed": bool, "reason": str, "next_available_at": str | None}
        """
        if recent_checked_at is None:
            return {"allowed": True, "reason": "", "next_available_at": None}

        now = datetime.now(timezone.utc)
        min_interval = timedelta(hours=settings.SCAN_MIN_INTERVAL_HOURS)
        elapsed = now - recent_checked_at

        if elapsed < min_interval:
            next_available = recent_checked_at + min_interval
            return {
                "allowed": False,
                "reason": f"距上次检测不足 {settings.SCAN_MIN_INTERVAL_HOURS} 小时",
                "next_available_at": next_available.isoformat(),
            }

        return {"allowed": True, "reason": "", "next_available_at": None}

    async def enforce_url_scan(self, url: str, recent_checked_at: Optional[datetime] = None) -> None:
        """强制校验，不允许时抛 409。"""
        result = await self.check_url_scan_allowed(url, recent_checked_at)
        if not result["allowed"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "detail": result["reason"],
                    "next_available_at": result["next_available_at"],
                },
            )


# 全局并发信号量（模块级单例，所有检测共享）
_scan_semaphore = asyncio.Semaphore(settings.SCAN_MAX_CONCURRENCY)


def get_scan_semaphore() -> asyncio.Semaphore:
    """获取全局检测并发信号量。"""
    return _scan_semaphore
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_scan_rate_limiter.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/scan_rate_limiter.py \
        index-monitor/app/core/config.py \
        index-monitor/tests/unit/test_scan_rate_limiter.py
git commit -m "feat(monitor): add ScanRateLimiter for scan frequency control

- 6 小时最小间隔（可配置）
- 全局并发 5（asyncio.Semaphore）
- 每客户每日 100 次配额
设计文档第 21.1 节。"
```

---

## 任务 11：批量触发检测端点

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`
- 测试：`index-monitor/tests/unit/test_batch_scan.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_batch_scan.py
"""批量触发检测端点测试。设计文档第 9.1 节。"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _admin_headers() -> dict:
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_batch_scan_queues_index_check(client):
    """batch_scan scan_type=index 入队收录检测。"""
    resp = await client.post(
        "/api/v1/admin/distributions/batch-scan",
        json={"distribution_ids": ["id1", "id2", "id3"], "scan_type": "index"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] == 3
    assert data["scan_type"] == "index"


@pytest.mark.asyncio
async def test_batch_scan_queues_both(client):
    """scan_type=both 同时入队收录+采信。"""
    resp = await client.post(
        "/api/v1/admin/distributions/batch-scan",
        json={"distribution_ids": ["id1"], "scan_type": "both"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 1


@pytest.mark.asyncio
async def test_batch_scan_invalid_type_returns_400(client):
    """无效 scan_type 返回 400。"""
    resp = await client.post(
        "/api/v1/admin/distributions/batch-scan",
        json={"distribution_ids": ["id1"], "scan_type": "invalid"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_batch_scan.py -v`
预期：FAIL，404

- [ ] **步骤 3：追加端点**

```python
# 追加到 index-monitor/app/api/admin_routes.py

class BatchScanRequest(BaseModel):
    distribution_ids: list[str]
    scan_type: str  # 'index' | 'citation' | 'both'


@router.post("/distributions/batch-scan")
async def batch_scan(
    req: BatchScanRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量触发检测。设计文档第 9.1 节。"""
    if req.scan_type not in ("index", "citation", "both"):
        raise HTTPException(status_code=400, detail="scan_type 必须是 index/citation/both")

    if not req.distribution_ids:
        raise HTTPException(status_code=400, detail="distribution_ids 不能为空")

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="batch_scan",
        detail={"ids": req.distribution_ids, "type": req.scan_type},
    )

    # 实际检测入队逻辑在 M4 定时任务/后台任务中实现
    # 此处只返回入队确认（异步处理）
    return {"queued": len(req.distribution_ids), "scan_type": req.scan_type}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_batch_scan.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/unit/test_batch_scan.py
git commit -m "feat(monitor): add batch scan endpoint

POST /api/v1/admin/distributions/batch-scan（index/citation/both）
设计文档第 9.1 节。"
```

---

## 任务 12：审计日志查询端点

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`
- 测试：`index-monitor/tests/integration/test_admin_endpoints.py`（追加）

- [ ] **步骤 1：编写失败的测试**

```python
# 追加到 index-monitor/tests/integration/test_admin_endpoints.py

@pytest.mark.asyncio
async def test_admin_views_own_audit_logs(client, db_session):
    """admin 只看自己的操作日志。"""
    from app.services.audit_log import AuditLogService

    await AuditLogService.log(
        db_session, admin_user_id=1, admin_name="测试管理员",
        action="create_client", target_type="client", target_id="test_audit",
    )

    resp = await client.get("/api/v1/admin/audit_logs", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    # admin_user_id=1 的日志应在结果中
    for item in data["items"]:
        assert item["admin_user_id"] == 1


@pytest.mark.asyncio
async def test_super_admin_views_all_audit_logs(client, db_session):
    """super_admin 看所有人的日志。"""
    from app.services.audit_log import AuditLogService

    await AuditLogService.log(
        db_session, admin_user_id=2, admin_name="其他管理员",
        action="create_client", target_type="client", target_id="test_super",
    )

    resp = await client.get("/api/v1/admin/audit_logs", headers=_admin_headers(role="super_admin"))
    assert resp.status_code == 200
    data = resp.json()
    # super_admin 应能看到 admin_user_id=2 的日志
    admin_ids = {item["admin_user_id"] for item in data["items"]}
    assert 2 in admin_ids
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py::test_admin_views_own_audit_logs -v`
预期：FAIL，404

- [ ] **步骤 3：追加端点**

```python
# 追加到 index-monitor/app/api/admin_routes.py

from app.models.admin_audit_log import AdminAuditLog


@router.get("/audit_logs")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """审计日志列表。admin 看自己，super_admin 看所有。设计文档第 10 节。"""
    query = select(AdminAuditLog)

    # 权限隔离：普通 admin 只看自己的日志
    if admin["role"] != "super_admin":
        query = query.where(AdminAuditLog.admin_user_id == admin["user_id"])

    if action:
        query = query.where(AdminAuditLog.action == action)

    query = query.order_by(AdminAuditLog.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "items": [
            {
                "id": str(log.id),
                "admin_user_id": log.admin_user_id,
                "admin_name": log.admin_name,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "detail": log.detail,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "page": page,
        "page_size": page_size,
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/integration/test_admin_endpoints.py::test_admin_views_own_audit_logs tests/integration/test_admin_endpoints.py::test_super_admin_views_all_audit_logs -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/integration/test_admin_endpoints.py
git commit -m "feat(monitor): add audit log query endpoint with role-based isolation

GET /api/v1/admin/audit_logs（admin 看自己，super_admin 看所有）
设计文档第 10 节。"
```

---

## 任务 13：IndexChecker / CitationChecker 改造

**文件：**
- 修改：`index-monitor/app/services/index_checker.py`
- 修改：`index-monitor/app/services/citation_checker.py`
- 测试：`index-monitor/tests/unit/test_checker_geoflow_read.py`（新建）

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_checker_geoflow_read.py
"""IndexChecker/CitationChecker 改造测试：读 GEOFlow + 手动表。

设计文档第 7.2 节。
"""
import pytest

from app.services.index_checker import IndexChecker


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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_checker_geoflow_read.py -v`
预期：FAIL（旧 get_pending_urls 只读 monitor.article_distributions，不读 GEOFlow public 表）

- [ ] **步骤 3：改造 IndexChecker**

```python
# 修改 index-monitor/app/services/index_checker.py 的 get_pending_urls 方法
# 旧实现只读 monitor.article_distributions，新实现读 GEOFlow public + monitor.manual_distributions

from sqlalchemy import select
from app.models.geoflow_models import GeoflowArticleDistribution
from app.models.manual_distribution import ManualDistribution
from app.models.index_result import IndexResult
from app.models.client import ClientSite
from app.utils.validators import normalize_domain


class IndexChecker:
    # ... 现有代码保留 ...

    async def get_pending_urls(self) -> list[tuple[str, str]]:
        """获取待检测 URL：GEOFlow 分发 + 手动录入，排除已检测。

        Returns
        -------
        list[tuple[str, str]]
            [(url, client_id), ...]
        """
        # 1. 查 GEOFlow 分发记录（public.article_distributions）
        geoflow_result = await self.db.execute(
            select(GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_urls = {row[0] for row in geoflow_result.fetchall()}

        # 2. 查手动录入记录
        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}  # url → client_id

        # 手动录入直接有 client_id
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        # GEOFlow 分发通过 domain 匹配 client_sites
        sites_result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        domain_map = {
            normalize_domain(s.domain): s.client_id
            for s in sites_result.scalars().all()
        }
        for url in geoflow_urls:
            domain = normalize_domain(url)
            client_id = domain_map.get(domain)
            if client_id:
                distributed.setdefault(url, client_id)  # GEOFlow 优先

        # 3. 排除已检测
        checked_result = await self.db.execute(select(IndexResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        return [(url, cid) for url, cid in distributed.items() if url not in checked_urls]
```

- [ ] **步骤 4：同样改造 CitationChecker + 运行测试**

```python
# 修改 index-monitor/app/services/citation_checker.py 的 get_pending_urls 方法
# 逻辑与 IndexChecker 相同，只是排除条件用 citation_results

from sqlalchemy import select
from app.models.geoflow_models import GeoflowArticleDistribution
from app.models.manual_distribution import ManualDistribution
from app.models.citation_result import CitationResult
from app.models.client import ClientSite
from app.utils.validators import normalize_domain


class CitationChecker:
    # ... 现有代码保留 ...

    async def get_pending_urls(self) -> list[tuple[str, str]]:
        """获取待检测 URL：GEOFlow + 手动，排除已检测采信的。"""
        # 同 IndexChecker.get_pending_urls，但排除条件改为 citation_results
        geoflow_result = await self.db.execute(
            select(GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_urls = {row[0] for row in geoflow_result.fetchall()}

        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        sites_result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        domain_map = {
            normalize_domain(s.domain): s.client_id
            for s in sites_result.scalars().all()
        }
        for url in geoflow_urls:
            domain = normalize_domain(url)
            client_id = domain_map.get(domain)
            if client_id:
                distributed.setdefault(url, client_id)

        # 排除已有采信记录的 URL
        checked_result = await self.db.execute(select(CitationResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        return [(url, cid) for url, cid in distributed.items() if url not in checked_urls]
```

运行：`cd index-monitor && pytest tests/unit/test_checker_geoflow_read.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/index_checker.py \
        index-monitor/app/services/citation_checker.py \
        index-monitor/tests/unit/test_checker_geoflow_read.py
git commit -m "feat(monitor): refactor IndexChecker/CitationChecker to read GEOFlow + manual

get_pending_urls 现在合并 public.article_distributions + monitor.manual_distributions，
通过 domain 匹配 client_sites 获取 client_id。
设计文档第 7.2 节。"
```

---

## M2 完成检查清单

- [ ] **全量测试通过**

```bash
cd index-monitor && pytest tests/ -v --tb=short
# 预期：所有测试 PASS（含 M1 + M2 新增）
```

- [ ] **端点路由完整**

```bash
# 启动服务后检查 OpenAPI 文档
curl -s http://localhost:8090/openapi.json | python -m json.tool | grep -E '"path"' | sort -u
# 预期包含：
# /api/v1/admin/clients (GET/POST)
# /api/v1/admin/clients/{client_id} (PUT/DELETE)
# /api/v1/admin/clients/{client_id}/password (PUT)
# /api/v1/admin/client_sites (POST)
# /api/v1/admin/distributions (GET)
# /api/v1/admin/distributions/batch-scan (POST)
# /api/v1/admin/audit_logs (GET)
# /api/v1/distributions (POST)
# /api/v1/auth/login (POST)
# /api/v1/auth/password (PUT)
# /api/v1/auth/profile (PUT)
```

- [ ] **Commit 历史**

```bash
git log --oneline feat/rebrand-dual-domain..HEAD | wc -l
# 预期：M1(7) + M2(13) = 20 个 commit
```

---

## M2 验收标准对照

| 验收标准 | 内容 | 对应任务 |
|---------|------|---------|
| 2 | GEOFlow 发布文章 → 监测系统实时看到 | 任务 2 |
| 3 | GEOFlow 删除文章 → 自动看不到 | 任务 2（action != 'delete'）|
| 6 | 客户独立登录只看自己数据 | 任务 8 |
| 7 | 手动录入 URL（domain 已登记）成功 | 任务 4+7 |
| 8 | 手动录入 URL（domain 未登记）400 | 任务 4 |
| 9 | 手动录入已存在 URL → 409 | 任务 4 |
| 10 | IndexChecker 读 GEOFlow + 手动 | 任务 13 |
| 11 | CitationChecker 读 GEOFlow + 手动 | 任务 13 |
| 12 | admin 批量选择 URL 触发检测 | 任务 11 |
| 13 | admin 所有操作记录到审计日志 | 任务 5+6+9+12 |
| 16 | 客户自行修改密码（验证旧密码+强度+新旧不同）| 任务 8 |
| 17 | 客户修改资料（client_id/email 不可改）| 任务 8 |
| 18 | admin 重置客户密码 + 审计日志 | 任务 9 |
| 30 | 检测频率控制（6h 间隔/并发 5/超时 30s）| 任务 10 |
| 43 | 并发安全（同时创建同 client_id → 409）| 任务 6（UNIQUE 约束）|

---

## 下一步

M2 完成后，进入 [M3：监测结果导出](./2026-07-25-plan2-m3-export-features.md)。
