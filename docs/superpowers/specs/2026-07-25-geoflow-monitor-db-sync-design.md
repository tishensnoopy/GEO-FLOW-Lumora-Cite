# GEOFlow → 监测系统 DB 同步机制设计

- **创建日期**：2026-07-25
- **状态**：待实现
- **关联文档**：[2026-07-23-geo-monitoring-system-design.md](./2026-07-23-geo-monitoring-system-design.md)
- **实现分支**：`feat/monitor-db-sync`（基于 `feat/rebrand-dual-domain`）

---

## 1. 背景与目标

### 1.1 问题陈述

当前系统存在两个独立的 PostgreSQL 实例：

- **GEOFlow**（Laravel/PHP）：内容生产端，`article_distributions` 表记录文章分发到各渠道（WordPress 等）的状态。配置在 `GEOFlow-main/.env` 的 `DB_*` 变量。
- **监测系统**（FastAPI/Python，index-monitor + dashboard）：监测端，`article_distributions` 表已定义模型（[article.py:9-18](../../../index-monitor/app/models/article.py)）但**无数据**，因为没有接收入口。使用 [docker-compose.prod.yml](../../../docker-compose.prod.yml) 里的 `postgres` 容器（`geo-postgres`）。

两个 PG 实例完全不互通，导致 GEOFlow 分发成功的文章数据无法流入监测系统，[IndexChecker](../../../index-monitor/app/services/index_checker.py) 和 [CitationChecker](../../../index-monitor/app/services/citation_checker.py) 读到的 `article_distributions` 表是空的，收录检测和 AI 采信检测无法执行。

### 1.2 设计目标

1. 建立 GEOFlow → 监测系统的单向数据同步机制（article_distributions 表）
2. 支持运营手动录入 URL（不依赖 GEOFlow 推送）
3. 客户登录 dashboard 只看自己 client_id 下的数据（多租户隔离）
4. 补全管理员角色（你和同事登录管理所有客户数据）
5. 客户 dashboard UI 采用专业数据中台风格

### 1.3 非目标（YAGNI）

- 不做监测系统 → GEOFlow 的反向同步（本期仅预留扩展点）
- 不做双向实时同步
- 不引入消息队列（Kafka/RabbitMQ）
- 不做 PostgreSQL FDW 跨库直连

---

## 2. 架构总览

### 2.1 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│  GEOFlow (Laravel/PHP) — 独立 PG 实例 A                         │
│                                                                  │
│  ArticleDistribution (action=publish/update/delete)              │
│       │                                                          │
│       ▼                                                          │
│  ProcessArticleDistributionJob                                   │
│       │  发布成功后（status='synced'）                           │
│       ▼                                                          │
│  MonitorSyncClient::push($payload)   ← 新增服务                  │
│       │  HTTP POST + SYNC_API_TOKEN                              │
│       │  失败 → 复用现有 queue 重试 (attempt_count/next_retry_at) │
└───────┼──────────────────────────────────────────────────────────┘
        │
        │  HTTPS（https://monitor.zkeeeai.com），不依赖容器网络互通
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  监测系统 (FastAPI/Python) — 独立 PG 实例 B (geo-postgres)       │
│                                                                  │
│  POST /api/v1/distributions/sync       ← GEOFlow 推送入口        │
│  POST /api/v1/distributions/sync/batch ← 历史数据批量迁移        │
│       │  验证 SYNC_API_TOKEN                                     │
│       │  domain → client_id 匹配 (查 client_sites)               │
│       │  (client_id, remote_url) 唯一约束去重                     │
│       │  按 action 处理：publish/update/upsert, delete/软删除    │
│       ▼                                                          │
│  article_distributions (source='geoflow', 全量字段)              │
│       │                                                          │
│       ▼                                                          │
│  IndexChecker / CitationChecker  ← 现有逻辑无需改                │
│                                                                  │
│  POST /api/v1/distributions            ← 运营手动录入 (admin)     │
│  GET  /api/v1/distributions            ← 列表 (admin/client)      │
│  GET  /api/v1/admin/clients            ← 客户管理 (admin)         │
│  GET  /api/v1/admin/client_sites       ← 站点管理 (admin)         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 关键边界

- GEOFlow 只负责「推送」，不关心监测系统内部数据模型
- 监测系统只负责「接收 + 匹配 + 落库」，不反向查询 GEOFlow
- 两个 PG 实例完全不互通，只通过 HTTP 推送同步
- 推送走 HTTPS（`https://monitor.zkeeeai.com`），通过现有 nginx 暴露

---

## 3. 数据模型变更

### 3.1 监测系统侧：article_distributions 表扩展

在 [article.py:9-18](../../../index-monitor/app/models/article.py) 现有基础上扩展：

```python
class ArticleDistribution(Base):
    __tablename__ = "article_distributions"
    __table_args__ = (
        UniqueConstraint("client_id", "remote_url", name="uq_distributions_client_url"),
    )

    # 现有字段
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 新增：来源标识
    source = Column(String(16), nullable=False, default="manual", index=True)  # 'geoflow' | 'manual'
    geoflow_article_id = Column(String(64), nullable=True, index=True)  # GEOFlow Article.id 转 string
    geoflow_action = Column(String(16), nullable=True)  # 'publish' | 'update' | 'delete'，仅 geoflow 推送有

    # 新增：文章全量字段（GEOFlow 推送，手动录入可空）
    content_title = Column(String(512), nullable=True)
    content_slug = Column(String(512), nullable=True)
    content_excerpt = Column(Text, nullable=True)
    content_body = Column(Text, nullable=True)  # 文章正文 HTML/Markdown
    content_keywords = Column(ARRAY(Text), nullable=True)  # 复用 IndexResult 的 ARRAY(Text)
    meta_description = Column(Text, nullable=True)
    original_keyword = Column(String(255), nullable=True)
    site_type = Column(String(32), nullable=True)  # 从 client_sites.site_type 带过来
    published_at = Column(DateTime(timezone=True), nullable=True)
```

**status 取值**：`synced`（已同步，可监测）/ `deleted`（已删除，跳过监测）/ `failed`（推送失败，仅 geoflow 源可能）

### 3.2 监测系统侧：client_sites 表加 domain 唯一约束

[client.py:24-40](../../../index-monitor/app/models/client.py) 的 `ClientSite`：

