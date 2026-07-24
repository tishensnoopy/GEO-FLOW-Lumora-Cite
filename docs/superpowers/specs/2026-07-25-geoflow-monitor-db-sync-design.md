# GEOFlow + 监测系统 统一数据库架构与监测能力增强设计

- **创建日期**：2026-07-25
- **状态**：待实现
- **关联文档**：[2026-07-23-geo-monitoring-system-design.md](./2026-07-23-geo-monitoring-system-design.md)
- **实现分支**：`feat/unified-db-and-monitoring`（基于 `feat/rebrand-dual-domain`）

---

## 1. 背景与目标

### 1.1 问题陈述

当前系统存在两个独立的 PostgreSQL 实例：

- **GEOFlow**（Laravel/PHP）：内容生产端，使用 `pgvector/pgvector:pg16` 镜像（PostgreSQL 16 + pgvector 向量扩展），有自己的 docker-compose（[GEOFlow-main/docker-compose.yml](../../../GEOFlow-main/docker-compose.yml)）。
- **监测系统**（FastAPI/Python，index-monitor + dashboard）：监测端，使用 `postgres:15-alpine` 镜像（[docker-compose.prod.yml](../../../docker-compose.prod.yml) 的 `postgres` 容器）。

两个 PG 实例完全不互通，导致 GEOFlow 分发成功的文章数据无法流入监测系统，`article_distributions` 表在监测系统侧是空的，IndexChecker 和 CitationChecker 无法执行。

**经过 brainstorming 评估，两套数据库是历史遗留，不是有意设计。** 同步机制（推送/重试/幂等）本质上是在解决人为制造的数据隔离问题。本设计改为**一套数据库**，从根源消除数据不互通。

### 1.2 设计目标

1. **统一数据库**：监测系统直接读 GEOFlow 的 PG，用 schema 隔离，消除同步机制
2. **手动 URL 录入**：支持运营手动录入 URL（不依赖 GEOFlow 分发）
3. **管理员角色**：补全 admin/super_admin 两级角色（你和同事登录管理）
4. **监测结果导出**：支持 PDF/Excel 报告导出
5. **多渠道分发扩展**：为头条/知乎等平台预留扩展点
6. **客户 dashboard**：采用专业数据中台风格（风格 A）
7. **官网管理入口**：在官网添加管理员/客户登录入口

### 1.3 非目标（YAGNI）

- 不做监测系统 → GEOFlow 的反向同步（统一数据库后天然可见，不需要反向同步）
- 不做头条/知乎 publisher 的完整实现（本期只做框架 + generic_http_api 适配，具体平台 API 调研作为后续任务）
- 不引入消息队列
- 不做 PostgreSQL FDW（同一 PG 内跨 schema 查询不需要 FDW）

---

## 2. 架构总览

### 2.1 统一数据库架构

```
┌─────────────────────────────────────────────────────────────────┐
│  单一 PostgreSQL 实例（pgvector/pgvector:pg16）                  │
│                                                                  │
│  public schema（GEOFlow 读写）                                   │
│   ├── articles                          ← 监测系统只读 JOIN       │
│   ├── article_distributions             ← 监测系统只读 JOIN       │
│   ├── distribution_channels             ← 监测系统只读            │
│   ├── knowledge_bases / knowledge_chunks ← pgvector 向量搜索     │
│   └── ...（GEOFlow 现有所有表）                                  │
│                                                                  │
│  monitor schema（监测系统读写）                                  │
│   ├── clients                           ← 客户账号               │
│   ├── client_sites                      ← 客户站点（domain 映射）│
│   ├── admins                            ← 管理员账号             │
│   ├── index_results                     ← 收录检测结果           │
│   ├── citation_results                  ← AI 采信检测结果        │
│   ├── manual_distributions              ← 手动录入的 URL         │
│   ├── system_config                     ← 系统配置               │
│   └── export_tasks                      ← 导出任务记录           │
└─────────────────────────────────────────────────────────────────┘
        ▲                              ▲
        │                              │
┌───────┴──────────┐          ┌────────┴──────────────────────┐
│  GEOFlow          │          │  监测系统 (index-monitor)      │
│  (Laravel/PHP)    │          │  (FastAPI/Python)              │
│  连 public schema │          │  读 public + 读写 monitor     │
│  写 articles 等   │          │  跨 schema JOIN 查询           │
└───────────────────┘          └────────────────────────────────┘
```

### 2.2 关键边界

- **GEOFlow**：只读写 `public` schema，不感知 `monitor` schema 存在
- **监测系统**：读 `public` schema（只读 GEOFlow 数据），读写 `monitor` schema（自己的表）
- **数据一致性**：天然保证（同一 PG，同一事务可见性）
- **schema 隔离**：GEOFlow 改表结构不影响监测系统（除非改了被监测系统 JOIN 的表结构）
- **无同步机制**：不需要推送、重试、幂等、迁移命令

### 2.3 数据流

```
GEOFlow 发布文章 → 写 public.article_distributions (status='synced')
                          │
                          │ 监测系统跨 schema 查询（实时可见）
                          ▼
监测系统查询：SELECT d.*, a.title, a.content, s.client_id, s.site_type
              FROM public.article_distributions d
              JOIN public.articles a ON a.id = d.article_id
              LEFT JOIN monitor.client_sites s ON s.domain = extract_domain(d.remote_url)
              WHERE d.status = 'synced' AND d.action != 'delete'
                          │
                          ▼
IndexChecker / CitationChecker 执行检测 → 写 monitor.index_results / monitor.citation_results
                          │
                          ▼
客户/管理员看 dashboard → 查询 monitor.index_results + monitor.citation_results
                          │
                          ▼
导出报告（PDF/Excel）→ 下载
```

---

## 3. 数据库统一方案

### 3.1 迁移策略

**目标**：废弃监测系统的 `postgres:15-alpine` 容器，统一使用 GEOFlow 的 `pgvector/pgvector:pg16` 容器。

**迁移步骤**（本地先验证，生产按部署手册执行）：

1. **备份监测系统现有数据**（虽然表是空的，但保险起见）
   ```bash
   docker exec geo-postgres-local pg_dump -U geo_user -d geo_monitoring > backup_monitor.sql
   ```

2. **在 GEOFlow 的 PG 创建 monitor schema**
   ```sql
   CREATE SCHEMA IF NOT EXISTS monitor;
   ```

3. **迁移监测系统的表到 monitor schema**
   - 修改监测系统的 Alembic 迁移，所有表加 `schema="monitor"`
   - 或用 `ALTER TABLE xxx SET SCHEMA monitor` 迁移现有表

