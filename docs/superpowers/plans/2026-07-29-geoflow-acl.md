# GEOFlow Schema 防腐层与契约测试实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 LumoraCite 侧引入仓储模式防腐层，把所有对 GEOFlow `public` schema 的直接 ORM 依赖隔离到 `app/integration/geoflow/` 一个包内，并配独立 schema 契约测试，让 GEOFlow 升级对 LumoraCite 的破坏可提前检测。

**架构：** 仓储类 `GeoflowRepository` 暴露 5 个业务方法（覆盖 7 个调用点），内部通过 `reader.py` 执行 SQLAlchemy 查询、`mappers.py` 把 raw row 映射为 frozen dataclass DTO。调用方（7 个文件）从直接 `select(GeoflowArticleDistribution)...` 改为 `repo.get_xxx(...)`。契约测试连真实 GEOFlow DB 校验表结构和查询行为。

**技术栈：** Python 3.11+ / SQLAlchemy 2.0 async / pytest / pytest-asyncio / dataclasses

**规格来源：** [docs/superpowers/specs/2026-07-29-geoflow-acl-design.md](file:///home/tishensnoopy/GEO%20FLOW+LUMORA%20CITE/docs/superpowers/specs/2026-07-29-geoflow-acl-design.md)

---

## 文件结构

**新建文件：**
- `index-monitor/app/integration/__init__.py` — 空 init
- `index-monitor/app/integration/geoflow/__init__.py` — 导出 `GeoflowRepository` 和 DTO
- `index-monitor/app/integration/geoflow/dto.py` — 4 个 frozen dataclass DTO
- `index-monitor/app/integration/geoflow/mappers.py` — 3 个 `row → DTO` 映射函数
- `index-monitor/app/integration/geoflow/reader.py` — SQLAlchemy 查询实现（5 个查询函数）
- `index-monitor/app/integration/geoflow/repository.py` — `GeoflowRepository` 仓储类（5 个业务方法）
- `index-monitor/tests/unit/test_geoflow_repository.py` — 仓储单元测试（mock reader）
- `index-monitor/tests/contract/__init__.py` — 空 init
- `index-monitor/tests/contract/geoflow_schema/__init__.py` — 空 init
- `index-monitor/tests/contract/geoflow_schema/conftest.py` — 连真实 GEOFlow DB
- `index-monitor/tests/contract/geoflow_schema/test_table_structure.py` — 结构契约
- `index-monitor/tests/contract/geoflow_schema/test_repository_queries.py` — 查询契约
- `index-monitor/tests/contract/geoflow_schema/seed_contract_data.py` — 测试数据 seed + 清理

**修改文件（7 个调用方，按迁移顺序）：**
1. `index-monitor/app/api/trend_routes.py` — 改用 `repo.get_distribution_count_by_date()`
2. `index-monitor/app/api/admin_routes.py` — 改用 `repo.get_distribution_by_ids()`
3. `index-monitor/app/services/index_checker.py` — 改用 `repo.get_synced_distribution_urls()`
4. `index-monitor/app/services/citation_checker.py` — 改用 `repo.get_synced_distribution_urls()`
5. `index-monitor/app/services/archive_service.py` — 改用 `repo.get_deleted_distributions_with_article()` + 调用方保留 `~exists` 过滤
6. `index-monitor/app/services/distribution_query.py` — 改用 `repo.get_distributions_with_article()` + 调用方保留 IndexResult join 和 client_id 过滤

**删除文件：**
- `index-monitor/app/models/geoflow_models.py` — 所有引用迁移完成后删除

---

## 全局约束

- **DTO 是 frozen dataclass**：用 `@dataclass(frozen=True)`，不可变，字段类型用 `int | None` 而非 `Optional[int]`
- **仓储方法都是 async**：与现有调用方的 `await self.db.execute(...)` 模式一致
- **仓储构造接收 `db: AsyncSession`**：与现有 `IndexChecker(db)`、`CitationChecker(db)` 模式一致
- **不改业务逻辑**：只改数据访问方式，迁移后行为零变化
- **DTO 字段名与 ORM 属性名一致**：如 `remote_url`、`article_id`、`created_at`——降低调用方改动量（`.remote_url` 访问方式不变）
- **每步迁移后跑该调用方的测试**：迁移一个文件后立即跑相关测试确认无回归
- **契约测试不依赖 CI**：手动执行 `pytest tests/contract/ -v`，连真实 GEOFlow DB
- **reader.py 内的 ORM 模型**：从 `geoflow_models.py` 迁移过来，定义为防腐层内部实现细节，不对外导出

---

### 任务 1：DTO 定义

**文件：**
- 创建：`index-monitor/app/integration/__init__.py`
- 创建：`index-monitor/app/integration/geoflow/__init__.py`
- 创建：`index-monitor/app/integration/geoflow/dto.py`
- 测试：`index-monitor/tests/unit/test_geoflow_dto.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_geoflow_dto.py`：

```python
"""DTO 不可变性 + 字段定义测试。"""
from datetime import datetime, timezone

import pytest

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)


def test_distribution_dto_fields():
    dto = DistributionDTO(
        id=1,
        article_id=100,
        remote_url="https://example.com/a",
        status="synced",
        action="publish",
        distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dto.id == 1
    assert dto.article_id == 100
    assert dto.remote_url == "https://example.com/a"
    assert dto.status == "synced"
    assert dto.action == "publish"
    assert dto.distribution_channel_id == 5
    assert dto.created_at == datetime(2026, 7, 29, tzinfo=timezone.utc)


def test_article_dto_fields():
    dto = ArticleDTO(
        id=100,
        title="标题",
        slug="slug",
        excerpt="摘要",
        content="正文",
        keywords='["k1","k2"]',
        meta_description="描述",
        original_keyword="关键词",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dto.id == 100
    assert dto.title == "标题"
    assert dto.slug == "slug"
    assert dto.keywords == '["k1","k2"]'
    assert dto.published_at == datetime(2026, 7, 29, tzinfo=timezone.utc)


def test_distribution_channel_dto_fields():
    dto = DistributionChannelDTO(
        id=5,
        name="渠道",
        domain="example.com",
        channel_type="geoflow_agent",
    )
    assert dto.id == 5
    assert dto.name == "渠道"
    assert dto.domain == "example.com"
    assert dto.channel_type == "geoflow_agent"


def test_distribution_with_article_dto_composition():
    dist = DistributionDTO(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    article = ArticleDTO(
        id=100, title="t", slug="s", excerpt=None, content=None,
        keywords=None, meta_description=None, original_keyword=None,
        published_at=None,
    )
    channel = DistributionChannelDTO(
        id=5, name="c", domain="d", channel_type="geoflow_agent",
    )
    composite = DistributionWithArticleDTO(
        distribution=dist, article=article, channel=channel,
    )
    assert composite.distribution.id == 1
    assert composite.article.title == "t"
    assert composite.channel.name == "c"


def test_dto_is_frozen():
    """DTO 不可变——修改字段应抛 FrozenInstanceError。"""
    dto = DistributionDTO(
        id=1, article_id=None, remote_url="u", status="s",
        action="a", distribution_channel_id=None,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        dto.id = 2


def test_dto_optional_fields_accept_none():
    """article_id、distribution_channel_id、article 各字段都可为 None。"""
    dist = DistributionDTO(
        id=1, article_id=None, remote_url="u", status="s",
        action="a", distribution_channel_id=None,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    assert dist.article_id is None
    assert dist.distribution_channel_id is None

    composite = DistributionWithArticleDTO(
        distribution=dist, article=None, channel=None,
    )
    assert composite.article is None
    assert composite.channel is None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_dto.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.integration'`

- [ ] **步骤 3：编写最少实现代码**

创建 `index-monitor/app/integration/__init__.py`（空文件）。

创建 `index-monitor/app/integration/geoflow/__init__.py`：

```python
"""GEOFlow schema 防腐层。

所有对 GEOFlow public schema 的直接 ORM 依赖集中在此包内。
调用方通过 GeoflowRepository 访问 GEOFlow 数据，操作 DTO 而非 ORM 模型。
"""
from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.repository import GeoflowRepository

__all__ = [
    "GeoflowRepository",
    "DistributionDTO",
    "ArticleDTO",
    "DistributionChannelDTO",
    "DistributionWithArticleDTO",
]
```

创建 `index-monitor/app/integration/geoflow/dto.py`：

```python
"""GEOFlow 数据传输对象。

DTO 只暴露 LumoraCite 实际消费的字段——GEOFlow 加新字段不影响，
删/改字段才触发契约测试失败。所有 DTO 都是 frozen dataclass。
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DistributionDTO:
    """article_distributions 表中 LumoraCite 实际消费的字段。"""
    id: int
    article_id: int | None
    remote_url: str
    status: str
    action: str
    distribution_channel_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class ArticleDTO:
    """articles 表中 LumoraCite 实际消费的字段。"""
    id: int
    title: str | None
    slug: str | None
    excerpt: str | None
    content: str | None
    keywords: str | None  # TEXT 类型，LumoraCite 侧自行解析 JSON
    meta_description: str | None
    original_keyword: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class DistributionChannelDTO:
    """distribution_channels 表中 LumoraCite 实际消费的字段。"""
    id: int
    name: str | None
    domain: str | None
    channel_type: str | None


@dataclass(frozen=True)
class DistributionWithArticleDTO:
    """三表 join 查询的复合 DTO（不含 IndexResult——那是 LumoraCite 自己的表）。"""
    distribution: DistributionDTO
    article: ArticleDTO | None
    channel: DistributionChannelDTO | None
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_dto.py -v`
预期：PASS（6 个测试）

注：此时 `__init__.py` 导入 `GeoflowRepository` 会失败（尚未创建 repository.py）——先在 `__init__.py` 中注释掉 repository 导入行，等任务 4 再放开。

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/integration/__init__.py \
        index-monitor/app/integration/geoflow/__init__.py \
        index-monitor/app/integration/geoflow/dto.py \
        index-monitor/tests/unit/test_geoflow_dto.py
git commit -m "feat(acl): 新增 GEOFlow 防腐层 DTO 定义"
```

---

### 任务 2：Mappers（row → DTO 映射）

**文件：**
- 创建：`index-monitor/app/integration/geoflow/mappers.py`
- 测试：`index-monitor/tests/unit/test_geoflow_mappers.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_geoflow_mappers.py`：

```python
"""Mappers：raw row → DTO 映射测试。"""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.mappers import (
    map_article_row,
    map_channel_row,
    map_distribution_row,
    map_join_row,
)


def _fake_dist_row(**overrides):
    base = SimpleNamespace(
        id=1,
        article_id=100,
        remote_url="https://example.com/a",
        status="synced",
        action="publish",
        distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_article_row(**overrides):
    base = SimpleNamespace(
        id=100,
        title="标题",
        slug="slug",
        excerpt="摘要",
        content="正文",
        keywords='["k1"]',
        meta_description="描述",
        original_keyword="关键词",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_channel_row(**overrides):
    base = SimpleNamespace(
        id=5,
        name="渠道",
        domain="example.com",
        channel_type="geoflow_agent",
    )
    base.__dict__.update(overrides)
    return base


def test_map_distribution_row_full():
    row = _fake_dist_row()
    dto = map_distribution_row(row)
    assert isinstance(dto, DistributionDTO)
    assert dto.id == 1
    assert dto.article_id == 100
    assert dto.remote_url == "https://example.com/a"


def test_map_distribution_row_none_fields():
    row = _fake_dist_row(article_id=None, distribution_channel_id=None)
    dto = map_distribution_row(row)
    assert dto.article_id is None
    assert dto.distribution_channel_id is None


def test_map_article_row_full():
    row = _fake_article_row()
    dto = map_article_row(row)
    assert isinstance(dto, ArticleDTO)
    assert dto.id == 100
    assert dto.title == "标题"
    assert dto.keywords == '["k1"]'


def test_map_article_row_none():
    dto = map_article_row(None)
    assert dto is None


def test_map_channel_row_full():
    row = _fake_channel_row()
    dto = map_channel_row(row)
    assert isinstance(dto, DistributionChannelDTO)
    assert dto.id == 5
    assert dto.channel_type == "geoflow_agent"


def test_map_channel_row_none():
    dto = map_channel_row(None)
    assert dto is None


def test_map_join_row_all_present():
    dist = _fake_dist_row()
    article = _fake_article_row()
    channel = _fake_channel_row()
    composite = map_join_row(dist, article, channel)
    assert isinstance(composite, DistributionWithArticleDTO)
    assert composite.distribution.id == 1
    assert composite.article.id == 100
    assert composite.channel.id == 5


def test_map_join_row_article_channel_none():
    dist = _fake_dist_row()
    composite = map_join_row(dist, None, None)
    assert composite.distribution.id == 1
    assert composite.article is None
    assert composite.channel is None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_mappers.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.integration.geoflow.mappers'`

- [ ] **步骤 3：编写最少实现代码**

创建 `index-monitor/app/integration/geoflow/mappers.py`：

```python
"""Raw ORM row → DTO 映射函数。

把字段访问集中在这里——GEOFlow 改字段名时只改此文件，
DTO 定义和调用方都不动。
"""
from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)


def map_distribution_row(row) -> DistributionDTO:
    """单条 article_distributions 行 → DistributionDTO。"""
    return DistributionDTO(
        id=row.id,
        article_id=row.article_id,
        remote_url=row.remote_url,
        status=row.status,
        action=row.action,
        distribution_channel_id=row.distribution_channel_id,
        created_at=row.created_at,
    )


def map_article_row(row) -> ArticleDTO | None:
    """articles 行 → ArticleDTO。row 为 None 时返回 None（outer join 场景）。"""
    if row is None:
        return None
    return ArticleDTO(
        id=row.id,
        title=row.title,
        slug=row.slug,
        excerpt=row.excerpt,
        content=row.content,
        keywords=row.keywords,
        meta_description=row.meta_description,
        original_keyword=row.original_keyword,
        published_at=row.published_at,
    )


def map_channel_row(row) -> DistributionChannelDTO | None:
    """distribution_channels 行 → DistributionChannelDTO。row 为 None 时返回 None。"""
    if row is None:
        return None
    return DistributionChannelDTO(
        id=row.id,
        name=row.name,
        domain=row.domain,
        channel_type=row.channel_type,
    )


def map_join_row(dist_row, article_row, channel_row) -> DistributionWithArticleDTO:
    """三表 join 的三行 → DistributionWithArticleDTO。"""
    return DistributionWithArticleDTO(
        distribution=map_distribution_row(dist_row),
        article=map_article_row(article_row),
        channel=map_channel_row(channel_row),
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_mappers.py -v`
预期：PASS（8 个测试）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/integration/geoflow/mappers.py \
        index-monitor/tests/unit/test_geoflow_mappers.py
git commit -m "feat(acl): 新增 row → DTO 映射函数"
```

---

### 任务 3：Reader（SQLAlchemy 查询实现）

**文件：**
- 创建：`index-monitor/app/integration/geoflow/reader.py`
- 测试：`index-monitor/tests/unit/test_geoflow_reader.py`

**注**：reader.py 内部需要 ORM 模型定义。我们从 `geoflow_models.py` 复制必要的模型定义到 reader.py 内部（作为防腐层内部实现细节，不对外导出）。这样防腐层与 `geoflow_models.py` 解耦——任务 10 删除 `geoflow_models.py` 时 reader 不受影响。

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_geoflow_reader.py`：

```python
"""Reader：SQLAlchemy 查询构建测试（mock db.execute）。

只验证查询能正确构建和执行、结果能正确解包，
不验证 SQL 语义（那是契约测试的职责）。
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integration.geoflow.reader import (
    fetch_deleted_distributions_with_article,
    fetch_distribution_by_ids,
    fetch_distribution_count_by_date,
    fetch_distributions_with_article,
    fetch_synced_distribution_urls,
)


def _row(*values):
    """模拟 SQLAlchemy Row 的可索引对象。"""
    return SimpleNamespace(_mapping=SimpleNamespace(values=tuple(values)))


@pytest.mark.asyncio
async def test_fetch_synced_distribution_urls_returns_url_list():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("https://a.com/1",), ("https://b.com/2",)]
    mock_db.execute.return_value = mock_result

    urls = await fetch_synced_distribution_urls(mock_db)
    assert urls == ["https://a.com/1", "https://b.com/2"]


@pytest.mark.asyncio
async def test_fetch_distribution_by_ids_returns_rows():
    mock_db = AsyncMock()
    mock_dist = SimpleNamespace(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_dist]
    mock_db.execute.return_value = mock_result

    rows = await fetch_distribution_by_ids(mock_db, [1, 2])
    assert len(rows) == 1
    assert rows[0].id == 1


@pytest.mark.asyncio
async def test_fetch_distribution_by_ids_empty_ids_returns_empty():
    mock_db = AsyncMock()
    rows = await fetch_distribution_by_ids(mock_db, [])
    assert rows == []
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_distribution_count_by_date_returns_rows():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (datetime(2026, 7, 28, tzinfo=timezone.utc), 5),
        (datetime(2026, 7, 29, tzinfo=timezone.utc), 3),
    ]
    mock_db.execute.return_value = mock_result

    rows = await fetch_distribution_count_by_date(
        mock_db, datetime(2026, 7, 28, tzinfo=timezone.utc)
    )
    assert len(rows) == 2
    assert rows[0] == (datetime(2026, 7, 28, tzinfo=timezone.utc), 5)


@pytest.mark.asyncio
async def test_fetch_distributions_with_article_no_date_filter():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    rows = await fetch_distributions_with_article(mock_db)
    assert rows == []
    # 验证 db.execute 被调用（查询构建成功）
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_distributions_with_article_with_date_filter():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)
    await fetch_distributions_with_article(mock_db, date_from=start, date_to=end)
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_deleted_distributions_with_article():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result

    rows = await fetch_deleted_distributions_with_article(mock_db)
    assert rows == []
    mock_db.execute.assert_called_once()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_reader.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.integration.geoflow.reader'`

- [ ] **步骤 3：编写最少实现代码**

创建 `index-monitor/app/integration/geoflow/reader.py`：

```python
"""GEOFlow schema 查询实现（防腐层内部）。

ORM 模型定义在此文件内部——防腐层与 geoflow_models.py 解耦，
任务 10 删除 geoflow_models.py 时 reader 不受影响。

所有函数都是 async，接收 db: AsyncSession，返回 raw row（未映射为 DTO）。
映射职责在 mappers.py，编排职责在 repository.py。
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geoflow_base import GeoflowBase  # 复用现有 base（含 schema 绑定）


# ---- 防腐层内部 ORM 模型（不对外导出）----
# 这些模型只在 reader.py 内部使用，是 GEOFlow schema 在防腐层内的唯一映射点。
# GEOFlow 升级改字段时，只改这里的列定义 + mappers.py 的字段访问。

class _Distribution(GeoflowBase):
    __tablename__ = "article_distributions"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    article_id = Column(BigInteger, nullable=True)
    remote_url = Column(String(500), nullable=True)
    status = Column(String(30), default="queued")
    action = Column(String(30), default="publish")
    distribution_channel_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True))


class _Article(GeoflowBase):
    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    title = Column(String(500), nullable=False)
    slug = Column(String(500), nullable=False, unique=True)
    excerpt = Column(Text, default="")
    content = Column(Text, nullable=False)
    keywords = Column(Text, default="")
    meta_description = Column(Text, default="")
    original_keyword = Column(String(200), default="")
    published_at = Column(DateTime(timezone=True), nullable=True)


class _Channel(GeoflowBase):
    __tablename__ = "distribution_channels"
    __table_args__ = {"schema": "public"}

    id = Column(BigInteger, primary_key=True)
    name = Column(String(120), nullable=False)
    domain = Column(String(255), nullable=False)
    channel_type = Column(String(60), default="geoflow_agent")


# ---- 查询函数 ----

async def fetch_synced_distribution_urls(db: AsyncSession) -> list[str]:
    """查所有 status='synced' 且 action!='delete' 且 remote_url 非空的 url。"""
    result = await db.execute(
        select(_Distribution.remote_url).where(
            _Distribution.status == "synced",
            _Distribution.action != "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    return [row[0] for row in result.fetchall()]


async def fetch_distribution_by_ids(
    db: AsyncSession, ids: list[int]
) -> list:
    """按 id 批量查，remote_url 非空过滤。返回 ORM 行列表。"""
    if not ids:
        return []
    result = await db.execute(
        select(_Distribution).where(
            _Distribution.id.in_(ids),
            _Distribution.remote_url.isnot(None),
        )
    )
    return result.scalars().all()


async def fetch_distribution_count_by_date(
    db: AsyncSession, start_date: datetime
) -> list[tuple]:
    """按天聚合 created_at，返回 [(day, count), ...]。"""
    day_expr = func.date_trunc("day", _Distribution.created_at).label("day")
    result = await db.execute(
        select(day_expr, func.count(_Distribution.id).label("count"))
        .where(_Distribution.created_at >= start_date)
        .group_by(day_expr)
    )
    return result.fetchall()


async def fetch_distributions_with_article(
    db: AsyncSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list:
    """三表 join 查询 synced 分发。不含 IndexResult——调用方自行 join。

    返回 raw row 列表，每个 row 可按 (dist, article, channel) 解包。
    """
    query = (
        select(_Distribution, _Article, _Channel)
        .join(_Article, _Article.id == _Distribution.article_id)
        .outerjoin(
            _Channel,
            _Channel.id == _Distribution.distribution_channel_id,
        )
        .where(
            _Distribution.status == "synced",
            _Distribution.action != "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    if date_from is not None:
        query = query.where(_Distribution.created_at >= date_from)
    if date_to is not None:
        query = query.where(_Distribution.created_at < date_to)
    result = await db.execute(query)
    return result.fetchall()


async def fetch_deleted_distributions_with_article(db: AsyncSession) -> list:
    """三表 join 查询 action='delete' 的分发。不含 ~exists 过滤——调用方自行处理。

    返回 raw row 列表，每个 row 可按 (dist, article, channel) 解包。
    """
    query = (
        select(_Distribution, _Article, _Channel)
        .join(_Article, _Article.id == _Distribution.article_id)
        .outerjoin(
            _Channel,
            _Channel.id == _Distribution.distribution_channel_id,
        )
        .where(
            _Distribution.action == "delete",
            _Distribution.remote_url.isnot(None),
        )
    )
    result = await db.execute(query)
    return result.fetchall()
```

**注**：reader.py 导入 `GeoflowBase` from `app.models.geoflow_base`——需要确认这个 base 类的位置。如果 `geoflow_base` 在 `geoflow_models.py` 内定义，需要先抽出到独立文件。这一步在任务 3 实现时检查；若 base 在 geoflow_models.py 内，先抽出到 `app/models/geoflow_base.py`。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_reader.py -v`
预期：PASS（7 个测试）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/integration/geoflow/reader.py \
        index-monitor/tests/unit/test_geoflow_reader.py \
        index-monitor/app/models/geoflow_base.py  # 若新增
git commit -m "feat(acl): 新增 GEOFlow schema 查询实现（reader）"
```

---

### 任务 4：Repository（仓储类编排）

**文件：**
- 创建：`index-monitor/app/integration/geoflow/repository.py`
- 修改：`index-monitor/app/integration/geoflow/__init__.py`（放开 GeoflowRepository 导入）
- 测试：`index-monitor/tests/unit/test_geoflow_repository.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_geoflow_repository.py`：

```python
"""Repository：仓储方法编排测试（mock reader 函数）。"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.repository import GeoflowRepository


def _fake_dist_row(**overrides):
    base = SimpleNamespace(
        id=1, article_id=100, remote_url="u", status="synced",
        action="publish", distribution_channel_id=5,
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    base.__dict__.update(overrides)
    return base


def _fake_article_row():
    return SimpleNamespace(
        id=100, title="t", slug="s", excerpt="e", content="c",
        keywords='["k"]', meta_description="m", original_keyword="k",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )


def _fake_channel_row():
    return SimpleNamespace(
        id=5, name="n", domain="d", channel_type="geoflow_agent",
    )


@pytest.mark.asyncio
async def test_get_synced_distribution_urls():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    with patch(
        "app.integration.geoflow.repository.fetch_synced_distribution_urls",
        new_callable=AsyncMock,
        return_value=["https://a.com/1", "https://b.com/2"],
    ) as mock_fetch:
        urls = await repo.get_synced_distribution_urls()
        assert urls == ["https://a.com/1", "https://b.com/2"]
        mock_fetch.assert_called_once_with(mock_db)


@pytest.mark.asyncio
async def test_get_distribution_by_ids_returns_dtos():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [_fake_dist_row(id=1), _fake_dist_row(id=2)]
    with patch(
        "app.integration.geoflow.repository.fetch_distribution_by_ids",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_distribution_by_ids([1, 2])
        assert len(dtos) == 2
        assert all(isinstance(d, DistributionDTO) for d in dtos)
        assert dtos[0].id == 1
        assert dtos[1].id == 2


@pytest.mark.asyncio
async def test_get_distribution_by_ids_empty():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    dtos = await repo.get_distribution_by_ids([])
    assert dtos == []


@pytest.mark.asyncio
async def test_get_distribution_count_by_date_returns_dict():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    start = datetime(2026, 7, 28, tzinfo=timezone.utc)
    fake_rows = [
        (datetime(2026, 7, 28, tzinfo=timezone.utc), 5),
        (datetime(2026, 7, 29, tzinfo=timezone.utc), 3),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_distribution_count_by_date",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        result = await repo.get_distribution_count_by_date(start)
        assert isinstance(result, dict)
        assert result[datetime(2026, 7, 28, tzinfo=timezone.utc)] == 5
        assert result[datetime(2026, 7, 29, tzinfo=timezone.utc)] == 3


@pytest.mark.asyncio
async def test_get_distributions_with_article_returns_composite_dtos():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [
        (_fake_dist_row(), _fake_article_row(), _fake_channel_row()),
        (_fake_dist_row(id=2, article_id=None), None, None),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_distributions_with_article",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_distributions_with_article()
        assert len(dtos) == 2
        assert isinstance(dtos[0], DistributionWithArticleDTO)
        assert dtos[0].distribution.id == 1
        assert dtos[0].article.id == 100
        assert dtos[0].channel.id == 5
        assert dtos[1].article is None
        assert dtos[1].channel is None


@pytest.mark.asyncio
async def test_get_distributions_with_article_passes_date_filter():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 31, tzinfo=timezone.utc)
    with patch(
        "app.integration.geoflow.repository.fetch_distributions_with_article",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_fetch:
        await repo.get_distributions_with_article(date_from=start, date_to=end)
        mock_fetch.assert_called_once_with(mock_db, date_from=start, date_to=end)


@pytest.mark.asyncio
async def test_get_deleted_distributions_with_article():
    mock_db = AsyncMock()
    repo = GeoflowRepository(mock_db)
    fake_rows = [
        (_fake_dist_row(action="delete"), _fake_article_row(), _fake_channel_row()),
    ]
    with patch(
        "app.integration.geoflow.repository.fetch_deleted_distributions_with_article",
        new_callable=AsyncMock,
        return_value=fake_rows,
    ):
        dtos = await repo.get_deleted_distributions_with_article()
        assert len(dtos) == 1
        assert dtos[0].distribution.action == "delete"
        assert dtos[0].article is not None
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_repository.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.integration.geoflow.repository'`

- [ ] **步骤 3：编写最少实现代码**

创建 `index-monitor/app/integration/geoflow/repository.py`：

```python
"""GEOFlow 仓储类——防腐层的对外接口。

调用方只使用 GeoflowRepository，不接触 reader/mappers/ORM 模型。
GEOFlow schema 变化时，只改 reader.py + mappers.py，此文件不动
（除非业务方法签名要调整）。
"""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integration.geoflow.dto import (
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.mappers import map_distribution_row, map_join_row
from app.integration.geoflow.reader import (
    fetch_deleted_distributions_with_article,
    fetch_distribution_by_ids,
    fetch_distribution_count_by_date,
    fetch_distributions_with_article,
    fetch_synced_distribution_urls,
)


class GeoflowRepository:
    """GEOFlow 数据只读仓储。所有方法都是 async，返回 DTO。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_synced_distribution_urls(self) -> list[str]:
        """取所有 synced 且非 delete 的 remote_url 列表。"""
        return await fetch_synced_distribution_urls(self.db)

    async def get_distribution_by_ids(self, ids: list[int]) -> list[DistributionDTO]:
        """按 id 批量查分发记录，返回 DistributionDTO 列表。"""
        rows = await fetch_distribution_by_ids(self.db, ids)
        return [map_distribution_row(row) for row in rows]

    async def get_distribution_count_by_date(
        self, start_date: datetime
    ) -> dict[datetime, int]:
        """按天聚合 created_at，返回 {date: count} 字典。"""
        rows = await fetch_distribution_count_by_date(self.db, start_date)
        return {row[0]: int(row[1]) for row in rows}

    async def get_distributions_with_article(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[DistributionWithArticleDTO]:
        """三表 join 查询 synced 分发。不含 IndexResult——调用方自行 join。"""
        rows = await fetch_distributions_with_article(
            self.db, date_from=date_from, date_to=date_to
        )
        return [map_join_row(row[0], row[1], row[2]) for row in rows]

    async def get_deleted_distributions_with_article(
        self,
    ) -> list[DistributionWithArticleDTO]:
        """三表 join 查询 action='delete' 的分发。不含 ~exists 过滤——调用方自行处理。"""
        rows = await fetch_deleted_distributions_with_article(self.db)
        return [map_join_row(row[0], row[1], row[2]) for row in rows]
```

修改 `index-monitor/app/integration/geoflow/__init__.py`——放开 `GeoflowRepository` 导入（任务 1 注释掉的行）：

```python
"""GEOFlow schema 防腐层。

所有对 GEOFlow public schema 的直接 ORM 依赖集中在此包内。
调用方通过 GeoflowRepository 访问 GEOFlow 数据，操作 DTO 而非 ORM 模型。
"""
from app.integration.geoflow.dto import (
    ArticleDTO,
    DistributionChannelDTO,
    DistributionDTO,
    DistributionWithArticleDTO,
)
from app.integration.geoflow.repository import GeoflowRepository

__all__ = [
    "GeoflowRepository",
    "DistributionDTO",
    "ArticleDTO",
    "DistributionChannelDTO",
    "DistributionWithArticleDTO",
]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_geoflow_repository.py tests/unit/test_geoflow_dto.py tests/unit/test_geoflow_mappers.py -v`
预期：PASS（全部测试）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/integration/geoflow/repository.py \
        index-monitor/app/integration/geoflow/__init__.py \
        index-monitor/tests/unit/test_geoflow_repository.py
git commit -m "feat(acl): 新增 GeoflowRepository 仓储类（5 个业务方法）"
```

---

### 任务 5：迁移 trend_routes.py

**文件：**
- 修改：`index-monitor/app/api/trend_routes.py:107-119`
- 测试：`index-monitor/tests/unit/test_trend_routes_geoflow.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_trend_routes_geoflow.py`：

```python
"""trend_routes 已改用 GeoflowRepository（验证不再直接 import GeoflowArticleDistribution）。"""
import ast
import pathlib


def test_trend_routes_no_longer_imports_geoflow_models():
    """trend_routes.py 不应再直接 import GeoflowArticleDistribution。"""
    path = pathlib.Path("app/api/trend_routes.py")
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    imports.append(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "geoflow_models" in alias.name:
                    imports.append(alias.name)
    assert "GeoflowArticleDistribution" not in imports, (
        "trend_routes.py 仍直接 import GeoflowArticleDistribution，应改用 GeoflowRepository"
    )


def test_trend_routes_imports_repository():
    """trend_routes.py 应 import GeoflowRepository。"""
    path = pathlib.Path("app/api/trend_routes.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow" in node.module and "integration" in node.module:
                found = True
                break
    assert found, "trend_routes.py 未从 app.integration.geoflow 导入"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_trend_routes_geoflow.py -v`
预期：FAIL，`test_trend_routes_no_longer_imports_geoflow_models` 失败

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/api/trend_routes.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution` 导入行
2. 新增 `from app.integration.geoflow import GeoflowRepository` 导入
3. 替换第 107-119 行的 try/except 块：

原代码（第 107-119 行）：
```python
    try:
        day_expr = func.date_trunc("day", GeoflowArticleDistribution.created_at).label("day")
        geoflow_rows = await db.execute(
            select(day_expr, func.count(GeoflowArticleDistribution.id).label("count"))
            .where(GeoflowArticleDistribution.created_at >= start_date)
            .group_by(day_expr)
        )
        for row in geoflow_rows:
            d = _to_date(row.day)
            if d in date_set:
                dist_daily_map[d] += int(row.count)
    except Exception:
        pass
```

新代码：
```python
    try:
        repo = GeoflowRepository(db)
        geoflow_counts = await repo.get_distribution_count_by_date(start_date)
        for day, count in geoflow_counts.items():
            d = _to_date(day)
            if d in date_set:
                dist_daily_map[d] += count
    except Exception:
        pass
```

4. 检查 `func`/`select` 是否在文件其他地方仍被使用——若不再使用，删除对应导入

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_trend_routes_geoflow.py -v`
预期：PASS（2 个测试）

运行现有 trend 相关测试（如有）确认无回归：
`cd index-monitor && python -m pytest tests/ -k trend -v`

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/trend_routes.py \
        index-monitor/tests/unit/test_trend_routes_geoflow.py
git commit -m "refactor(acl): trend_routes 改用 GeoflowRepository"
```

---

### 任务 6：迁移 admin_routes.py

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py:603-610`
- 测试：`index-monitor/tests/unit/test_admin_routes_geoflow.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_admin_routes_geoflow.py`：

```python
"""admin_routes 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_admin_routes_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/api/admin_routes.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution", (
                        "admin_routes.py 仍 import GeoflowArticleDistribution"
                    )


def test_admin_routes_imports_repository():
    path = pathlib.Path("app/api/admin_routes.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found, "admin_routes.py 未从 app.integration.geoflow 导入"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_admin_routes_geoflow.py -v`
预期：FAIL

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/api/admin_routes.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution`（若其他地方仍用则保留导入但移除该名称）
2. 新增 `from app.integration.geoflow import GeoflowRepository`
3. 替换第 603-610 行：

原代码：
```python
    if geoflow_int_ids:
        geoflow_result = await db.execute(
            select(GeoflowArticleDistribution).where(
                GeoflowArticleDistribution.id.in_(geoflow_int_ids),
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_dists = geoflow_result.scalars().all()
```

新代码：
```python
    if geoflow_int_ids:
        repo = GeoflowRepository(db)
        geoflow_dists = await repo.get_distribution_by_ids(geoflow_int_ids)
```

4. 后续 `for dist in geoflow_dists:` 循环中 `dist.remote_url` 访问方式不变（DTO 属性名与 ORM 一致）

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_admin_routes_geoflow.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/unit/test_admin_routes_geoflow.py
git commit -m "refactor(acl): admin_routes 改用 GeoflowRepository"
```

---

### 任务 7：迁移 index_checker.py

**文件：**
- 修改：`index-monitor/app/services/index_checker.py:28-36`
- 测试：`index-monitor/tests/unit/test_index_checker_geoflow.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_index_checker_geoflow.py`：

```python
"""index_checker 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_index_checker_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/services/index_checker.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution"


def test_index_checker_imports_repository():
    path = pathlib.Path("app/services/index_checker.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_index_checker_geoflow.py -v`
预期：FAIL

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/services/index_checker.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution`
2. 新增 `from app.integration.geoflow import GeoflowRepository`
3. 替换第 28-36 行：

原代码：
```python
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
```

新代码：
```python
        # 1. 查 GEOFlow 分发记录（通过防腐层）
        repo = GeoflowRepository(self.db)
        geoflow_urls = set(await repo.get_synced_distribution_urls())
```

4. 检查 `select` 是否在文件其他地方仍被使用，若不再使用则删除导入

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_index_checker_geoflow.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/index_checker.py \
        index-monitor/tests/unit/test_index_checker_geoflow.py
git commit -m "refactor(acl): index_checker 改用 GeoflowRepository"
```

---

### 任务 8：迁移 citation_checker.py

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py:84-129`
- 测试：`index-monitor/tests/unit/test_citation_checker_geoflow.py`

**注**：citation_checker 的 `get_pending_urls` 比 index_checker 复杂——它还查 `ManualDistribution`、`ClientSite`、`CitationResult`（都是 LumoraCite 自己的表）。仓储只负责查 GEOFlow 的 synced urls，其余逻辑留在调用方。

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_citation_checker_geoflow.py`：

```python
"""citation_checker 已改用 GeoflowRepository（仅替换 GEOFlow 查询部分）。"""
import ast
import pathlib


def test_citation_checker_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/services/citation_checker.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution"


def test_citation_checker_imports_repository():
    path = pathlib.Path("app/services/citation_checker.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_geoflow.py -v`
预期：FAIL

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/services/citation_checker.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution`
2. 新增 `from app.integration.geoflow import GeoflowRepository`
3. 替换 `get_pending_urls` 方法中第 90-98 行的 GEOFlow 查询部分：

原代码（第 90-98 行）：
```python
        geoflow_result = await self.db.execute(
            select(GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        geoflow_urls = {row[0] for row in geoflow_result.fetchall()}
```

新代码：
```python
        repo = GeoflowRepository(self.db)
        geoflow_urls = set(await repo.get_synced_distribution_urls())
```

4. 后续 `ManualDistribution`、`ClientSite`、`CitationResult` 的查询保持不变（这些是 LumoraCite 自己的表）
5. 检查 `select` 是否在文件其他地方仍被使用——`ManualDistribution`、`ClientSite`、`CitationResult` 的查询仍用 `select`，保留导入

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_geoflow.py tests/unit/test_citation_checker_stages.py -v`
预期：PASS（新测试 + 子项目 A 的阶段测试都通过）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_checker.py \
        index-monitor/tests/unit/test_citation_checker_geoflow.py
git commit -m "refactor(acl): citation_checker 改用 GeoflowRepository"
```

---

### 任务 9：迁移 archive_service.py

**文件：**
- 修改：`index-monitor/app/services/archive_service.py:68-82`
- 测试：`index-monitor/tests/unit/test_archive_service_geoflow.py`

**注**：这是三表 join 查询。仓储返回 `DistributionWithArticleDTO` 列表，调用方在 Python 层做 `~exists(ArchivedDistribution)` 过滤（因为 `ArchivedDistribution` 是 LumoraCite 自己的表）。

原 SQL 的 `~exists` 子查询查的是 `monitor.archived_distributions` 表——这个过滤现在改为：先查已归档 url 集合，再在 Python 层排除。

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_archive_service_geoflow.py`：

```python
"""archive_service 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_archive_service_no_longer_imports_geoflow_models():
    path = pathlib.Path("app/services/archive_service.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                names = [alias.name for alias in node.names]
                assert "GeoflowArticleDistribution" not in names
                assert "GeoflowArticle" not in names
                assert "GeoflowDistributionChannel" not in names


def test_archive_service_imports_repository():
    path = pathlib.Path("app/services/archive_service.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_archive_service_geoflow.py -v`
预期：FAIL

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/services/archive_service.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel`
2. 新增 `from app.integration.geoflow import GeoflowRepository`
3. 新增 `from sqlalchemy import select`（若已存在则保留——`ArchivedDistribution` 查询仍需 select）
4. 替换 `archive_deleted_distributions` 方法第 68-82 行：

原代码（第 68-83 行）：
```python
        query = (
            select(GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel)
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(
                GeoflowDistributionChannel,
                GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id,
            )
            .where(
                GeoflowArticleDistribution.action == "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
                ~exists(select(ArchivedDistribution).where(
                    ArchivedDistribution.remote_url == GeoflowArticleDistribution.remote_url
                )),
            )
        )
        rows = (await self.db.execute(query)).fetchall()
```

新代码：
```python
        # 通过防腐层查 action='delete' 的三表 join 结果
        repo = GeoflowRepository(self.db)
        composite_dtos = await repo.get_deleted_distributions_with_article()

        # 查已归档 url 集合（LumoraCite 自己的表，留在调用方）
        archived_result = await self.db.execute(
            select(ArchivedDistribution.remote_url)
        )
        archived_urls = {row[0] for row in archived_result.fetchall()}

        # Python 层过滤：排除已归档的 url（原 SQL 的 ~exists 逻辑）
        composite_dtos = [
            dto for dto in composite_dtos
            if dto.distribution.remote_url not in archived_urls
        ]
```

5. 替换循环体（第 87-117 行）——把 `dist`、`article`、`channel` 改为从 DTO 访问：

原代码（第 87-117 行）：
```python
        for dist, article, channel in rows:
            domain = normalize_domain(dist.remote_url)
            client_id = domain_map.get(domain)
            if client_id is None:
                logger.warning(f"归档跳过：URL {dist.remote_url} 的 domain {domain} 未登记")
                continue

            archived = ArchivedDistribution(
                client_id=client_id,
                remote_url=dist.remote_url,
                ...
                content_title=article.title if article else None,
                content_slug=article.slug if article else None,
                ...
                geoflow_article_id=article.id if article else None,
            )
            self.db.add(archived)
            count += 1
```

新代码：
```python
        for dto in composite_dtos:
            dist = dto.distribution
            article = dto.article
            channel = dto.channel  # 当前未消费，但保留以备将来用
            domain = normalize_domain(dist.remote_url)
            client_id = domain_map.get(domain)
            if client_id is None:
                logger.warning(f"归档跳过：URL {dist.remote_url} 的 domain {domain} 未登记")
                continue

            archived = ArchivedDistribution(
                client_id=client_id,
                remote_url=dist.remote_url,
                content_title=article.title if article else None,
                content_slug=article.slug if article else None,
                content_excerpt=article.excerpt if article else None,
                content_body=article.content if article else None,
                content_keywords=self._parse_keywords(article.keywords if article else None),
                meta_description=article.meta_description if article else None,
                original_keyword=article.original_keyword if article else None,
                published_at=article.published_at if article else None,
                geoflow_article_id=article.id if article else None,
            )
            self.db.add(archived)
            count += 1
```

6. 删除 `from sqlalchemy import exists` 导入（若不再使用）

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_archive_service_geoflow.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/archive_service.py \
        index-monitor/tests/unit/test_archive_service_geoflow.py
git commit -m "refactor(acl): archive_service 改用 GeoflowRepository"
```

---

### 任务 10：迁移 distribution_query.py

**文件：**
- 修改：`index-monitor/app/services/distribution_query.py:82-128`
- 测试：`index-monitor/tests/unit/test_distribution_query_geoflow.py`

**注**：这是最复杂的迁移。原查询 join 了 4 张表（3 张 GEOFlow + `IndexResult`）。仓储只负责 3 张 GEOFlow 表，`IndexResult` 的 join 改为在 Python 层做——先查 IndexResult 的 url→result 映射，再按 remote_url 匹配。

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_distribution_query_geoflow.py`：

```python
"""distribution_query 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_distribution_query_no_longer_imports_geoflow_models():
    path = pathlib.Path("app/services/distribution_query.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                names = [alias.name for alias in node.names]
                assert "GeoflowArticleDistribution" not in names
                assert "GeoflowArticle" not in names
                assert "GeoflowDistributionChannel" not in names


def test_distribution_query_imports_repository():
    path = pathlib.Path("app/services/distribution_query.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_distribution_query_geoflow.py -v`
预期：FAIL

- [ ] **步骤 3：编写最少实现代码**

修改 `index-monitor/app/services/distribution_query.py`：

1. 删除 `from app.models.geoflow_models import GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel`
2. 新增 `from app.integration.geoflow import GeoflowRepository`
3. 替换查询部分（第 82-128 行）。原代码用单个 join 查询返回 `(dist, article, channel, index_result)` 行；新代码分两步：(a) 仓储查三表 join 返回 DTO，(b) 单独查 IndexResult 建 url→result 映射，Python 层拼装。

原代码（第 82-128 行）：
```python
        query = (
            select(
                GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel, IndexResult,
            )
            .join(GeoflowArticle, ...)
            .outerjoin(GeoflowDistributionChannel, ...)
            .outerjoin(IndexResult, IndexResult.url == GeoflowArticleDistribution.remote_url)
            .where(...)
        )
        if date_from is not None: ...
        if date_to is not None: ...
        result = await self.db.execute(query)
        rows = result.fetchall()
        domain_map = await self._build_domain_map()
        records = []
        for row in rows:
            dist, article, channel, index_result = row
            ...
            records.append(self._serialize_geoflow(dist, article, channel, index_result, cid, site_type))
        return records
```

新代码：
```python
        # 通过防腐层查三表 join（不含 IndexResult——那是 LumoraCite 自己的表）
        repo = GeoflowRepository(self.db)
        geoflow_dtos = await repo.get_distributions_with_article(
            date_from=_date_from_lower_bound(date_from) if date_from is not None else None,
            date_to=_date_to_upper_bound(date_to) if date_to is not None else None,
        )

        # 单独查 IndexResult，建 url→result 映射
        index_result_map: dict[str, IndexResult] = {}
        if geoflow_dtos:
            urls = [dto.distribution.remote_url for dto in geoflow_dtos]
            index_result_rows = await self.db.execute(
                select(IndexResult).where(IndexResult.url.in_(urls))
            )
            for ir in index_result_rows.scalars().all():
                index_result_map[ir.url] = ir

        domain_map = await self._build_domain_map()

        records = []
        for dto in geoflow_dtos:
            dist = dto.distribution
            article = dto.article
            channel = dto.channel
            index_result = index_result_map.get(dist.remote_url)
            domain = self._extract_domain(dist.remote_url)
            matched = domain_map.get(domain)
            if matched is None:
                continue
            cid, site_type = matched
            if client_id and cid != client_id:
                continue
            records.append(
                self._serialize_geoflow(dist, article, channel, index_result, cid, site_type)
            )
        return records
```

4. 修改 `_serialize_geoflow` 方法签名——参数从 ORM 对象改为 DTO。DTO 属性名与 ORM 一致（`dist.remote_url`、`article.title`、`channel.name`、`channel.channel_type`、`index_result.*`），所以方法体基本不变，只是类型注解可选改。`index_result` 仍传 ORM 对象（IndexResult 是 LumoraCite 自己的表，不经过防腐层）。

5. 检查 `select`/`join` 等导入是否仍被使用——`IndexResult` 查询仍用 `select`，保留

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_distribution_query_geoflow.py -v`
预期：PASS

运行现有 distribution_query 测试（如有）确认无回归：
`cd index-monitor && python -m pytest tests/ -k distribution -v`

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/distribution_query.py \
        index-monitor/tests/unit/test_distribution_query_geoflow.py
git commit -m "refactor(acl): distribution_query 改用 GeoflowRepository"
```

---

### 任务 11：删除 geoflow_models.py

**文件：**
- 删除：`index-monitor/app/models/geoflow_models.py`
- 测试：`index-monitor/tests/unit/test_no_geoflow_models.py`

**前置条件**：任务 5-10 全部完成，7 个调用方已全部迁移。

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/unit/test_no_geoflow_models.py`：

```python
"""geoflow_models.py 已删除，全项目不再引用它。"""
import pathlib
import subprocess


def test_geoflow_models_file_deleted():
    path = pathlib.Path("app/models/geoflow_models.py")
    assert not path.exists(), "app/models/geoflow_models.py 仍存在"


def test_no_code_imports_geoflow_models():
    """全项目（排除防腐层 reader.py 内部）不应再 import geoflow_models。"""
    result = subprocess.run(
        ["grep", "-rn", "geoflow_models", "app/", "--include=*.py"],
        capture_output=True, text=True,
    )
    # reader.py 不应导入 geoflow_models（它有自己的内部 ORM 定义）
    # 若有残留引用，grep 会返回 0
    assert result.stdout == "", (
        f"仍有代码引用 geoflow_models:\n{result.stdout}"
    )
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_no_geoflow_models.py -v`
预期：FAIL，`test_geoflow_models_file_deleted` 失败（文件仍存在）

- [ ] **步骤 3：执行删除 + 全量回归验证**

```bash
# 删除文件
rm index-monitor/app/models/geoflow_models.py
```

全量回归测试：
```bash
cd index-monitor && python -m pytest tests/ -v --ignore=tests/contract
```
预期：所有现有测试通过（无回归）

如果回归测试失败，说明有遗漏的引用——修复后再继续。

- [ ] **步骤 4：运行新测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_no_geoflow_models.py -v`
预期：PASS（2 个测试）

- [ ] **步骤 5：Commit**

```bash
git add -A index-monitor/app/models/geoflow_models.py \
        index-monitor/tests/unit/test_no_geoflow_models.py
git commit -m "refactor(acl): 删除 geoflow_models.py，GEOFlow schema 依赖完全隔离"
```

---

### 任务 12：契约测试 conftest + 结构契约

**文件：**
- 创建：`index-monitor/tests/contract/__init__.py`
- 创建：`index-monitor/tests/contract/geoflow_schema/__init__.py`
- 创建：`index-monitor/tests/contract/geoflow_schema/conftest.py`
- 创建：`index-monitor/tests/contract/geoflow_schema/test_table_structure.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/contract/__init__.py`（空文件）。
创建 `index-monitor/tests/contract/geoflow_schema/__init__.py`（空文件）。

创建 `index-monitor/tests/contract/geoflow_schema/conftest.py`：

```python
"""契约测试公共夹具。

升级 GEOFlow 前执行：pytest tests/contract/ -v
需要真实 GEOFlow DB 可连接（从 .env 读 DATABASE_URL 或 GEOFLOW_DATABASE_URL）。
"""
import os
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_session, create_async_engine

# 契约测试需要真实 DB——若无配置则跳过（不阻塞 unit 测试运行）
GEOFLOW_DB_URL = os.getenv("GEOFLOW_DATABASE_URL") or os.getenv("DATABASE_URL", "")


def _is_pg_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgresql+asyncpg://")


pytestmark = pytest.mark.skipif(
    not GEOFLOW_DB_URL or not _is_pg_url(GEOFLOW_DB_URL),
    reason="契约测试需要 GEOFLOW_DATABASE_URL 或 DATABASE_URL 指向 PostgreSQL",
)


@pytest.fixture(scope="session")
async def geoflow_engine():
    """会话级 async engine，所有契约测试共享。"""
    url = GEOFLOW_DB_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def geoflow_session(geoflow_engine):
    """每个测试函数独立的 async session。"""
    async with geoflow_engine.connect() as conn:
        yield conn
```

创建 `index-monitor/tests/contract/geoflow_schema/test_table_structure.py`：

```python
"""结构契约：表/字段/类型校验。

只读 information_schema，不依赖业务数据，可对空库运行。
失败时打印"哪个字段缺失/类型不匹配"，直接指向问题。
"""
import pytest
from sqlalchemy import text

# 防腐层实际消费的字段清单——这是 LumoraCite 与 GEOFlow 的 schema 契约。
# GEOFlow 加字段不触发失败；删/改这里的字段才失败。
EXPECTED_FIELDS = {
    "article_distributions": {
        "id": ("integer", "bigint"),
        "article_id": ("integer", "bigint"),
        "remote_url": ("character varying", "text"),
        "status": ("character varying", "text"),
        "action": ("character varying", "text"),
        "distribution_channel_id": ("integer", "bigint"),
        "created_at": ("timestamp with time zone", "timestamp without time zone"),
    },
    "articles": {
        "id": ("integer", "bigint"),
        "title": ("character varying", "text"),
        "slug": ("character varying", "text"),
        "excerpt": ("text",),
        "content": ("text",),
        "keywords": ("text", "character varying"),
        "meta_description": ("text", "character varying"),
        "original_keyword": ("character varying", "text"),
        "published_at": ("timestamp with time zone", "timestamp without time zone"),
    },
    "distribution_channels": {
        "id": ("integer", "bigint"),
        "name": ("character varying", "text"),
        "domain": ("character varying", "text"),
        "channel_type": ("character varying", "text"),
    },
}


@pytest.mark.asyncio
async def test_tables_exist(geoflow_session):
    """三张表必须存在。"""
    result = await geoflow_session.execute(
        text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('article_distributions', 'articles', 'distribution_channels')
        """)
    )
    tables = {row[0] for row in result.fetchall()}
    expected = {"article_distributions", "articles", "distribution_channels"}
    missing = expected - tables
    assert not missing, f"GEOFlow 缺失表: {missing}"


@pytest.mark.asyncio
async def test_fields_exist_and_type_compatible(geoflow_session):
    """每个 DTO 消费的字段必须存在且类型兼容。"""
    for table_name, expected_fields in EXPECTED_FIELDS.items():
        result = await geoflow_session.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
            """),
            {"table": table_name},
        )
        actual = {row[0]: row[1] for row in result.fetchall()}
        assert actual, f"表 {table_name} 不存在或无字段"

        for field_name, acceptable_types in expected_fields.items():
            assert field_name in actual, (
                f"表 {table_name} 缺失字段 {field_name}（DTO 消费此字段）"
            )
            actual_type = actual[field_name]
            assert actual_type in acceptable_types, (
                f"表 {table_name}.{field_name} 类型不兼容: "
                f"期望 {acceptable_types}, 实际 {actual_type}"
            )
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/contract/geoflow_schema/test_table_structure.py -v`
预期：FAIL 或 SKIPPED（若未配置 GEOFLOW_DATABASE_URL）

若配置了真实 DB：
```bash
cd index-monitor && GEOFLOW_DATABASE_URL=postgresql://user:pass@localhost:15432/geo_flow \
  python -m pytest tests/contract/geoflow_schema/test_table_structure.py -v
```
预期：PASS（若 GEOFlow schema 正常）

- [ ] **步骤 3：验证（无实现代码——结构契约只校验 DB）**

结构契约测试不需要实现代码——它直接读 `information_schema`。若测试失败，说明 GEOFlow schema 与 DTO 契约不一致，需要修正 DTO 或确认 GEOFlow 是否升级。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && GEOFLOW_DATABASE_URL=postgresql://user:pass@localhost:15432/geo_flow python -m pytest tests/contract/geoflow_schema/test_table_structure.py -v`
预期：PASS（2 个测试）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/tests/contract/
git commit -m "test(contract): 新增 GEOFlow schema 结构契约测试"
```

---

### 任务 13：契约测试 seed + 查询契约

**文件：**
- 创建：`index-monitor/tests/contract/geoflow_schema/seed_contract_data.py`
- 创建：`index-monitor/tests/contract/geoflow_schema/test_repository_queries.py`

- [ ] **步骤 1：编写失败的测试**

创建 `index-monitor/tests/contract/geoflow_schema/seed_contract_data.py`：

```python
"""契约测试数据 seed + 清理。

插入固定数据（1 篇文章 + 2 条分发 + 1 个渠道），测完自动清理。
"""
from sqlalchemy import text

# 固定测试数据 ID（避免与真实数据冲突）
TEST_ARTICLE_ID = 999900001
TEST_CHANNEL_ID = 999900001
TEST_DIST_ID_1 = 999900001
TEST_DIST_ID_2 = 999900002
TEST_REMOTE_URL_1 = "https://contract-test.example.com/article-1"
TEST_REMOTE_URL_2 = "https://contract-test.example.com/article-2"


async def seed_contract_data(conn):
    """插入契约测试数据。调用方负责在测试后调用 cleanup_contract_data。"""
    await conn.execute(
        text("""
            INSERT INTO distribution_channels (id, name, domain, endpoint_url, channel_type, status)
            VALUES (:id, :name, :domain, :endpoint, :ctype, 'active')
        """),
        {
            "id": TEST_CHANNEL_ID,
            "name": "契约测试渠道",
            "domain": "contract-test.example.com",
            "endpoint": "https://contract-test.example.com/api",
            "ctype": "geoflow_agent",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO articles (id, title, slug, content, category_id, author_id, status, review_status)
            VALUES (:id, :title, :slug, :content, 1, 1, 'published', 'approved')
        """),
        {
            "id": TEST_ARTICLE_ID,
            "title": "契约测试文章",
            "slug": "contract-test-article",
            "content": "契约测试正文",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO article_distributions
            (id, article_id, remote_url, status, action, distribution_channel_id)
            VALUES
            (:id1, :aid, :url1, 'synced', 'publish', :cid),
            (:id2, :aid, :url2, 'synced', 'delete', :cid)
        """),
        {
            "id1": TEST_DIST_ID_1,
            "id2": TEST_DIST_ID_2,
            "aid": TEST_ARTICLE_ID,
            "url1": TEST_REMOTE_URL_1,
            "url2": TEST_REMOTE_URL_2,
            "cid": TEST_CHANNEL_ID,
        },
    )


async def cleanup_contract_data(conn):
    """清理契约测试数据（按固定 ID 删除）。"""
    await conn.execute(
        text("DELETE FROM article_distributions WHERE id IN (:id1, :id2)"),
        {"id1": TEST_DIST_ID_1, "id2": TEST_DIST_ID_2},
    )
    await conn.execute(
        text("DELETE FROM articles WHERE id = :id"),
        {"id": TEST_ARTICLE_ID},
    )
    await conn.execute(
        text("DELETE FROM distribution_channels WHERE id = :id"),
        {"id": TEST_CHANNEL_ID},
    )
```

创建 `index-monitor/tests/contract/geoflow_schema/test_repository_queries.py`：

```python
"""查询契约：每个仓储方法能对真实 GEOFlow DB 正常执行。

依赖 seed_contract_data 插入的固定数据。
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integration.geoflow import GeoflowRepository
from app.integration.geoflow.dto import (
    DistributionDTO,
    DistributionWithArticleDTO,
)
from tests.contract.geoflow_schema.conftest import GEOFLOW_DB_URL
from tests.contract.geoflow_schema.seed_contract_data import (
    TEST_DIST_ID_1,
    TEST_DIST_ID_2,
    TEST_REMOTE_URL_1,
    cleanup_contract_data,
    seed_contract_data,
)


@pytest.fixture
async def repo_with_seed(geoflow_engine):
    """插入测试数据 → 提供 repo → 测后清理。"""
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
    # seed 数据的 created_at 由 DB 默认值生成，应有至少一条
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && GEOFLOW_DATABASE_URL=postgresql://user:pass@localhost:15432/geo_flow python -m pytest tests/contract/geoflow_schema/test_repository_queries.py -v`
预期：FAIL（seed 或查询失败）

- [ ] **步骤 3：验证（无额外实现代码——查询逻辑在任务 3-4 已实现）**

若查询契约测试失败，可能原因：
- seed SQL 与 GEOFlow 真实表结构不符（如必填字段缺失）→ 修 seed_contract_data.py
- 仓储查询逻辑有 bug → 修 reader.py/repository.py

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && GEOFLOW_DATABASE_URL=postgresql://user:pass@localhost:15432/geo_flow python -m pytest tests/contract/geoflow_schema/ -v`
预期：PASS（结构契约 2 个 + 查询契约 5 个 = 7 个测试）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/tests/contract/geoflow_schema/seed_contract_data.py \
        index-monitor/tests/contract/geoflow_schema/test_repository_queries.py
git commit -m "test(contract): 新增 GEOFlow 查询契约测试 + seed 数据"
```

---

## 自检

### 规格覆盖度

| 规格章节 | 实现任务 |
|---------|---------|
| 文件结构（4 个新文件） | 任务 1（dto）、2（mappers）、3（reader）、4（repository） |
| DTO 定义 | 任务 1 |
| 仓储接口方法清单（5 个方法） | 任务 4 |
| 契约测试形态（结构 + 查询） | 任务 12（结构）、13（查询） |
| 迁移策略（7 个调用方 + 删除） | 任务 5-10（迁移 6 个调用方）、11（删除 geoflow_models） |

**遗漏检查**：规格提到 7 个引用文件，但 `scheduler.py` 不直接查 GEOFlow——它调用 `ArchiveService.archive_deleted_distributions()`，后者在任务 9 已迁移。所以实际只需迁移 6 个调用方文件，`scheduler.py` 无需改动。覆盖完整。

### 占位符扫描

无占位符。每个步骤都有完整代码。

### 类型一致性

- `GeoflowRepository.__init__(db: AsyncSession)` — 任务 4 定义，任务 5-10 使用 ✓
- `get_synced_distribution_urls() -> list[str]` — 任务 4 定义，任务 7/8 使用 ✓
- `get_distribution_by_ids(ids: list[int]) -> list[DistributionDTO]` — 任务 4 定义，任务 6 使用 ✓
- `get_distribution_count_by_date(start_date) -> dict[datetime, int]` — 任务 4 定义，任务 5 使用 ✓
- `get_distributions_with_article(date_from?, date_to?) -> list[DistributionWithArticleDTO]` — 任务 4 定义，任务 10 使用 ✓
- `get_deleted_distributions_with_article() -> list[DistributionWithArticleDTO]` — 任务 4 定义，任务 9 使用 ✓
- DTO 字段名与 ORM 属性名一致（`remote_url`、`article_id`、`created_at` 等）— 任务 1 定义，任务 9/10 调用方使用 ✓