```python
class ClientSite(Base):
    __tablename__ = "client_sites"
    __table_args__ = (
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),  # 现有
        UniqueConstraint("domain", name="client_sites_domain_unique_key"),  # 新增：一个 domain 只属于一个客户
    )
    # ... 其余字段不变
    domain = Column(String(255), nullable=False, index=True)  # 已有 index，保留
```

**业务约束**：一个 domain 只能属于一个客户。避免 domain 匹配时找到多个客户导致数据归属错误。

### 3.3 监测系统侧：新增 admins 表

```python
class Admin(Base):
    __tablename__ = "admins"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="admin", nullable=False)  # 'admin' | 'super_admin'
    status = Column(String(32), default="active", nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**两级 role**：
- `admin`：日常运营，可管理客户/站点/分发记录、手动录入 URL
- `super_admin`：可管理 admin 账号（创建/禁用其他 admin）

### 3.4 GEOFlow 侧：无表结构变更

复用现有 [ArticleDistribution](../../../GEOFlow-main/app/Models/ArticleDistribution.php) + [Article](../../../GEOFlow-main/app/Models/Article.php) 关联（[Article.php:92-95](../../../GEOFlow-main/app/Models/Article.php) 已有 `distributions()` 关系）。

### 3.5 字段映射（GEOFlow → 监测系统）

| GEOFlow 字段 | 监测系统字段 | 转换说明 |
|---|---|---|
| ArticleDistribution.id | — | 不直接映射，仅作推送日志 |
| ArticleDistribution.remote_url | remote_url | 直接映射 |
| ArticleDistribution.status | status | 'synced' → 'synced'；'failed' → 'failed' |
| ArticleDistribution.action | geoflow_action | 'publish'/'update'/'delete' 直接映射 |
| Article.id | geoflow_article_id | integer → string |
| Article.title | content_title | 直接映射 |
| Article.slug | content_slug | 直接映射 |
| Article.excerpt | content_excerpt | 直接映射 |
| Article.content | content_body | 直接映射（HTML/Markdown） |
| Article.keywords | content_keywords | **需确认格式**（JSON 字符串/array），实现前先 `SELECT keywords FROM articles LIMIT 5` 验证，在 `buildPayload()` 做 JSON decode → array 转换 |
| Article.meta_description | meta_description | 直接映射 |
| Article.original_keyword | original_keyword | 直接映射 |
| Article.published_at | published_at | Carbon → `toIso8601String()`（含时区） |
| (domain 匹配) | client_id | 从 remote_url 提取 domain 查 client_sites |
| (domain 匹配) | site_type | 从 client_sites.site_type 带过来 |
| (固定值) | source | 'geoflow' |

---

## 4. GEOFlow 侧推送实现

### 4.1 新增 MonitorSyncClient 服务

位置：`GEOFlow-main/app/Services/GeoFlow/MonitorSyncClient.php`

```php
class MonitorSyncClient
{
    public function __construct(
        private readonly string $apiUrl,      // config('geoflow.monitor_sync_api_url')
        private readonly string $apiToken,    // config('geoflow.monitor_sync_api_token')
        private readonly int $timeout = 10,
    ) {}

    /**
     * 推送分发记录到监测系统。
     * 失败时抛 MonitorSyncException，触发 queue 重试。
     */
    public function push(ArticleDistribution $distribution): void
    {
        $article = $distribution->article()->first();
        $payload = $this->buildPayload($distribution, $article);

        $response = Http::withToken($this->apiToken)
            ->timeout($this->timeout)
            ->post("{$this->apiUrl}/api/v1/distributions/sync", $payload);

        if ($response->failed()) {
            throw new MonitorSyncException(
                "推送失败: HTTP {$response->status()} - {$response->body()}"
            );
        }
    }

    private function buildPayload(ArticleDistribution $d, ?Article $a): array
    {
        $keywords = $a?->keywords;
        // keywords 格式适配：如果是 JSON 字符串先 decode，如果是逗号分隔字符串转 array
        if (is_string($keywords)) {
            $decoded = json_decode($keywords, true);
            $keywords = is_array($decoded) ? $decoded : array_filter(array_map('trim', explode(',', $keywords)));
        }
        $keywords = $keywords ?? [];

        // delete action 时 remote_url 可能为空（GEOFlow 删除分发时可能已清空 remote_url）。
        // 此时推送 geoflow_article_id 让监测系统按 article_id 软删除对应记录。
        // 监测系统 _handle_delete 优先按 remote_url 查找，回退到 geoflow_article_id。
        $remoteUrl = $d->remote_url;
        if (!$remoteUrl && $d->action !== 'delete') {
            throw new MonitorSyncException("非 delete action 的 remote_url 为空，无法推送");
        }

        return [
            'geoflow_article_id' => $a ? (string) $a->id : null,
            'remote_url' => $remoteUrl,  // delete 时可能为 null
            'status' => $d->status,
            'action' => $d->action,  // publish/update/delete
            'content_title' => $a?->title,
            'content_slug' => $a?->slug,
            'content_excerpt' => $a?->excerpt,
            'content_body' => $a?->content,
            'content_keywords' => $keywords,
            'meta_description' => $a?->meta_description,
            'original_keyword' => $a?->original_keyword,
            'published_at' => $a?->published_at?->toIso8601String(),
        ];
    }
}
```

### 4.2 修改 ProcessArticleDistributionJob

位置：[GEOFlow-main/app/Jobs/ProcessArticleDistributionJob.php](../../../GEOFlow-main/app/Jobs/ProcessArticleDistributionJob.php)

在 `process()` 方法末尾，发布成功（`status='synced'`）或 delete 完成后，调用推送：

```php
// 在 process() 末尾
if (in_array($distribution->status, ['synced', 'failed'], true)
    || $distribution->action === 'delete') {
    try {
        app(MonitorSyncClient::class)->push($distribution);
    } catch (MonitorSyncException $e) {
        // 记录失败信息，触发 queue 重试
        $distribution->last_error_message = $e->getMessage();
        $distribution->save();
        throw $e;  // queue 自动重试（复用现有 attempt_count/next_retry_at）
    }
}
```

### 4.3 历史数据批量迁移命令

新增 Artisan 命令：`GEOFlow-main/app/Console/Commands/SyncHistoryToMonitorCommand.php`

```php
class SyncHistoryToMonitorCommand extends Command
{
    protected $signature = 'geoflow:sync-monitor
        {--batch=100 : 每批处理数量}
        {--days= : 只同步最近 N 天的数据}
        {--dry-run : 只打印不推送}';