4. **更新监测系统的数据库连接配置**
   - `.env.prod` 改 `POSTGRES_HOST` 指向 GEOFlow 的 PG 容器
   - `POSTGRES_PORT` 改为 GEOFlow PG 的端口
   - `POSTGRES_DB` 改为 GEOFlow 的 database name

5. **更新 docker-compose**
   - `docker-compose.prod.yml` 删除 `postgres` 服务（geo-postgres）
   - `index-monitor` 服务的 `depends_on` 改为依赖 GEOFlow 的 PG（或通过 host 网络访问）
   - 保留 `redis` 服务（监测系统仍需要 Redis）

6. **验证**：监测系统能跨 schema 查询 `public.article_distributions`

### 3.2 回滚方案

如果统一后出现问题：
1. 恢复监测系统的 `postgres:15-alpine` 容器
2. 恢复 `backup_monitor.sql`
3. 监测系统 `.env` 改回原 PG 连接
4. GEOFlow 不受影响（从未改动）

### 3.3 网络配置

**方案**：GEOFlow 和监测系统的 docker-compose 合并到同一个网络，或通过宿主机网络访问。

**推荐**：合并到一个 docker-compose（或用 `external network`），让监测系统的 index-monitor 容器能直接访问 GEOFlow 的 PG 容器。

```yaml
# docker-compose.prod.yml（合并后）
networks:
  geoflow-net:
    external: true  # GEOFlow 的 docker-compose 创建的网络

services:
  index-monitor:
    environment:
      POSTGRES_HOST: geoflow-postgres  # GEOFlow 的 PG 容器名
      POSTGRES_PORT: 5432
      POSTGRES_DB: ${GEOFLOW_DB_NAME}
      ...
    networks:
      - geoflow-net
```

---

## 4. 数据模型

### 4.1 监测系统侧：monitor schema 的表

**新建 admins 表**：