    public function handle(MonitorSyncClient $client): int
    {
        $query = ArticleDistribution::query()
            ->where('status', 'synced')
            ->where('action', '!=', 'delete')
            ->whereNotNull('remote_url');
        if ($this->option('days')) {
            $query->where('updated_at', '>=', now()->subDays((int) $this->option('days')));
        }
        $total = $query->count();
        $this->info("待同步：{$total} 条");
        $bar = $this->output->createProgressBar($total);
        $success = 0; $failed = 0;
        $query->chunkById((int) $this->option('batch'), function ($distributions) use ($client, $bar, &$success, &$failed) {
            foreach ($distributions as $distribution) {
                if ($this->option('dry-run')) {
                    $this->line("DRY-RUN: #{$distribution->id} {$distribution->remote_url}");
                    continue;
                }
                try {
                    $client->push($distribution);
                    $success++;
                } catch (\Throwable $e) {
                    $failed++;
                    $this->error("失败 #{$distribution->id}: {$e->getMessage()}");
                }
                $bar->advance();
            }
        });
        $bar->finish();
        $this->info("\n完成：成功 {$success}，失败 {$failed}");
        return $failed > 0 ? self::FAILURE : self::SUCCESS;
    }
}
```

### 4.4 配置项

`.env.prod`（GEOFlow 侧，遵循 project_memory 硬约束"API keys must not be hardcoded"）：
```
MONITOR_SYNC_API_URL=https://monitor.zkeeeai.com
MONITOR_SYNC_API_TOKEN=<部署时 openssl rand -hex 32 生成>
```

`config/geoflow.php` 新增：
```php
'monitor_sync_api_url' => env('MONITOR_SYNC_API_URL'),
'monitor_sync_api_token' => env('MONITOR_SYNC_API_TOKEN'),
```

---

## 5. 监测系统侧接收端点

### 5.1 POST /api/v1/distributions/sync（GEOFlow 推送入口）

```python
# index-monitor/app/api/routes.py 新增
from app.services.distribution_sync import DistributionSyncService, DomainNotRegisteredError

class DistributionSyncPayload(BaseModel):
    geoflow_article_id: str | None = None
    remote_url: str
    status: str = "synced"
    action: str = "publish"  # publish/update/delete
    content_title: str | None = None
    content_slug: str | None = None
    content_excerpt: str | None = None
    content_body: str | None = None
    content_keywords: list[str] | None = None
    meta_description: str | None = None
    original_keyword: str | None = None
    published_at: str | None = None

@router.post("/distributions/sync")
async def sync_distribution(
    payload: DistributionSyncPayload,
    token: str = Depends(verify_sync_token),
    db: AsyncSession = Depends(get_db),
):
    service = DistributionSyncService(db)
    try:
        result = await service.ingest_from_geoflow(payload)
    except DomainNotRegisteredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result
```

### 5.2 POST /api/v1/distributions/sync/batch（历史迁移）

```python
class BatchSyncPayload(BaseModel):
    distributions: list[DistributionSyncPayload]

@router.post("/distributions/sync/batch")
async def sync_batch(
    payload: BatchSyncPayload,
    token: str = Depends(verify_sync_token),
    db: AsyncSession = Depends(get_db),
):
    service = DistributionSyncService(db)
    results = []
    for item in payload.distributions:
        try:
            results.append(await service.ingest_from_geoflow(item))
        except DomainNotRegisteredError as e:
            results.append({"remote_url": item.remote_url, "error": str(e), "action": "failed"})
    return {"total": len(results), "results": results}
```

### 5.3 POST /api/v1/distributions（运营手动录入）

```python
class ManualDistributionPayload(BaseModel):
    remote_url: str
    # client_id 可选；不填则 domain 自动匹配；填了则用指定的（admin 可覆盖）

@router.post("/distributions")
async def manual_create_distribution(
    payload: ManualDistributionPayload,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = DistributionSyncService(db)
    try:
        result = await service.ingest_manual(payload.remote_url)
    except DomainNotRegisteredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DistributionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result
```

### 5.4 GET /api/v1/distributions（列表查询，JOIN 收录/采信状态）

```python
@router.get("/distributions")
async def list_distributions(
    requester = Depends(get_current_user),  # admin 看所有，client 看自己
    source: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    # 根据 requester 类型决定 client_id 过滤
    client_id = None if requester.role in ("admin", "super_admin") else requester.client_id
    service = DistributionSyncService(db)
    return await service.list_distributions(client_id=client_id, source=source, status=status)
```

**返回结构**（每条分发记录关联收录和采信统计）：
```python
[
    {
        "id": "...",
        "client_id": "...",
        "remote_url": "...",
        "source": "geoflow",
        "status": "synced",
        "content_title": "...",
        "content_excerpt": "...",
        "site_type": "official",
        "published_at": "...",
        "created_at": "...",
        # 关联收录状态（从 IndexResult 聚合）
        "index_status": {
            "baidu": "indexed", "toutiao": "not_indexed", ...
            "last_checked": "..."
        },
        # 关联采信状态（从 CitationResult 聚合）
        "citation_status": "cited",  # pending/cited/partial/not_cited
        "citation_exact": 2,
        "citation_total": 5,
    }
]
```

---

## 6. DistributionSyncService 实现

位置：`index-monitor/app/services/distribution_sync.py`

### 6.1 完整实现

```python
import logging
from urllib.parse import urlsplit
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import ArticleDistribution
from app.models.client import ClientSite
from app.models.index_result import IndexResult
from app.models.citation_result import CitationResult

logger = logging.getLogger(__name__)


class DomainNotRegisteredError(ValueError):
    pass


class DistributionConflictError(ValueError):
    pass


class DistributionSyncService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # 接收入口
    # ------------------------------------------------------------------

    async def ingest_from_geoflow(self, payload) -> dict:
        """GEOFlow 推送入口。处理 publish/update/delete 三种 action。"""
        if payload.action == "delete":
            return await self._handle_delete(payload)

        client_id, site_type = await self._match_client_by_domain(payload.remote_url)
        return await self._upsert(
            client_id=client_id,
            remote_url=payload.remote_url,
            source="geoflow",
            site_type=site_type,
            payload=payload,
        )

    async def ingest_manual(self, remote_url: str) -> dict:
        """运营手动录入入口。"""
        client_id, site_type = await self._match_client_by_domain(remote_url)
        try:
            return await self._upsert(
                client_id=client_id,
                remote_url=remote_url,
                source="manual",
                site_type=site_type,
                payload=None,
            )
        except IntegrityError:
            raise DistributionConflictError(f"URL 已存在：{remote_url}")

    # ------------------------------------------------------------------
    # delete 处理
    # ------------------------------------------------------------------

    async def _handle_delete(self, payload) -> dict:
        """delete action：软删除监测系统侧记录。"""
        if not payload.remote_url:
            # delete 时 remote_url 可能为空，按 geoflow_article_id 查找
            if not payload.geoflow_article_id:
                return {"action": "skipped", "reason": "no_identifier"}
            result = await self.db.execute(
                select(ArticleDistribution)
                .where(ArticleDistribution.geoflow_article_id == payload.geoflow_article_id)
            )
        else:
            result = await self.db.execute(
                select(ArticleDistribution)
                .where(ArticleDistribution.remote_url == payload.remote_url)
            )
        records = result.scalars().all()
        for record in records:
            record.status = "deleted"
            record.geoflow_action = "delete"
        await self.db.commit()
        return {"action": "deleted", "count": len(records)}

    # ------------------------------------------------------------------
    # domain → client_id 匹配
    # ------------------------------------------------------------------

    async def _match_client_by_domain(self, url: str) -> tuple[str, str]:
        """从 URL 提取 domain，查 client_sites 表匹配 client_id。

        domain 标准化：小写 + 去掉 www. 前缀。
        """
        domain = self._extract_domain(url)
        # client_sites.domain 存储时也标准化，两边一致
        result = await self.db.execute(
            select(ClientSite)
            .where(ClientSite.domain == domain, ClientSite.status == "active")
        )
        sites = result.scalars().all()
        if not sites:
            raise DomainNotRegisteredError(
                f"域名 '{domain}' 未在 client_sites 登记任一客户，"
                f"请先在管理后台 → 客户站点 中添加该域名。"
            )
        # 由于 client_sites.domain 有 UNIQUE 约束，最多只会有一个
        site = sites[0]
        return site.client_id, site.site_type

    @staticmethod
    def _extract_domain(url: str) -> str:
        """提取并标准化 domain：小写 + 去掉 www. 前缀。"""
        host = urlsplit(url).hostname or ""
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host

    # ------------------------------------------------------------------
    # 幂等 upsert
    # ------------------------------------------------------------------

    async def _upsert(self, client_id, remote_url, source, site_type, payload) -> dict:
        """按 (client_id, remote_url) 幂等 upsert。

        冲突策略：
        - manual 记录优先，geoflow 推送不覆盖 manual（除非 manual 主动 update）
        - geoflow → geoflow：更新内容字段
        - 无记录：创建
        """
        existing = await self.db.execute(
            select(ArticleDistribution)
            .where(
                ArticleDistribution.client_id == client_id,
                ArticleDistribution.remote_url == remote_url,
            )
        )
        record = existing.scalar_one_or_none()

        if record:
            # 冲突策略
            if record.source == "manual" and source == "geoflow":
                logger.info("跳过推送：URL 已被手动录入 %s", remote_url)
                return {"action": "skipped", "reason": "manual_record_exists", "client_id": client_id}
            if record.source == "manual" and source == "manual":
                raise DistributionConflictError(f"URL 已存在（手动录入）：{remote_url}")
            # 更新（geoflow → geoflow，或 manual 补充内容）
            self._apply_fields(record, payload, source, site_type)
            action = "updated"
        else:
            record = ArticleDistribution(
                client_id=client_id,
                remote_url=remote_url,
                source=source,
                site_type=site_type,
                status="synced",
            )
            self._apply_fields(record, payload, source, site_type)
            self.db.add(record)
            action = "created"

        try:
            await self.db.commit()
        except IntegrityError:
            # 并发竞态：UNIQUE 约束兜底，重试一次 upsert
            await self.db.rollback()
            return await self._upsert(client_id, remote_url, source, site_type, payload)

        return {"action": action, "client_id": client_id}

    def _apply_fields(self, record: ArticleDistribution, payload, source: str, site_type: str):
        """将 payload 内容字段应用到 record。"""
        record.site_type = site_type
        if payload:
            record.geoflow_article_id = payload.geoflow_article_id
            record.geoflow_action = payload.action
            record.content_title = payload.content_title
            record.content_slug = payload.content_slug
            record.content_excerpt = payload.content_excerpt
            record.content_body = payload.content_body
            record.content_keywords = payload.content_keywords
            record.meta_description = payload.meta_description
            record.original_keyword = payload.original_keyword
            if payload.published_at:
                # 时区一致性：保留 ISO8601 时区信息
                from datetime import datetime
                record.published_at = datetime.fromisoformat(payload.published_at.replace("Z", "+00:00"))
            record.status = payload.status if payload.status in ("synced", "failed") else "synced"
        if source == "manual" and record.source == "geoflow":
            record.source = "manual"  # 手动录入补充内容，source 升级为 manual

    # ------------------------------------------------------------------
    # 列表查询（JOIN 收录/采信状态）
    # ------------------------------------------------------------------

    async def list_distributions(
        self, client_id: str | None = None, source: str | None = None, status: str | None = None
    ) -> list[dict]:
        """列表查询，关联 IndexResult 和 CitationResult 聚合统计。"""
        query = select(ArticleDistribution).where(ArticleDistribution.status != "deleted")
        if client_id:
            query = query.where(ArticleDistribution.client_id == client_id)
        if source:
            query = query.where(ArticleDistribution.source == source)
        if status:
            query = query.where(ArticleDistribution.status == status)
        result = await self.db.execute(query.order_by(ArticleDistribution.created_at.desc()))
        records = result.scalars().all()

        if not records:
            return []

        urls = [r.remote_url for r in records]
        # 聚合收录状态
        index_result = await self.db.execute(
            select(IndexResult).where(IndexResult.url.in_(urls))
        )
        index_map = {r.url: r for r in index_result.scalars().all()}
        # 聚合采信状态
        from sqlalchemy import func
        citation_result = await self.db.execute(
            select(
                CitationResult.url,
                func.count().label("total"),
                func.count().filter(CitationResult.hit_type == "exact").label("exact"),
                func.max(CitationResult.checked_at).label("last_checked"),
            )
            .where(CitationResult.url.in_(urls))
            .group_by(CitationResult.url)
        )
        citation_map = {row.url: row for row in citation_result.fetchall()}

        return [self._serialize_with_stats(r, index_map, citation_map) for r in records]

    def _serialize_with_stats(self, record, index_map, citation_map) -> dict:
        index = index_map.get(record.remote_url)
        citation = citation_map.get(record.remote_url)
        citation_status = "pending"
        if citation:
            if citation.exact > 0:
                citation_status = "cited"
            elif citation.total > 0:
                citation_status = "not_cited"
        return {
            "id": str(record.id),
            "client_id": record.client_id,
            "remote_url": record.remote_url,
            "source": record.source,
            "status": record.status,
            "content_title": record.content_title,
            "content_excerpt": record.content_excerpt,
            "site_type": record.site_type,
            "published_at": record.published_at.isoformat() if record.published_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "index_status": {
                "baidu": index.baidu_status if index else "pending",
                "toutiao": index.toutiao_status if index else "pending",
                "sogou": index.sogou_status if index else "pending",
                "so360": index.so360_status if index else "pending",
                "bing": index.bing_status if index else "pending",
                "last_checked": max(
                    filter(None, [
                        index.baidu_checked_at if index else None,
                        index.toutiao_checked_at if index else None,
                    ])
                ).isoformat() if index else None,
            },
            "citation_status": citation_status,
            "citation_exact": citation.exact if citation else 0,
            "citation_total": citation.total if citation else 0,
        }
```

---

## 7. 鉴权设计

### 7.1 GEOFlow 推送：共享 API Token

```python
# index-monitor/app/api/deps.py 新增
from app.core.config import settings

async def verify_sync_token(authorization: str = Header(...)) -> str:
    """验证 GEOFlow 推送的 SYNC_API_TOKEN。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    token = authorization.removeprefix("Bearer ")
    if not settings.SYNC_API_TOKEN or token != settings.SYNC_API_TOKEN:
        raise HTTPException(status_code=401, detail="SYNC_API_TOKEN 无效")
    return token
```

### 7.2 运营手动录入：admin JWT

```python
# index-monitor/app/api/deps.py 新增
from app.models.admin import Admin

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
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Admin | Client:
    """统一入口：admin 或 client 都能通过，调用方根据类型判断。"""
    payload = decode_token(token)
    role = payload.get("role", "client")
    if role in ("admin", "super_admin"):
        return await get_current_admin(token, db)
    return await get_current_client(token, db)
```

### 7.3 客户查看：现有 client JWT

无需改动，复用现有 [deps.py:7-12](../../../index-monitor/app/api/deps.py) 的 `get_current_client_id`。

### 7.4 admin 登录端点

```python
# index-monitor/app/api/admin_routes.py 新增
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

## 8. 管理员端点清单

新增 `index-monitor/app/api/admin_routes.py`，前缀 `/api/v1/admin`：

| 方法 | 路径 | 鉴权 | 功能 |
|---|---|---|---|
| POST | `/admin/auth/login` | 公开 | admin 登录，返回 JWT（含 role） |
| GET | `/admin/clients` | admin | 客户列表（分页、搜索） |
| POST | `/admin/clients` | admin | 创建客户账号（生成 client_id） |
| PUT | `/admin/clients/{id}` | admin | 更新客户（密码重置、状态） |
| GET | `/admin/client_sites` | admin | 站点列表 |
| POST | `/admin/client_sites` | admin | 登记站点（domain 自动标准化去 www） |
| PUT | `/admin/client_sites/{id}` | admin | 更新站点 |
| DELETE | `/admin/client_sites/{id}` | admin | 删除站点（软删除） |
| GET | `/admin/distributions` | admin | 所有分发记录（跨客户，可按 client_id/source 过滤） |
| POST | `/distributions` | admin | 手动录入 URL（[5.3 节](#53-post-apiv1distributions运营手动录入)） |
| GET | `/admin/admins` | super_admin | admin 账号列表 |
| POST | `/admin/admins` | super_admin | 创建 admin 账号 |
| PUT | `/admin/admins/{id}` | super_admin | 禁用/启用 admin |

**客户站点登记 domain 标准化**（admin 写入时）：
```python
@router.post("/admin/client_sites")
async def create_client_site(payload: ClientSitePayload, admin = Depends(get_current_admin), db = ...):
    domain = DistributionSyncService._extract_domain(payload.domain)  # 标准化
    # 检查 domain UNIQUE
    existing = await db.execute(select(ClientSite).where(ClientSite.domain == domain))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"域名 {domain} 已被其他客户登记")
    site = ClientSite(client_id=payload.client_id, domain=domain, site_name=payload.site_name, ...)
    db.add(site)
    await db.commit()
    return {"id": str(site.id), "domain": domain}
```

---

## 9. 安全加固

### 9.1 推送端点限流

```python
# index-monitor/app/api/deps.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/distributions/sync")
@limiter.limit("100/minute")  # 防 GEOFlow 异常批量推送
async def sync_distribution(request: Request, ...):
    ...
```

### 9.2 请求体大小限制

```python
# index-monitor/app/main.py 或 nginx 配置
# FastAPI 层：限制 content_body 大小
# nginx 层：client_max_body_size 2m;
```

在 `DistributionSyncPayload` 校验：
```python
from pydantic import validator

class DistributionSyncPayload(BaseModel):
    ...
    @validator("content_body")
    def validate_body_size(cls, v):
        if v and len(v.encode("utf-8")) > 2_000_000:  # 2MB
            raise ValueError("content_body 超过 2MB 限制")
        return v
```

### 9.3 日志审计

```python
# 所有推送请求记录日志
logger.info(
    "sync_distribution: action=%s client_id=%s remote_url=%s source=geoflow result=%s",
    payload.action, result.get("client_id"), payload.remote_url, result.get("action")
)
```

---

## 10. 监测触发机制

### 10.1 不自动触发

推送后**不自动触发**收录检测和 AI 采信检测。原因：
- 收录检测有延迟（搜索引擎需要时间收录新文章，刚发布的 URL 检测必然 not_indexed，浪费资源）
- AI 采信检测成本高（调用 DeepSeek + 多个引用检测模型）

### 10.2 两种触发方式

**手动触发**（现有 [routes.py:137-156](../../../index-monitor/app/api/routes.py)）：
- 客户/运营在 dashboard 点击"检测"按钮
- `POST /scan/trigger/index` / `POST /scan/trigger/citation`

**定时触发**（新增）：
- 每日凌晨 02:00 定时检测所有 `status='synced'` 且超过 24h 的 URL
- 使用 APScheduler 或 cron + Artisan 命令

```python
# index-monitor/app/services/scheduler.py 新增
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("cron", hour=2, minute=0)
async def daily_index_check():
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()
```

---

## 11. 反向同步扩展点（预留，本期不实现）

本期不做监测系统 → GEOFlow 的反向同步。但预留扩展点：

**方案**：GEOFlow 后台通过 iframe 嵌入监测系统 dashboard
- GEOFlow 后台文章详情页加"查看监测"按钮
- 点击后 iframe 嵌入 `https://monitor.zkeeeai.com/embed/distributions?article_id={geoflow_article_id}`
- 监测系统新增 `/embed/distributions` 端点，支持按 geoflow_article_id 查询
- 鉴权：使用一次性 token 或共享 secret（避免暴露 client JWT）

**未来扩展**：如果需要 GEOFlow 后台显示监测数据摘要，监测系统可提供只读 API：
```
GET /api/v1/external/articles/{geoflow_article_id}/stats
  → { index_rate, citation_rate, last_checked }
```

---

## 12. Dashboard UI 设计规范（风格 A：专业数据中台）

### 12.1 技术栈

现有：Vue 3 + Element Plus + ECharts + Vite + Vuex + Vue Router

### 12.2 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│ [深色侧边栏 240px]  │  [顶部导航 64px]                       │
│                     │  面包屑 | 搜索 | 🔔 | 👤 客户A ▼      │
│  🌐 知氪AI监测       ├────────────────────────────────────────┤
│                     │                                        │
│  📊 数据总览         │  [内容区，浅色背景 #f5f7fa]            │
│  📝 分发记录         │                                        │
│  🔍 收录检测         │  ┌──────────────────────────────┐     │
│  📈 AI采信检测       │  │  统计卡片行（4 个卡片）       │     │
│  📋 检测报告         │  │  收录率 | 采信率 | 分发数 | 待检测 │ │
│  ⚙️ 系统设置         │  └──────────────────────────────┘     │
│                     │                                        │
│  ─────────          │  ┌──────────────────────────────┐     │
│  站点筛选 ▼         │  │  ECharts 折线图：收录趋势     │     │
│   • zkeeeai.com     │  │  （近 30 天）                 │     │
│   • blog.example    │  └──────────────────────────────┘     │
│                     │                                        │
│  ─────────          │  ┌──────────────────────────────┐     │
│  👤 客户切换 ▼      │  │  分发记录表格                 │     │
│  (仅 admin 可见)    │  │  标题|URL|来源|收录|采信|操作 │     │
│                     │  └──────────────────────────────┘     │
└─────────────────────┴────────────────────────────────────────┘
```

### 12.3 配色规范

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
$primary: #1890ff;       // Element Plus 默认蓝
$success: #52c41a;       // 已收录/已采信
$warning: #faad14;       // 部分收录
$error: #f5222d;         // 未收录/失败

// 文字
$text-primary: #262626;
$text-secondary: #595959;
$text-tertiary: #8c8c8c;
```

### 12.4 组件规范

**统计卡片**：白色背景 + 圆角 8px + 柔和阴影 + 大数字 + 趋势箭头
```vue
<el-card class="stat-card" shadow="hover">
  <div class="stat-label">收录率</div>
  <div class="stat-value">87%</div>
  <div class="stat-trend trend-up">↑ 5% 本周</div>
</el-card>
```

**数据表格**：Element Plus Table + 状态标签
- 收录状态：`<el-tag type="success">已收录</el-tag>` / `<el-tag type="danger">未收录</el-tag>` / `<el-tag type="warning">部分</el-tag>`
- 来源：`<el-tag type="info">GEOFlow</el-tag>` / `<el-tag type="warning">手动</el-tag>`

**图表**：ECharts 折线图（收录趋势）、饼图（采信分布）、柱状图（各搜索引擎收录对比）

### 12.5 登录页设计

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
│                    │                                         │
│                    │   忘记密码？                            │
└─────────────────────────────────────────────────────────────┘
```

**登录页区分**：
- 客户登录：`/login`（client JWT）
- 管理员登录：`/admin/login`（admin JWT，含 role）
- 两个登录页共用相同视觉风格，但路由和鉴权独立

### 12.6 客户多站点分组展示

- 侧边栏底部"站点筛选"下拉框，默认"全部站点"
- 选择具体站点后，所有数据按 `client_sites.site_type` 或 domain 过滤
- 统计卡片和图表跟随筛选更新

---

## 13. 错误监控告警

### 13.1 GEOFlow 侧

后台新增"同步失败记录"页面（admin 登录后可见）：
- 查询 `article_distributions WHERE last_error_message IS NOT NULL AND attempt_count >= 3`
- 显示：分发 ID、文章标题、remote_url、失败原因、最后尝试时间
- 提供"重新同步"按钮（重新 dispatch ProcessArticleDistributionJob）

### 13.2 监测系统侧

- 推送端点异常日志（5xx 错误）
- domain 未登记告警（统计未登记 domain，提示运营补登记）
- 接收量异常告警（推送量突增/突降）

---

## 14. 时区一致性

- GEOFlow `published_at`：Carbon datetime → `toIso8601String()` 输出 `2026-07-25T10:00:00+08:00`
- 监测系统解析：`datetime.fromisoformat(payload.published_at.replace("Z", "+00:00"))`，保留时区
- DB 存储：`DateTime(timezone=True)`，PostgreSQL 存储为 timestamptz
- 展示：前端用 dayjs 转换为用户本地时区显示

---

## 15. 测试策略（TDD）

遵循 project_memory 约束"测试先于实现"和用户偏好"TDD approach"。

### 15.1 监测系统侧测试（pytest）

```
index-monitor/tests/
├── unit/
│   ├── test_domain_matcher.py
│   │   - test_extract_domain_strips_www
│   │   - test_extract_domain_lowercase
│   │   - test_extract_domain_handles_no_host
│   │   - test_match_client_by_domain_success
│   │   - test_match_client_by_domain_not_registered_raises
│   │   - test_match_client_by_domain_inactive_site_ignored
│   ├── test_distribution_sync_service.py
│   │   - test_ingest_geoflow_publish_creates_new_record
│   │   - test_ingest_geoflow_update_existing_record
│   │   - test_ingest_geoflow_delete_soft_deletes_record
│   │   - test_ingest_geoflow_delete_by_article_id
│   │   - test_ingest_manual_creates_new_record
│   │   - test_upsert_skip_when_manual_exists_and_geoflow_push
│   │   - test_upsert_manual_overwrites_geoflow
│   │   - test_upsert_manual_conflict_raises_409
│   │   - test_concurrent_upsert_catches_integrity_error
│   │   - test_keywords_array_conversion
│   ├── test_sync_token_auth.py
│   │   - test_valid_token_passes
│   │   - test_missing_token_returns_401
│   │   - test_invalid_token_returns_401
│   ├── test_admin_auth.py
│   │   - test_admin_login_returns_jwt_with_role
│   │   - test_super_admin_can_create_admin
│   │   - test_admin_cannot_create_admin
│   │   - test_disabled_admin_cannot_login
│   └── test_payload_validation.py
│       - test_content_body_over_2mb_rejected
│       - test_action_delete_without_url_or_article_id_skipped
├── integration/
│   ├── test_sync_endpoint.py
│   │   - test_sync_creates_record_with_full_fields
│   │   - test_sync_domain_not_registered_returns_400
│   │   - test_sync_duplicate_url_idempotent
│   │   - test_sync_update_existing_record
│   │   - test_sync_delete_removes_record
│   │   - test_batch_sync_endpoint
│   ├── test_manual_endpoint.py
│   │   - test_manual_create_requires_admin_auth
│   │   - test_manual_create_with_unregistered_domain_returns_400
│   │   - test_manual_create_duplicate_url_returns_409
│   ├── test_distributions_list.py
│   │   - test_admin_sees_all_distributions
│   │   - test_client_sees_only_own_distributions
│   │   - test_distributions_include_index_and_citation_stats
│   └── test_admin_endpoints.py
│       - test_create_client_site_normalizes_domain
│       - test_create_client_site_duplicate_domain_returns_409
└── e2e/
    └── test_geoflow_to_monitor_sync.py
        - test_pushed_record_visible_to_index_checker
        - test_pushed_record_visible_to_citation_checker
        - test_deleted_record_skipped_by_index_checker
        - test_pushed_record_visible_in_dashboard_list
```

### 15.2 GEOFlow 侧测试（PHPUnit）

```
GEOFlow-main/tests/Unit/Services/GeoFlow/
├── MonitorSyncClientTest.php
│   - test_build_payload_includes_all_article_fields
│   - test_build_payload_converts_keywords_json_to_array
│   - test_build_payload_converts_keywords_comma_string_to_array
│   - test_push_success_when_monitor_returns_200
│   - test_push_throws_exception_on_4xx
│   - test_push_throws_exception_on_5xx
│   - test_push_throws_exception_on_timeout
└── ProcessArticleDistributionJobTest.php
    - test_job_calls_monitor_sync_when_status_synced
    - test_job_does_not_sync_when_status_queued
    - test_job_retries_on_sync_failure
    - test_job_delete_action_calls_sync

GEOFlow-main/tests/Feature/Console/Commands/
└── SyncHistoryToMonitorCommandTest.php
    - test_command_syncs_history_in_batches
    - test_command_dry_run_does_not_push
    - test_command_respects_days_option
```

### 15.3 端到端验证（手动 + 脚本）

```
deploy/scripts/test-db-sync-e2e.sh
```

验证步骤：
1. GEOFlow 后台发布文章到 WordPress → status='synced'
2. 验证监测系统 article_distributions 表新增记录（source='geoflow'，字段完整）
3. dashboard 用 admin 登录 → 看到该分发记录
4. dashboard 用 client 登录（对应 domain）→ 看到该分发记录
5. 触发收录检测 → IndexChecker 读到该 URL
6. 触发 AI 采信检测 → CitationChecker 读到该 URL
7. GEOFlow 更新文章内容重新发布 → 监测系统记录被更新
8. GEOFlow 删除文章 → 监测系统记录 status='deleted'，IndexChecker 跳过
9. 运营手动录入同一 URL → 409 冲突提示
10. 运营手动录入新 URL（domain 已登记）→ 创建成功，source='manual'
11. 运营手动录入新 URL（domain 未登记）→ 400 错误提示
12. 历史数据迁移：`php artisan geoflow:sync-monitor --days=30` → 监测系统批量接收

---

## 16. 部署配置

### 16.1 新增配置项

遵循 project_memory 硬约束"API keys must not be hardcoded, use .env.prod"。

`.env.prod`（GEOFlow 侧）：
```
MONITOR_SYNC_API_URL=https://monitor.zkeeeai.com
MONITOR_SYNC_API_TOKEN=<部署时 openssl rand -hex 32 生成>
```

`.env.prod`（监测系统侧）：
```
SYNC_API_TOKEN=<与 GEOFlow 侧 MONITOR_SYNC_API_TOKEN 相同>
ADMIN_JWT_SECRET=<部署时生成，可与 client JWT_SECRET 相同或独立>
```

### 16.2 依赖项安装

**监测系统侧 Python 依赖**（`index-monitor/requirements.txt` 新增）：
```
slowapi>=0.1.9        # 限流（第 9.1 节）
apscheduler>=3.10.0   # 定时任务（第 10.2 节）
```

**GEOFlow 侧 PHP 依赖**：无新增（`laravel/http` 已内置，现有项目已有 HTTP 客户端）。

**Dashboard 前端依赖**：无新增（现有 Element Plus + ECharts 足够，仅需定制主题）。

部署脚本需在 `pip install -r requirements.txt` 步骤后确保新依赖被安装。

### 16.3 部署脚本更新

- `deploy/scripts/deploy-geoflow.sh`：注入 `MONITOR_SYNC_API_URL` + `MONITOR_SYNC_API_TOKEN`
- `deploy/scripts/deploy-lumora-cite.sh`：注入 `SYNC_API_TOKEN` + `ADMIN_JWT_SECRET`
- 两个 token 必须一致，部署脚本里用同一个变量源（避免不一致）

### 16.4 DB 迁移

**监测系统侧**（新建 Alembic 迁移）：
```bash
cd index-monitor
alembic revision --autogenerate -m "add sync fields to article_distributions, create admins table, add domain unique"
alembic upgrade head
```

迁移内容：
1. `article_distributions` 加字段：source, geoflow_article_id, geoflow_action, content_title, content_slug, content_excerpt, content_body, content_keywords, meta_description, original_keyword, site_type, published_at
2. `article_distributions` 加唯一约束：`uq_distributions_client_url (client_id, remote_url)`
3. 新建 `admins` 表
4. `client_sites` 加唯一约束：`client_sites_domain_unique_key (domain)`

**GEOFlow 侧**：无 DB schema 变更。

### 16.5 Docker 网络

- GEOFlow 推送走 HTTPS（`https://monitor.zkeeeai.com`），不依赖容器网络互通
- 监测系统接收端点通过现有 nginx 暴露（已有 nginx 配置）
- 无需修改 docker-compose.prod.yml 的网络配置

### 16.6 nginx 配置

现有 nginx 已配置 `monitor.zkeeeai.com` 路由到 index-monitor，无需改动。需确认：
- `client_max_body_size 2m;`（限制推送请求体大小）
- 限流配置（`limit_req_zone` 防 GEOFlow 异常批量推送）

---

## 17. 实现顺序（TDD）

遵循"测试先于实现"原则，按依赖顺序实现：

### Phase 1：监测系统侧基础（数据模型 + 鉴权）
1. 写 admins 表迁移 + 模型 + 测试
2. 写 article_distributions 扩展迁移 + 模型 + 测试
3. 写 client_sites.domain UNIQUE 约束迁移 + 测试
4. 写 admin JWT 鉴权（登录 + get_current_admin + get_current_super_admin）+ 测试
5. 写 SYNC_API_TOKEN 鉴权 + 测试

### Phase 2：监测系统侧核心服务
6. 写 DistributionSyncService._extract_domain + 测试
7. 写 DistributionSyncService._match_client_by_domain + 测试
8. 写 DistributionSyncService._upsert（publish/update）+ 测试
9. 写 DistributionSyncService._handle_delete + 测试
10. 写 DistributionSyncService.ingest_manual + 测试
11. 写 DistributionSyncService.list_distributions（JOIN 收录/采信）+ 测试

### Phase 3：监测系统侧端点
12. 写 POST /distributions/sync 端点 + 集成测试
13. 写 POST /distributions/sync/batch 端点 + 集成测试
14. 写 POST /distributions（手动录入）端点 + 集成测试
15. 写 GET /distributions 端点 + 集成测试
16. 写 admin 端点（clients/client_sites/distributions/admins）+ 集成测试
17. 写限流 + 请求体校验 + 日志审计

### Phase 4：GEOFlow 侧推送
18. 写 MonitorSyncClient::buildPayload + 测试（含 keywords 格式适配）
19. 写 MonitorSyncClient::push + 测试（成功/4xx/5xx/超时）
20. 修改 ProcessArticleDistributionJob 调用推送 + 测试
21. 写 SyncHistoryToMonitorCommand + 测试

### Phase 5：Dashboard 前端
22. 改造登录页（风格 A）+ 客户登录 / admin 登录
23. 改造数据总览页（统计卡片 + ECharts 图表）
24. 新增分发记录页（表格 + 收录/采信状态）
25. 新增站点筛选 + 客户切换（admin）

### Phase 6：定时任务 + 端到端
26. 写定时收录检测任务
27. 写端到端测试脚本 `test-db-sync-e2e.sh`
28. 本地完整测试 → 云端部署 → 生产验证

---

## 18. 验收标准

1. GEOFlow 发布文章到 WordPress → 监测系统 article_distributions 表新增记录，字段完整
2. GEOFlow 更新文章 → 监测系统记录被更新（content_body 等字段刷新）
3. GEOFlow 删除文章 → 监测系统记录 status='deleted'，IndexChecker/CitationChecker 跳过
4. 运营 admin 登录 → 看到所有客户的所有分发记录
5. 客户 client 登录 → 只看到自己 client_id 下的分发记录
6. 运营手动录入 URL（domain 已登记）→ 创建成功，source='manual'
7. 运营手动录入 URL（domain 未登记）→ 400 错误，提示先登记 domain
8. 运营手动录入已存在的 URL → 409 冲突提示
9. GEOFlow 推送失败 → queue 重试，重试耗尽后 GEOFlow 后台可见失败记录
10. dashboard 展示分发记录 + 收录状态 + 采信状态（JOIN 查询）
11. 历史数据迁移命令 `php artisan geoflow:sync-monitor` 执行成功
12. 所有单元/集成测试通过
13. 端到端测试脚本 12 步全部通过

---

## 19. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| GEOFlow 推送时监测系统宕机 | queue 重试 + 指数退避，重试耗尽后人工介入 |
| domain 未登记导致推送被拒 | 400 错误 + 日志告警，运营及时补登记 |
| content_body 过大压垮监测系统 | 2MB 请求体限制 + nginx client_max_body_size |
| 并发推送导致 UNIQUE 冲突 | IntegrityError 捕获 + 重试一次 upsert |
| keywords 字段格式不一致 | 实现前先 `SELECT keywords FROM articles LIMIT 5` 验证，buildPayload 做 JSON/string 双适配 |
| 历史数据量大导致迁移慢 | 分批 chunkById（每批 100）+ 进度条 + dry-run 预览 |
| admin 账号被盗 | JWT 过期时间 7 天 + 禁用账号立即失效 + 操作日志审计 |
| 客户看到非自己 client_id 的数据 | 所有查询强制按 client_id 过滤 + admin/client 鉴权隔离 |

---

## 20. 未来扩展点（不在本期实现）

1. **反向同步**：监测系统 → GEOFlow 推送监测结果摘要（收录率、采信率）
2. **GEOFlow 后台嵌入监测 dashboard**：iframe + 一次性 token 鉴权
3. ** webhook 通知**：监测完成后通知 GEOFlow 或客户（邮件/钉钉/企微）
4. **多渠道分发**：除了 WordPress，支持分发到头条、知乎等平台
5. **监测结果导出**：PDF/Excel 报告导出
6. **客户自助管理站点**：客户自己登记 domain（需 admin 审核）