```python
# index-monitor/app/models/admin.py
class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = {"schema": "monitor"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="admin", nullable=False)  # 'admin' | 'super_admin'
    status = Column(String(32), default="active", nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**新建 manual_distributions 表**（手动录入的 URL）：

```python
# index-monitor/app/models/manual_distribution.py
class ManualDistribution(Base):
    __tablename__ = "manual_distributions"
    __table_args__ = (
        UniqueConstraint("client_id", "remote_url", name="uq_manual_client_url"),
        {"schema": "monitor"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    note = Column(Text, nullable=True)  # 运营备注
    created_by_admin_id = Column(UUID(as_uuid=True), nullable=True)  # 录入的 admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**现有表迁移到 monitor schema**（clients, client_sites, index_results, citation_results, system_config, index_history）：

```python
# 所有监测系统的模型加 __table_args__ = {"schema": "monitor"}
class Client(Base):
    __tablename__ = "clients"
    __table_args__ = {"schema": "monitor"}
    # ... 字段不变

class ClientSite(Base):
    __tablename__ = "client_sites"
    __table_args__ = (
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),
        UniqueConstraint("domain", name="client_sites_domain_unique_key"),  # 新增：一个 domain 只属于一个客户
        {"schema": "monitor"},
    )
    # ... 字段不变
```

**新建 export_tasks 表**（导出任务记录）：

```python
class ExportTask(Base):
    __tablename__ = "export_tasks"
    __table_args__ = {"schema": "monitor"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=True)  # null 表示全部客户（admin 导出）
    requested_by = Column(String(128), nullable=False)  # admin username 或 client_id
    requested_by_role = Column(String(32), nullable=False)  # 'admin' | 'client'
    export_type = Column(String(16), nullable=False)  # 'pdf' | 'excel'
    date_from = Column(Date, nullable=True)
    date_to = Column(Date, nullable=True)
    status = Column(String(32), default="pending", nullable=False)  # pending/processing/completed/failed
    file_path = Column(String(512), nullable=True)  # 生成的文件路径
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
```

### 4.2 跨 schema 读 GEOFlow 的表

监测系统的 SQLAlchemy 模型跨 schema 查询 GEOFlow 的表（只读）：

```python
# index-monitor/app/models/geoflow_views.py
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey
from app.models.base import Base

class GeoflowArticle(Base):
    """GEOFlow 的 articles 表（只读视图）。"""
    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    title = Column(String(512))
    slug = Column(String(512))
    excerpt = Column(Text)
    content = Column(Text)  # 文章正文
    keywords = Column(Text)  # JSON 字符串，需解析
    meta_description = Column(Text)
    original_keyword = Column(String(255))
    status = Column(String(32))
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))

class GeoflowArticleDistribution(Base):
    """GEOFlow 的 article_distributions 表（只读视图）。"""
    __tablename__ = "article_distributions"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("public.articles.id"))
    distribution_channel_id = Column(Integer)
    action = Column(String(16))  # publish/update/delete
    status = Column(String(32))  # synced/failed/queued/sending
    remote_id = Column(String(255))
    remote_url = Column(String(512))
    remote_meta = Column(Text)  # JSON
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))

class GeoflowDistributionChannel(Base):
    """GEOFlow 的 distribution_channels 表（只读视图，用于显示渠道类型）。"""
    __tablename__ = "distribution_channels"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    channel_type = Column(String(64))  # geoflow_agent/wordpress_rest/generic_http_api
    domain = Column(String(255))
    status = Column(String(32))
```

**重要**：这些模型**不创建表**（表由 GEOFlow 的 Laravel migration 管理），只用于查询。在 Alembic 里标记为 `view=True` 或不生成迁移。

### 4.3 字段映射（查询时 JOIN）

监测系统查询分发记录时，跨 schema JOIN 获取完整信息：

```sql
SELECT
    d.id AS distribution_id,
    d.remote_url,
    d.action,
    d.status AS distribution_status,
    d.created_at AS distributed_at,
    a.title AS content_title,
    a.slug AS content_slug,
    a.excerpt AS content_excerpt,
    a.content AS content_body,
    a.keywords AS content_keywords_raw,
    a.meta_description,
    a.original_keyword,
    a.published_at,
    s.client_id,
    s.site_type,
    c.channel_type,
    c.name AS channel_name,
    -- 手动录入标记
    CASE WHEN m.id IS NOT NULL THEN 'manual' ELSE 'geoflow' END AS source,
    -- 关联收录检测
    ir.baidu_status, ir.toutiao_status, ir.sogou_status, ir.so360_status, ir.bing_status,
    -- 关联采信检测
    cr.citation_exact, cr.citation_total
FROM public.article_distributions d
JOIN public.articles a ON a.id = d.article_id
LEFT JOIN public.distribution_channels c ON c.id = d.distribution_channel_id
LEFT JOIN monitor.client_sites s ON s.domain = extract_domain(d.remote_url)
LEFT JOIN monitor.manual_distributions m ON m.remote_url = d.remote_url  -- 手动录入关联
LEFT JOIN monitor.index_results ir ON ir.url = d.remote_url
LEFT JOIN (SELECT url, COUNT(*) FILTER (WHERE hit_type='exact') AS citation_exact, COUNT(*) AS citation_total
           FROM monitor.citation_results GROUP BY url) cr ON cr.url = d.remote_url
WHERE d.status = 'synced' AND d.action != 'delete'
```

**keywords 格式处理**：GEOFlow 的 `articles.keywords` 存储格式需实现前验证（`SELECT keywords FROM public.articles LIMIT 5`），可能是 JSON 字符串或逗号分隔。查询后用 Python 解析为 array。

---

## 5. DistributionQueryService 实现

位置：`index-monitor/app/services/distribution_query.py`

### 5.1 domain → client_id 匹配（查询时 JOIN）

```python
class DistributionQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _extract_domain(url: str) -> str:
        """提取并标准化 domain：小写 + 去掉 www. 前缀。"""
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname or ""
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host

    async def list_distributions(
        self,
        client_id: str | None = None,
        source: str | None = None,
        status: str | None = None,
        include_manual: bool = True,
    ) -> list[dict]:
        """查询分发记录（跨 schema JOIN）。

        client_id 为 None 时返回所有客户（admin 权限）。
        source 为 'geoflow' / 'manual' / None（全部）。
        """
        results = []

        # 1. GEOFlow 推送的记录
        if source in (None, "geoflow"):
            geoflow_records = await self._query_geoflow_distributions(client_id, status)
            results.extend(geoflow_records)

        # 2. 手动录入的记录
        if include_manual and source in (None, "manual"):
            manual_records = await self._query_manual_distributions(client_id, status)
            results.extend(manual_records)

        # 按时间倒序
        results.sort(key=lambda x: x.get("distributed_at") or x.get("created_at") or "", reverse=True)
        return results

    async def _query_geoflow_distributions(self, client_id: str | None, status: str | None) -> list[dict]:
        """查 GEOFlow 的 article_distributions（跨 schema JOIN）。

        domain 匹配采用 Python 层处理（避免复杂 SQL 正则）：
        先查所有 client_sites 建立 domain→client_id 映射，再在 Python 层匹配。
        """
        # 1. 查 GEOFlow 分发记录 + 文章 + 渠道 + 收录结果
        query = (
            select(
                GeoflowArticleDistribution,
                GeoflowArticle,
                GeoflowDistributionChannel,
                IndexResult,
            )
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(GeoflowDistributionChannel, GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id)
            .outerjoin(IndexResult, IndexResult.url == GeoflowArticleDistribution.remote_url)
            .where(
                GeoflowArticleDistribution.status == "synced",
                GeoflowArticleDistribution.action != "delete",
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        result = await self.db.execute(query)
        rows = result.fetchall()

        # 2. 建立 domain → client_id 映射（一次查询）
        sites_result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        domain_map = {self._extract_domain(s.domain): (s.client_id, s.site_type) for s in sites_result.scalars().all()}

        # 3. 过滤：如果指定了 client_id，只保留匹配的记录
        # 4. 聚合采信统计
        urls = [row[0].remote_url for row in rows]
        citation_map = await self._aggregate_citations(urls)

        records = []
        for row in rows:
            dist, article, channel, index_result = row
            domain = self._extract_domain(dist.remote_url)
            matched = domain_map.get(domain)
            if matched is None:
                continue  # domain 未登记，跳过（可记日志告警）
            cid, site_type = matched
            if client_id and cid != client_id:
                continue  # 客户过滤
            records.append(self._serialize_geoflow(dist, article, channel, index_result, cid, site_type, citation_map))
        return records

    def _serialize_geoflow(self, dist, article, channel, index_result, client_id, site_type, citation_map) -> dict:
        """序列化 GEOFlow 分发记录 + 关联数据。"""
        import json
        # keywords 格式适配：JSON 字符串 → array
        keywords_raw = article.keywords if article else None
        if isinstance(keywords_raw, str):
            try:
                keywords = json.loads(keywords_raw)
            except (json.JSONDecodeError, ValueError):
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        else:
            keywords = keywords_raw or []

        url = dist.remote_url
        citation = citation_map.get(url)
        return {
            "id": str(dist.id),
            "source": "geoflow",
            "client_id": client_id,
            "site_type": site_type,
            "remote_url": url,
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
            "citation_status": "cited" if citation and citation.get("exact", 0) > 0 else ("not_cited" if citation else "pending"),
            "citation_exact": citation.get("exact", 0) if citation else 0,
            "citation_total": citation.get("total", 0) if citation else 0,
        }

    async def _query_manual_distributions(self, client_id: str | None, status: str | None) -> list[dict]:
        """查手动录入的记录。"""
        query = select(ManualDistribution).where(ManualDistribution.status == "synced")
        if client_id:
            query = query.where(ManualDistribution.client_id == client_id)

        result = await self.db.execute(query)
        records = result.scalars().all()

        urls = [r.remote_url for r in records]
        index_map, citation_map = await self._aggregate_index_and_citation(urls)

        return [self._serialize_manual(r, index_map, citation_map) for r in records]

    # ... 序列化方法略
```

### 5.2 手动录入

```python
async def create_manual_distribution(
    self, remote_url: str, admin_id: str, client_id: str | None = None, note: str | None = None
) -> dict:
    """运营手动录入 URL。

    client_id 为 None 时自动匹配 domain。
    """
    if client_id is None:
        client_id, _ = await self._match_client_by_domain(remote_url)

    # 检查重复（手动表 + GEOFlow 表）
    existing_manual = await self.db.execute(
        select(ManualDistribution).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.remote_url == remote_url,
        )
    )
    if existing_manual.scalar_one_or_none():
        raise DistributionConflictError(f"URL 已存在（手动录入）：{remote_url}")

    # 检查 GEOFlow 是否已推送过
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
        created_by_admin_id=admin_id,
    )
    self.db.add(record)
    await self.db.commit()
    return {"action": "created", "client_id": client_id, "source": "manual"}
```

### 5.3 IndexChecker / CitationChecker 改造

现有 [index_checker.py:15-25](../../../index-monitor/app/services/index_checker.py) 和 [citation_checker.py:76-95](../../../index-monitor/app/services/citation_checker.py) 从 `article_distributions` 读 URL。改造为同时读 GEOFlow 的表 + 手动录入表：

```python
# index_checker.py 改造
async def get_pending_urls(self) -> List[Tuple[str, str]]:
    """获取待检测 URL：GEOFlow 分发记录 + 手动录入记录。"""
    # 1. GEOFlow 分发记录（跨 schema 查询）
    geoflow_result = await self.db.execute(
        select(GeoflowArticleDistribution.remote_url, ClientSite.client_id)
        .outerjoin(ClientSite, ClientSite.domain == <domain_expr>)
        .where(
            GeoflowArticleDistribution.status == "synced",
            GeoflowArticleDistribution.action != "delete",
        )
    )
    distributed = {row[0]: row[1] for row in geoflow_result.fetchall()}

    # 2. 手动录入记录
    manual_result = await self.db.execute(
        select(ManualDistribution.remote_url, ManualDistribution.client_id)
        .where(ManualDistribution.status == "synced")
    )
    for row in manual_result.fetchall():
        distributed.setdefault(row[0], row[1])  # GEOFlow 优先

    # 3. 已检测的 URL
    result = await self.db.execute(select(IndexResult.url))
    checked_urls = {row[0] for row in result.fetchall()}

    return [(url, cid) for url, cid in distributed.items() if url not in checked_urls]
```

---

## 6. 鉴权设计

### 6.1 客户登录：现有 client JWT（无需改动）

复用 [deps.py:7-12](../../../index-monitor/app/api/deps.py) 的 `get_current_client_id`。客户登录后按 client_id 过滤数据。

### 6.2 管理员登录：admin JWT（新增）

```python
# index-monitor/app/api/deps.py 新增
async def get_current_admin(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> Admin:
    payload = decode_token(token)
    if payload.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    admin_id = payload.get("sub")
    result = await db.execute(select(Admin).where(Admin.id == admin_id, Admin.status == "active"))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=401, detail="管理员账号不存在或已禁用")
    return admin

async def get_current_super_admin(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> Admin:
    admin = await get_current_admin(token, db)
    if admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin

async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> tuple[Admin | Client, str]:
    """统一入口：返回 (user, role)。调用方根据 role 判断权限。"""
    payload = decode_token(token)
    role = payload.get("role", "client")
    if role in ("admin", "super_admin"):
        admin = await get_current_admin(token, db)
        return admin, role
    # client
    result = await db.execute(select(Client).where(Client.client_id == payload.get("sub")))
    client = result.scalar_one_or_none()
    if not client or client.status != "active":
        raise HTTPException(status_code=401, detail="客户账号不存在或已禁用")
    return client, "client"
```

### 6.3 admin 登录端点

```python
@router.post("/admin/auth/login")
async def admin_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Admin).where(Admin.username == req.username))
    admin = result.scalar_one_or_none()
    if not admin or not verify_password(req.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if admin.status != "active":
        raise HTTPException(status_code=403, detail="账号已禁用")
    admin.last_login_at = func.now()
    await db.commit()
    token = create_access_token({"sub": str(admin.id), "role": admin.role})
    return {"access_token": token, "token_type": "bearer", "role": admin.role}
```

---

## 7. 管理员端点清单

新增 `index-monitor/app/api/admin_routes.py`，前缀 `/api/v1/admin`：

| 方法 | 路径 | 鉴权 | 功能 |
|---|---|---|---|
| POST | `/admin/auth/login` | 公开 | admin 登录 |
| GET | `/admin/clients` | admin | 客户列表（分页、搜索） |
| POST | `/admin/clients` | admin | 创建客户账号 |
| PUT | `/admin/clients/{id}` | admin | 更新客户（密码重置、状态） |
| GET | `/admin/client_sites` | admin | 站点列表 |
| POST | `/admin/client_sites` | admin | 登记站点（domain 自动标准化去 www） |
| PUT | `/admin/client_sites/{id}` | admin | 更新站点 |
| DELETE | `/admin/client_sites/{id}` | admin | 删除站点（软删除） |
| GET | `/admin/distributions` | admin | 所有分发记录（跨客户） |
| POST | `/distributions` | admin | 手动录入 URL |
| DELETE | `/distributions/{id}` | admin | 删除手动录入的 URL |
| POST | `/admin/admins` | super_admin | 创建 admin 账号 |
| PUT | `/admin/admins/{id}` | super_admin | 禁用/启用 admin |
| GET | `/admin/admins` | super_admin | admin 账号列表 |
| POST | `/admin/exports` | admin/client | 创建导出任务 |
| GET | `/admin/exports/{id}/download` | admin/client | 下载导出文件 |

**客户站点 domain 标准化**（admin 写入时去 www）：
```python
@router.post("/admin/client_sites")
async def create_client_site(payload: ClientSitePayload, admin = Depends(get_current_admin), db = ...):
    domain = DistributionQueryService._extract_domain(payload.domain)
    existing = await db.execute(select(ClientSite).where(ClientSite.domain == domain))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"域名 {domain} 已被其他客户登记")
    site = ClientSite(client_id=payload.client_id, domain=domain, ...)
    db.add(site)
    await db.commit()
    return {"id": str(site.id), "domain": domain}
```

---

## 8. 监测触发机制

### 8.1 不自动触发

推送/录入后**不自动触发**检测。原因：
- 收录检测有延迟（搜索引擎需要时间收录新文章）
- AI 采信检测成本高（调用 DeepSeek + 多个引用检测模型）

### 8.2 两种触发方式

**手动触发**（现有 [routes.py:137-156](../../../index-monitor/app/api/routes.py)）：
- `POST /scan/trigger/index` / `POST /scan/trigger/citation`

**定时触发**（新增 APScheduler）：
- 每日凌晨 02:00 定时检测所有 `status='synced'` 且超过 24h 的 URL

```python
# index-monitor/app/services/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("cron", hour=2, minute=0)
async def daily_index_check():
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()
```

---

## 9. 监测结果导出（PDF/Excel）

### 9.1 导出类型

| 格式 | 用途 | 技术栈 |
|---|---|---|
| Excel | 明细数据导出（收录明细、采信明细），运营分析用 | `openpyxl` |
| PDF | 完整报告（含图表、摘要），客户给老板看 | `weasyprint`（HTML→PDF） |

### 9.2 导出报表内容

**Excel 报表**（多 sheet）：
- Sheet 1「分发记录」：URL、标题、来源、客户、渠道、发布时间
- Sheet 2「收录检测」：URL、百度/头条/搜狗/360/必应状态、检测时间
- Sheet 3「AI 采信」：URL、模型、问题、命中类型、检测时间
- Sheet 4「汇总统计」：总分发数、收录率、采信率、各引擎收录数

**PDF 报告**（HTML 模板 → PDF）：
- 封面：客户名、报告周期、生成时间
- 摘要：收录率、采信率、趋势
- 图表：ECharts 截图（前端生成 PNG 后嵌入）或 matplotlib 生成
- 明细表：关键 URL 的收录和采信详情
- 结论建议

### 9.3 实现方案

**异步导出**（避免大文件阻塞 API）：
1. 客户/admin 点击"导出" → `POST /admin/exports` 创建 `export_tasks` 记录
2. 后台任务处理（APScheduler 或 BackgroundTasks）：
   - 查询数据
   - 生成文件（openpyxl / weasyprint）
   - 保存到 `/app/exports/{task_id}.xlsx`
   - 更新 `export_tasks.status = 'completed'`
3. 用户轮询 `GET /admin/exports/{id}` 获取状态
4. 完成后 `GET /admin/exports/{id}/download` 下载

```python
# index-monitor/app/services/export_service.py
class ExportService:
    async def create_excel(self, task: ExportTask, db: AsyncSession) -> str:
        wb = openpyxl.Workbook()
        distributions = await DistributionQueryService(db).list_distributions(task.client_id)

        # Sheet 1: 分发记录
        ws1 = wb.active
        ws1.title = "分发记录"
        ws1.append(["URL", "标题", "来源", "客户", "渠道", "渠道类型", "发布时间", "收录状态", "采信状态"])
        for d in distributions:
            ws1.append([
                d["remote_url"], d["content_title"], d["source"], d["client_id"],
                d.get("channel_name"), d.get("channel_type"), d.get("published_at"),
                d.get("index_status", {}).get("baidu"), d.get("citation_status"),
            ])

        # Sheet 2: 收录检测明细
        ws2 = wb.create_sheet("收录检测")
        ws2.append(["URL", "百度", "头条", "搜狗", "360", "必应", "最后检测时间"])
        for d in distributions:
            idx = d.get("index_status", {})
            ws2.append([d["remote_url"], idx.get("baidu"), idx.get("toutiao"), idx.get("sogou"), idx.get("so360"), idx.get("bing"), d.get("distributed_at")])

        # Sheet 3: AI 采信明细（查 citation_results 原始记录）
        ws3 = wb.create_sheet("AI采信")
        ws3.append(["URL", "模型", "问题", "命中类型", "检测时间"])
        urls = [d["remote_url"] for d in distributions]
        citations = await db.execute(
            select(CitationResult).where(CitationResult.url.in_(urls)).order_by(CitationResult.checked_at.desc())
        )
        for c in citations.scalars().all():
            ws3.append([c.url, c.model, c.question, c.hit_type, c.checked_at.isoformat() if c.checked_at else None])

        # Sheet 4: 汇总统计
        ws4 = wb.create_sheet("汇总统计")
        total = len(distributions)
        indexed = sum(1 for d in distributions if any(v == "indexed" for v in d.get("index_status", {}).values()))
        cited = sum(1 for d in distributions if d.get("citation_status") == "cited")
        ws4.append(["指标", "数值"])
        ws4.append(["总分发数", total])
        ws4.append(["已收录数", indexed])
        ws4.append(["收录率", f"{indexed/total*100:.1f}%" if total else "0%"])
        ws4.append(["AI采信数", cited])
        ws4.append(["采信率", f"{cited/total*100:.1f}%" if total else "0%"])

        file_path = f"/app/exports/{task.id}.xlsx"
        wb.save(file_path)
        return file_path

    async def create_pdf(self, task: ExportTask, db: AsyncSession) -> str:
        distributions = await DistributionQueryService(db).list_distributions(task.client_id)
        # 渲染 HTML 模板（含封面/摘要/图表占位/明细表）
        html = render_template("report.html", distributions=distributions, task=task,
                               summary=self._calc_summary(distributions))
        file_path = f"/app/exports/{task.id}.pdf"
        weasyprint.HTML(string=html).write_pdf(file_path)
        return file_path

    def _calc_summary(self, distributions) -> dict:
        total = len(distributions)
        indexed = sum(1 for d in distributions if any(v == "indexed" for v in d.get("index_status", {}).values()))
        cited = sum(1 for d in distributions if d.get("citation_status") == "cited")
        return {"total": total, "indexed": indexed, "cited": cited,
                "index_rate": indexed/total if total else 0, "citation_rate": cited/total if total else 0}
```

### 9.4 前端导出交互

```vue
<!-- dashboard/src/views/Distributions.vue -->
<template>
  <el-button type="primary" @click="showExportDialog = true">
    <el-icon><Download /></el-icon> 导出报告
  </el-button>

  <el-dialog v-model="showExportDialog" title="导出报告">
    <el-form>
      <el-form-item label="格式">
        <el-radio-group v-model="exportForm.type">
          <el-radio label="excel">Excel 明细</el-radio>
          <el-radio label="pdf">PDF 报告</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="时间范围">
        <el-date-picker v-model="exportForm.dateRange" type="daterange" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="showExportDialog = false">取消</el-button>
      <el-button type="primary" @click="submitExport">生成报告</el-button>
    </template>
  </el-dialog>
</template>
```

---

## 10. 多渠道分发扩展

### 10.1 现有渠道支持

GEOFlow 已支持 3 种渠道类型（[DistributionChannel.php:418-423](../../../GEOFlow-main/app/Models/DistributionChannel.php)）：
- `geoflow_agent`：GEOFlow 自有代理
- `wordpress_rest`：WordPress REST API
- `generic_http_api`：通用 HTTP API

### 10.2 本期实现范围

**监测系统侧**（本期做）：
- domain 匹配逻辑适配所有渠道类型（`generic_http_api` 的 remote_url 格式可能多样）
- 导出报表显示渠道类型
- dashboard 列表显示渠道名称

**GEOFlow 侧**（本期做框架，具体 publisher 后续）：
- 文档说明如何新增渠道 publisher
- `generic_http_api` 渠道配置示例（适配有 API 的平台）

### 10.3 新增渠道 publisher 的步骤（GEOFlow 侧）

1. 在 [DistributionChannel.php](../../../GEOFlow-main/app/Models/DistributionChannel.php) 的 `channelType()` 方法加新类型常量
2. 创建新 Publisher 类（继承现有 Publisher 基类），实现 `publish()`/`update()`/`delete()` 方法
3. 在 [DistributionPublisherManager.php](../../../GEOFlow-main/app/Services/GeoFlow/DistributionPublisherManager.php) 注册新 Publisher
4. 配置 `channel_config` 选项（API URL、认证方式等）

### 10.4 头条/知乎等平台调研（后续任务）

**难点**：各平台是否有公开的内容发布 API？

| 平台 | API 现状 | 可行性 |
|---|---|---|
| WordPress | REST API 完善 | ✅ 已支持 |
| 微信公众号 | 有素材管理 API，但受限 | ⚠️ 需调研 |
| 头条号 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |
| 知乎 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |
| 百家号 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |

**本期不实现爬虫方式发布**（法律风险）。仅支持有合法 API 的平台，通过 `generic_http_api` 适配。

---

## 11. Dashboard UI 设计规范（风格 A：专业数据中台）

### 11.1 技术栈

现有：Vue 3 + Element Plus + ECharts + Vite + Vuex + Vue Router。无新增前端依赖。

### 11.2 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│ [深色侧边栏 240px]  │  [顶部导航 64px]                       │
│                     │  面包屑 | 搜索 | 🔔 | 👤 用户 ▼        │
│  🌐 知氪AI监测       ├────────────────────────────────────────┤
│                     │                                        │
│  📊 数据总览         │  [内容区，浅色背景 #f5f7fa]            │
│  📝 分发记录         │                                        │
│  🔍 收录检测         │  ┌──────────────────────────────┐     │
│  📈 AI采信检测       │  │  统计卡片行（4 个卡片）       │     │
│  📋 检测报告         │  │  收录率 | 采信率 | 分发数 | 待检测 │
│  📤 导出报告         │  └──────────────────────────────┘     │
│  ⚙️ 系统设置         │                                        │
│                     │  ┌──────────────────────────────┐     │
│  ─────────          │  │  ECharts 折线图：收录趋势     │     │
│  站点筛选 ▼         │  │  （近 30 天）                 │     │
│   • zkeeeai.com     │  └──────────────────────────────┘     │
│   • blog.example    │                                        │
│                     │  ┌──────────────────────────────┐     │
│  ─────────          │  │  分发记录表格                 │     │
│  👤 客户切换 ▼      │  │  标题|URL|来源|渠道|收录|采信|操作│ │
│  (仅 admin 可见)    │  │  [导出报告] 按钮              │     │
│                     │  └──────────────────────────────┘     │
└─────────────────────┴────────────────────────────────────────┘
```

### 11.3 配色规范

```scss
// 侧边栏（深色）
$sidebar-bg: #001529;
$sidebar-text: #ffffff;
$sidebar-text-hover: #1890ff;
$sidebar-active: #1890ff;

// 内容区（浅色）
$content-bg: #f5f7fa;
$card-bg: #ffffff;
$border-color: #e8e8e8;

// 品牌色
$primary: #1890ff;
$success: #52c41a;       // 已收录/已采信
$warning: #faad14;       // 部分收录
$error: #f5222d;         // 未收录/失败

// 文字
$text-primary: #262626;
$text-secondary: #595959;
$text-tertiary: #8c8c8c;
```

### 11.4 组件规范

**统计卡片**：白色背景 + 圆角 8px + 柔和阴影 + 大数字 + 趋势箭头

**数据表格**：Element Plus Table + 状态标签
- 收录状态：`<el-tag type="success">已收录</el-tag>` / `<el-tag type="danger">未收录</el-tag>`
- 来源：`<el-tag type="info">GEOFlow</el-tag>` / `<el-tag type="warning">手动</el-tag>`

**图表**：ECharts 折线图（收录趋势）、饼图（采信分布）、柱状图（各搜索引擎收录对比）

### 11.5 登录页设计

```
┌─────────────────────────────────────────────────────────────┐
│                    │                                         │
│  [左侧品牌区 50%]  │  [右侧登录表单 50%]                    │
│                    │                                         │
│   渐变背景         │           知氪AI全链路监测平台          │
│   #1890ff →        │                                         │
│   #0050b3          │           欢迎登录                      │
│                    │                                         │
│   🌐 知氪AI        │   ┌─────────────────────────────┐      │
│   全链路监测平台    │   │ 👤 用户名                    │      │
│                    │   └─────────────────────────────┘      │
│   GEO + SEO        │   ┌─────────────────────────────┐      │
│   一站式优化        │   │ 🔒 密码                      │      │
│                    │   └─────────────────────────────┘      │
│                    │                                         │
│                    │   ┌─────────────────────────────┐      │
│                    │   │        登  录               │      │
│                    │   └─────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

**登录页区分**：
- 客户登录：`/login`（client JWT）
- 管理员登录：`/admin/login`（admin JWT，含 role）
- 两个登录页共用相同视觉风格，路由和鉴权独立

### 11.6 客户多站点分组展示

- 侧边栏底部"站点筛选"下拉框，默认"全部站点"
- 选择具体站点后，所有数据按 `client_sites.domain` 或 `site_type` 过滤

---

## 12. 官网管理入口

### 12.1 入口设计

**官网首页（zkeeeai.com）添加入口**：

1. **顶部导航栏右侧**：「监测平台」链接 → `https://monitor.zkeeeai.com/login`（客户登录）
2. **底部页脚**：「管理员入口」链接 → `https://monitor.zkeeeai.com/admin/login`（管理员登录，低调放置）
3. **GEOFlow 后台菜单**：新增「监测系统」菜单项 → 新窗口打开 `https://monitor.zkeeeai.com`（你日常从 GEOFlow 后台跳转）

### 12.2 实现方式

**GEOFlow 前端**（zkeeeai.com）：
- 在模板文件加链接（Laravel blade 模板）
- 不需要鉴权，只是跳转链接

**dashboard 前端**（monitor.zkeeeai.com）：
- `/login` 客户登录页
- `/admin/login` 管理员登录页
- 登录后根据 role 跳转不同主页

---

## 13. 测试策略（TDD）

### 13.1 监测系统侧测试（pytest）

```
index-monitor/tests/
├── unit/
│   ├── test_domain_matcher.py
│   │   - test_extract_domain_strips_www
│   │   - test_extract_domain_lowercase
│   │   - test_match_client_by_domain_success
│   │   - test_match_client_by_domain_not_registered_raises
│   ├── test_distribution_query_service.py
│   │   - test_list_distributions_geoflow_only
│   │   - test_list_distributions_manual_only
│   │   - test_list_distributions_both_sources
│   │   - test_list_distributions_filtered_by_client
│   │   - test_list_distributions_includes_index_stats
│   │   - test_list_distributions_includes_citation_stats
│   ├── test_manual_distribution.py
│   │   - test_create_manual_distribution_success
│   │   - test_create_manual_duplicate_url_raises_409
│   │   - test_create_manual_url_exists_in_geoflow_raises_409
│   ├── test_admin_auth.py
│   │   - test_admin_login_returns_jwt_with_role
│   │   - test_super_admin_can_create_admin
│   │   - test_admin_cannot_create_admin
│   │   - test_disabled_admin_cannot_login
│   ├── test_export_service.py
│   │   - test_create_excel_generates_valid_file
│   │   - test_create_pdf_generates_valid_file
│   │   - test_export_task_status_transitions
│   │   - test_export_filters_by_date_range
│   └── test_cross_schema_query.py
│       - test_geoflow_article_distribution_readable
│       - test_join_geoflow_with_monitor_client_sites
│       - test_keywords_json_parsed_to_array
├── integration/
│   ├── test_distributions_endpoint.py
│   │   - test_admin_sees_all_distributions
│   │   - test_client_sees_only_own_distributions
│   │   - test_distributions_include_geoflow_and_manual
│   ├── test_admin_endpoints.py
│   │   - test_create_client_site_normalizes_domain
│   │   - test_create_client_site_duplicate_domain_returns_409
│   ├── test_export_endpoints.py
│   │   - test_create_export_task_returns_task_id
│   │   - test_download_completed_export
│   │   - test_download_pending_export_returns_409
│   └── test_manual_endpoint.py
│       - test_manual_create_requires_admin_auth
│       - test_manual_create_with_unregistered_domain_returns_400
└── e2e/
    └── test_unified_db_flow.py
        - test_geoflow_distribution_visible_to_index_checker
        - test_geoflow_distribution_visible_to_citation_checker
        - test_manual_distribution_visible_to_index_checker
        - test_deleted_geoflow_distribution_skipped
        - test_export_contains_both_geoflow_and_manual_records
```

### 13.2 端到端验证

```
deploy/scripts/test-unified-db-e2e.sh
```

验证步骤：
1. GEOFlow 发布文章到 WordPress → `public.article_distributions` 新增记录
2. 监测系统查询 `/distributions` → 看到 GEOFlow 推送的记录（跨 schema JOIN）
3. dashboard 用 admin 登录 → 看到所有分发记录
4. dashboard 用 client 登录 → 只看到自己 domain 的记录
5. 触发收录检测 → IndexChecker 读到 GEOFlow 的 URL
6. 触发 AI 采信检测 → CitationChecker 读到 GEOFlow 的 URL
7. GEOFlow 删除文章 → 监测系统查询时自动看不到（无需同步删除）
8. 运营手动录入 URL → 创建到 `monitor.manual_distributions`
9. 运营手动录入已存在的 URL → 409 冲突
10. 导出 Excel → 下载文件包含所有 sheet
11. 导出 PDF → 下载文件包含图表和摘要
12. 官网点击"监测平台" → 跳转到客户登录页
13. 官网点击"管理员入口" → 跳转到管理员登录页

---

## 14. 部署配置

### 14.1 新增配置项

遵循 project_memory 硬约束"API keys must not be hardcoded, use .env.prod"。

`.env.prod`（监测系统侧）：
```
# 改为连 GEOFlow 的 PG
POSTGRES_HOST=geoflow-postgres       # GEOFlow 的 PG 容器名
POSTGRES_PORT=5432
POSTGRES_DB=${GEOFLOW_DB_NAME}       # GEOFlow 的 database name
POSTGRES_USER=${GEOFLOW_DB_USER}
POSTGRES_PASSWORD=${GEOFLOW_DB_PASSWORD}
MONITOR_SCHEMA=monitor               # 监测系统的 schema 名
ADMIN_JWT_SECRET=<部署时生成>
```

### 14.2 依赖项安装

**监测系统侧 Python 依赖**（`index-monitor/requirements.txt` 新增）：
```
openpyxl>=3.1.0        # Excel 导出（第 9 节）
weasyprint>=60.0       # PDF 导出（第 9 节）
apscheduler>=3.10.0    # 定时任务（第 8 节）
```

**GEOFlow 侧 PHP 依赖**：无新增。

**Dashboard 前端依赖**：无新增（现有 Element Plus + ECharts 足够）。

### 14.3 docker-compose 变更

**docker-compose.prod.yml**：
- 删除 `postgres` 服务（geo-postgres，废弃）
- `index-monitor` 服务的 `POSTGRES_HOST` 改为 GEOFlow 的 PG 容器名
- `index-monitor` 加入 GEOFlow 的 docker network（或用 external network）
- 保留 `redis` 服务

**GEOFlow 的 docker-compose.yml**：
- 无变更（GEOFlow 不感知监测系统）
- 确保 PG 容器对监测系统容器可见（网络配置）

### 14.4 DB 迁移

**监测系统侧**（新建 Alembic 迁移）：
```bash
cd index-monitor
# 1. 创建 monitor schema
alembic revision -m "create monitor schema and migrate tables"
# 迁移内容：
#   - CREATE SCHEMA IF NOT EXISTS monitor;
#   - 所有监测系统表 ALTER SET SCHEMA monitor
#   - 新建 monitor.admins 表
#   - 新建 monitor.manual_distributions 表
#   - 新建 monitor.export_tasks 表
#   - client_sites.domain 加 UNIQUE 约束
alembic upgrade head
```

**GEOFlow 侧**：无 DB schema 变更。

### 14.5 数据迁移流程（生产环境）

1. 备份监测系统现有 PG（虽然表基本为空）
2. 在 GEOFlow 的 PG 创建 `monitor` schema
3. 运行监测系统的 Alembic 迁移（连 GEOFlow 的 PG）
4. 更新监测系统的 `.env.prod` 指向 GEOFlow 的 PG
5. 重启监测系统容器
6. 验证跨 schema 查询正常
7. 废弃监测系统的 `postgres:15-alpine` 容器

---

## 15. 实现顺序（TDD）

### Phase 1：数据库统一（基础）
1. 写 monitor schema 创建迁移 + 测试
2. 写监测系统表迁移到 monitor schema + 测试
3. 写跨 schema 查询模型（GeoflowArticle/Distribution/Channel）+ 测试
4. 改监测系统的 database.py 连接配置 + 测试
5. 本地验证跨 schema JOIN 查询

### Phase 2：鉴权与数据模型
6. 写 admins 表迁移 + 模型 + 测试
7. 写 manual_distributions 表迁移 + 模型 + 测试
8. 写 export_tasks 表迁移 + 模型 + 测试
9. 写 admin JWT 鉴权（登录 + get_current_admin + get_current_super_admin）+ 测试
10. 写 client_sites.domain UNIQUE 约束 + 测试

### Phase 3：核心查询服务
11. 写 DistributionQueryService._extract_domain + 测试
12. 写 DistributionQueryService._query_geoflow_distributions（跨 schema JOIN）+ 测试
13. 写 DistributionQueryService._query_manual_distributions + 测试
14. 写 DistributionQueryService.list_distributions（合并查询）+ 测试
15. 写 DistributionQueryService.create_manual_distribution + 测试

### Phase 4：IndexChecker/CitationChecker 改造
16. 改 IndexChecker.get_pending_urls 读 GEOFlow + 手动表 + 测试
17. 改 CitationChecker.get_pending_urls 读 GEOFlow + 手动表 + 测试
18. 验证收录检测和 AI 采信检测正常工作

### Phase 5：管理员端点
19. 写 admin 登录端点 + 测试
20. 写 admin 端点（clients/client_sites/distributions/admins）+ 测试
21. 写手动录入端点 POST /distributions + 测试
22. 写 domain 标准化（去 www）+ 测试

### Phase 6：监测结果导出
23. 写 ExportService.create_excel + 测试
24. 写 ExportService.create_pdf + 测试
25. 写导出端点（POST /admin/exports + GET download）+ 测试
26. 写导出任务后台处理 + 测试

### Phase 7：Dashboard 前端
27. 改造登录页（风格 A）+ 客户登录 / admin 登录
28. 改造数据总览页（统计卡片 + ECharts 图表）
29. 新增分发记录页（表格 + 收录/采信状态 + 来源标签）
30. 新增导出报告功能（导出对话框 + 下载）
31. 新增站点筛选 + 客户切换（admin）

### Phase 8：官网入口 + 定时任务 + 端到端
32. 官网首页加监测平台入口 + 管理员入口
33. GEOFlow 后台加监测系统菜单
34. 写定时收录检测任务
35. 写端到端测试脚本 `test-unified-db-e2e.sh`
36. 本地完整测试 → 云端部署 → 生产验证

---

## 16. 验收标准

1. 监测系统连 GEOFlow 的 PG，跨 schema 查询 `public.article_distributions` 正常
2. GEOFlow 发布文章 → 监测系统 `/distributions` 端点实时看到记录（无同步延迟）
3. GEOFlow 删除文章 → 监测系统查询时自动看不到（无需同步删除逻辑）
4. 运营 admin 登录 → 看到所有客户的所有分发记录
5. 客户 client 登录 → 只看到自己 client_id 下的分发记录
6. 运营手动录入 URL（domain 已登记）→ 创建成功，source='manual'
7. 运营手动录入 URL（domain 未登记）→ 400 错误
8. 运营手动录入已存在的 URL（GEOFlow 或手动）→ 409 冲突
9. IndexChecker 读取 GEOFlow + 手动录入的 URL 执行收录检测
10. CitationChecker 读取 GEOFlow + 手动录入的 URL 执行 AI 采信检测
11. 导出 Excel → 下载文件包含 4 个 sheet（分发记录/收录检测/AI 采信/汇总统计）
12. 导出 PDF → 下载文件包含封面/摘要/图表/明细表
13. 官网点击"监测平台" → 跳转客户登录页
14. 官网点击"管理员入口" → 跳转管理员登录页
15. GEOFlow 后台点击"监测系统" → 新窗口打开监测 dashboard
16. dashboard 风格 A（深色侧边栏 + 浅色内容区 + 统计卡片 + ECharts 图表）
17. 废弃监测系统的 `postgres:15-alpine` 容器，服务器节省 ~300MB 内存
18. 所有单元/集成测试通过
19. 端到端测试脚本 13 步全部通过

---

## 17. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 跨 schema JOIN 性能问题 | PostgreSQL 跨 schema 查询性能等同同 schema；必要时加索引 |
| GEOFlow 改 article_distributions 表结构影响监测系统 | 监测系统只读，且只依赖核心字段（id/remote_url/status/action/article_id）；表结构变更前协调 |
| 监测系统写入 monitor schema 影响 GEOFlow | schema 隔离，互不干扰 |
| 数据迁移过程停机 | 本地先验证迁移流程；生产选择低峰期；准备回滚方案（第 3.2 节） |
| GEOFlow PG 宕机导致监测系统不可用 | 监测系统依赖 GEOFlow 的 PG，需共同保障 PG 高可用；可后续做只读副本 |
| keywords 字段格式不一致 | 实现前先 `SELECT keywords FROM public.articles LIMIT 5` 验证，查询后 Python 解析 |
| 导出大文件阻塞 API | 异步导出 + export_tasks 状态跟踪 |
| weasyprint 系统依赖复杂 | Dockerfile 安装系统依赖（libpango, libjpeg 等）；或改用 reportlab |
| admin 账号被盗 | JWT 过期 7 天 + 禁用账号立即失效 + 操作日志审计 |
| 客户看到非自己 client_id 的数据 | 所有查询强制按 client_id 过滤 + admin/client 鉴权隔离 |
| docker network 配置错误导致容器无法通信 | 本地先验证网络配置；部署脚本检查容器连通性 |

---

## 18. 未来扩展点（不在本期实现）

1. **GEOFlow 后台嵌入监测 dashboard**：iframe + 一次性 token 鉴权（统一数据库后更简单，可直接跨 schema 查询）
2. **webhook 通知**：监测完成后通知客户（邮件/钉钉/企微）
3. **更多渠道 publisher**：微信公众号素材 API、其他有合法 API 的平台
4. **客户自助管理站点**：客户自己登记 domain（需 admin 审核）
5. **PG 只读副本**：监测系统查询走只读副本，避免影响 GEOFlow 写入
6. **实时监测**：WebSocket 推送检测结果到 dashboard（替代轮询）
