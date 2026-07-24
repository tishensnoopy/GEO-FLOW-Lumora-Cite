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
2. **SSO 单点登录**：admin 通过 GEOFlow 单点登录，客户独立登录（一套账号管理两个系统）
3. **客户账户全生命周期**：创建/编辑/停用/软删除/恢复
4. **操作审计日志**：记录 admin 的所有操作，可追溯
5. **手动 URL 录入**：支持运营手动录入 URL（不依赖 GEOFlow 分发）
6. **监测结果导出**：Playwright 生成高质量 PDF 报告 + openpyxl Excel 明细
7. **批量触发检测**：admin 可批量触发收录/采信检测
8. **多渠道分发扩展**：统一数据库后任意渠道自动可见，为头条/知乎等平台预留 publisher 框架
9. **客户 dashboard**：采用专业数据中台风格（风格 A），丰富图表
10. **官网管理入口**：在官网添加管理员/客户登录入口

### 1.3 非目标（YAGNI）

- 不做监测系统 → GEOFlow 的反向同步（统一数据库后天然可见）
- 不做头条/知乎 publisher 的完整实现（本期只做框架 + generic_http_api 适配）
- 不引入消息队列
- 不做 PostgreSQL FDW（同一 PG 内跨 schema 查询不需要 FDW）
- 不做批量导入 CSV/Excel（本期只支持单条手动录入 + GEOFlow 自动同步）
- 不做客户自助录入 URL（仅 admin 录入）
- 不做四级以上权限粒度（admin/super_admin 两级够用）

---

## 2. 架构总览

### 2.1 统一数据库架构

```
┌─────────────────────────────────────────────────────────────────┐
│  单一 PostgreSQL 实例（pgvector/pgvector:pg16）                  │
│                                                                  │
│  public schema（GEOFlow 读写）                                   │
│   ├── users                             ← SSO 认证读取           │
│   ├── articles                          ← 监测系统只读 JOIN       │
│   ├── article_distributions             ← 监测系统只读 JOIN       │
│   ├── distribution_channels             ← 监测系统只读            │
│   └── ...（GEOFlow 现有所有表）                                  │
│                                                                  │
│  monitor schema（监测系统读写）                                  │
│   ├── clients                           ← 客户账号               │
│   ├── client_sites                      ← 客户站点（domain 映射）│
│   ├── manual_distributions              ← 手动录入的 URL         │
│   ├── admin_audit_logs                  ← 操作审计日志           │
│   ├── index_results                     ← 收录检测结果           │
│   ├── citation_results                  ← AI 采信检测结果        │
│   ├── system_config                     ← 系统配置               │
│   └── export_tasks                      ← 导出任务记录           │
└─────────────────────────────────────────────────────────────────┘
        ▲                              ▲
        │                              │
┌───────┴──────────┐          ┌────────┴──────────────────────┐
│  GEOFlow          │          │  监测系统 (index-monitor)      │
│  (Laravel/PHP)    │          │  (FastAPI/Python)              │
│  连 public schema │          │  读 public + 读写 monitor     │
│  写 articles 等   │  SSO     │  跨 schema JOIN 查询           │
│  管理员认证源     │ ───────> │  admin 通过 SSO 登录           │
└───────────────────┘          └────────────────────────────────┘
```

**关键变更**：不建 `monitor.admins` 表。admin 信息从 GEOFlow 的 `public.users` 表获取，通过 SSO 机制登录监测系统。

### 2.2 关键边界

- **GEOFlow**：只读写 `public` schema，不感知 `monitor` schema 存在；作为 SSO 身份提供者（IdP）
- **监测系统**：读 `public` schema（只读 GEOFlow 数据，含 users 表用于 SSO），读写 `monitor` schema（自己的表）；作为 SSO 服务提供者（SP）
- **数据一致性**：天然保证（同一 PG，同一事务可见性）
- **多渠道自动可见**：无论 GEOFlow 分发到哪个渠道（WordPress/头条/知乎/generic_http_api），只要 `article_distributions.status='synced'`，监测系统跨 schema 查询即可见，**无需为每个渠道设计同步机制**

### 2.3 数据流

```
GEOFlow 发布文章 → 写 public.article_distributions (status='synced')
（任意渠道：WordPress/头条/知乎/generic_http_api）
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
admin SSO 登录 → 操作审计日志 → 触发检测（单个/批量）
                          │
                          ▼
IndexChecker / CitationChecker 执行检测 → 写 monitor.index_results / monitor.citation_results
                          │
                          ▼
客户/管理员看 dashboard（风格 A，丰富图表）→ 导出报告（Playwright PDF / Excel）
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

**不建 admins 表**——admin 信息从 GEOFlow 的 `public.users` 表获取（SSO 机制，见第 5 节）。

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
    created_by_admin_id = Column(Integer, nullable=True)  # GEOFlow users.id
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

**新建 admin_audit_logs 表**（操作审计日志）：

```python
# index-monitor/app/models/admin_audit_log.py
class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = {"schema": "monitor"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_user_id = Column(Integer, nullable=False)  # GEOFlow users.id
    admin_name = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False)  # create_client/delete_client/manual_create/trigger_scan/export/...
    target_type = Column(String(32), nullable=True)  # client/distribution/client_site
    target_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)  # JSON: 操作详情
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**现有表迁移到 monitor schema**（clients, client_sites, index_results, citation_results, system_config, index_history）：

```python
# 所有监测系统的模型加 __table_args__ = {"schema": "monitor"}
class Client(Base):
    __tablename__ = "clients"
    __table_args__ = {"schema": "monitor"}
    # 增加生命周期字段
    status = Column(String(32), default="active", nullable=False)  # active/inactive/deleted
    contact_name = Column(String(128), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(32), nullable=True)
    # ... 其他字段不变

class ClientSite(Base):
    __tablename__ = "client_sites"
    __table_args__ = (
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),
        UniqueConstraint("domain", name="client_sites_domain_unique_key"),  # 一个 domain 只属于一个客户
        {"schema": "monitor"},
    )
    # 增加字段
    has_wordpress = Column(Boolean, default=False)  # 是否 WordPress 站点（仅记录属性，不影响监测）
    site_type = Column(String(32), default="official")  # official/blog/help
    # ... 其他字段不变
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
    file_path = Column(String(512), nullable=True)
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
```

### 4.2 跨 schema 读 GEOFlow 的表

监测系统的 SQLAlchemy 模型跨 schema 查询 GEOFlow 的表（只读）：

```python
# index-monitor/app/models/geoflow_views.py
class GeoflowUser(Base):
    """GEOFlow 的 users 表（只读，用于 SSO 验证）。"""
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255), unique=True)
    password = Column(String(255))  # Laravel bcrypt hash
    # ... Laravel users 表其他字段

class GeoflowArticle(Base):
    """GEOFlow 的 articles 表（只读视图）。"""
    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    title = Column(String(512))
    slug = Column(String(512))
    excerpt = Column(Text)
    content = Column(Text)
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
    CASE WHEN m.id IS NOT NULL THEN 'manual' ELSE 'geoflow' END AS source,
    ir.baidu_status, ir.toutiao_status, ir.sogou_status, ir.so360_status, ir.bing_status,
    cr.citation_exact, cr.citation_total
FROM public.article_distributions d
JOIN public.articles a ON a.id = d.article_id
LEFT JOIN public.distribution_channels c ON c.id = d.distribution_channel_id
LEFT JOIN monitor.client_sites s ON s.domain = extract_domain(d.remote_url)
LEFT JOIN monitor.manual_distributions m ON m.remote_url = d.remote_url
LEFT JOIN monitor.index_results ir ON ir.url = d.remote_url
LEFT JOIN (SELECT url, COUNT(*) FILTER (WHERE hit_type='exact') AS citation_exact, COUNT(*) AS citation_total
           FROM monitor.citation_results GROUP BY url) cr ON cr.url = d.remote_url
WHERE d.status = 'synced' AND d.action != 'delete'
```

**keywords 格式处理**：GEOFlow 的 `articles.keywords` 存储格式需实现前验证（`SELECT keywords FROM public.articles LIMIT 5`），可能是 JSON 字符串或逗号分隔。查询后用 Python 解析为 array。

---

## 5. SSO 架构设计

### 5.1 SSO 流程（GEOFlow 作为 IdP，监测系统作为 SP）

```
用户访问 monitor.zkeeeai.com
         │
         ▼ 未登录
重定向到 GEOFlow 登录页
  https://zkeeeai.com/sso/authorize?redirect_uri=https://monitor.zkeeeai.com/sso/callback
         │
         ▼ 用户在 GEOFlow 登录（已有 session 则跳过登录）
GEOFlow 生成一次性 code（Redis 存 30s）
         │
         ▼ 重定向回监测系统
monitor.zkeeeai.com/sso/callback?code=xxx
         │
         ▼ 监测系统用 code 调 GEOFlow API
GET https://zkeeeai.com/api/sso/userinfo?code=xxx
         │
         ▼ GEOFlow 返回 user info
{ "user_id": 1, "name": "张三", "email": "...", "role": "super_admin" }
         │
         ▼ 监测系统签发自己的 JWT（含 user_id + role）
用户进入监测系统 dashboard
```

### 5.2 GEOFlow 侧新增

**SsoController**（`app/Http/Controllers/SsoController.php`）：

```php
class SsoController extends Controller
{
    // GET /sso/authorize?redirect_uri=xxx
    public function authorize(Request $request)
    {
        $redirectUri = $request->query('redirect_uri');
        if (!Auth::check()) {
            session(['sso_redirect_uri' => $redirectUri]);
            return redirect('/login');
        }
        $code = Str::random(32);
        Redis::setex("sso:code:{$code}", 30, Auth::id());
        return redirect("{$redirectUri}?code={$code}");
    }

    // GET /api/sso/userinfo?code=xxx
    public function userinfo(Request $request)
    {
        $code = $request->query('code');
        $userId = Redis::get("sso:code:{$code}");
        if (!$userId) {
            return response()->json(['error' => 'invalid_code'], 400);
        }
        Redis::del("sso:code:{$code}");  // 一次性使用
        $user = User::find($userId);
        $admin = Admin::where('user_id', $userId)->first();
        $role = $admin ? $admin->role : 'admin';
        return response()->json([
            'user_id' => $user->id,
            'name' => $user->name,
            'email' => $user->email,
            'role' => $role,  // admin | super_admin
        ]);
    }
}
```

**路由**（`routes/web.php` + `routes/api.php`）：
```php
Route::get('/sso/authorize', [SsoController::class, 'authorize']);
Route::get('/api/sso/userinfo', [SsoController::class, 'userinfo']);
```

### 5.3 监测系统侧新增

**SSO 路由**（`app/api/sso_routes.py`）：

```python
# GET /sso/login - 触发 SSO 跳转
@router.get("/sso/login")
async def sso_login(request: Request):
    redirect_uri = f"{settings.MONITOR_BASE_URL}/sso/callback"
    geoflow_login_url = f"{settings.GEOFLOW_BASE_URL}/sso/authorize?redirect_uri={redirect_uri}"
    return RedirectResponse(url=geoflow_login_url)

# GET /sso/callback?code=xxx - 接收 code，换取 userinfo，签发 JWT
@router.get("/sso/callback")
async def sso_callback(code: str, response: Response, db: AsyncSession = Depends(get_db)):
    # 1. 用 code 调 GEOFlow API 换取 user info
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.GEOFLOW_BASE_URL}/api/sso/userinfo",
            params={"code": code},
            timeout=10,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="SSO code 无效或已过期")
    user_info = resp.json()

    # 2. 签发监测系统 JWT（含 user_id + role）
    token = create_access_token({
        "sub": str(user_info["user_id"]),
        "name": user_info["name"],
        "email": user_info["email"],
        "role": user_info["role"],  # admin | super_admin
        "type": "admin",  # 标记为 admin 登录
    })

    # 3. 记录审计日志
    await AuditLogService.log(
        db, admin_user_id=user_info["user_id"], admin_name=user_info["name"],
        action="sso_login", ip_address=..., detail={"email": user_info["email"]}
    )

    # 4. 设置 cookie + 重定向到 dashboard
    response.set_cookie("admin_token", token, httponly=True, max_age=7*86400)
    return RedirectResponse(url="/admin/dashboard", status_code=302)
```

### 5.4 客户独立登录（不走 SSO）

客户在 `monitor.zkeeeai.com/login` 独立登录：

```python
@router.post("/auth/login")
async def client_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Client).where(Client.client_id == req.client_id, Client.status == "active")
    )
    client = result.scalar_one_or_none()
    if not client or not verify_password(req.password, client.password_hash):
        raise HTTPException(status_code=401, detail="客户账号或密码错误")
    client.last_login_at = func.now()
    await db.commit()
    token = create_access_token({"sub": client.client_id, "role": "client", "type": "client"})
    return {"access_token": token, "token_type": "bearer", "role": "client"}
```

### 5.5 权限同步策略

**无需手动同步**：GEOFlow 的 admin/super_admin 角色通过 SSO userinfo 自动传递到监测系统。在 GEOFlow 改角色 → 下次 SSO 登录自动生效（JWT 有效期 7 天，过期后重新 SSO 获取最新角色）。

### 5.6 配置项

`.env.prod`（GEOFlow 侧）：
```
SSO_REDIS_PREFIX=sso:code:
SSO_CODE_TTL=30
```

`.env.prod`（监测系统侧）：
```
GEOFLOW_BASE_URL=https://zkeeeai.com
MONITOR_BASE_URL=https://monitor.zkeeeai.com
SSO_JWT_SECRET=<部署时生成，与 client JWT_SECRET 可相同或独立>
SSO_JWT_EXPIRE_DAYS=7
```

---

## 6. 客户账户体系与生命周期

### 6.1 客户账户创建流程

**必填信息**：

| 字段 | 说明 | 用途 |
|---|---|---|
| client_name | 客户名称（公司名） | 显示 |
| client_id | 登录账号（自动生成或手动指定） | 登录 |
| password | 初始密码（admin 设置或自动生成） | 登录 |
| contact_name | 联系人姓名 | 沟通 |
| contact_email | 联系邮箱（UNIQUE） | 通知 |
| contact_phone | 联系电话 | 沟通 |
| status | active/inactive/deleted | 生命周期 |

**创建流程**：
1. admin 在监测系统后台「创建客户」页面填写信息
2. 系统校验：client_id UNIQUE、contact_email 格式+UNIQUE、密码强度（至少 8 位，含字母+数字）
3. 密码加密存储（bcrypt）
4. 创建 `monitor.clients` 记录（status='active'）
5. 记录审计日志（action='create_client'）
6. （可选）admin 接着登记客户站点 domain

### 6.2 客户站点登记（domain 匹配）

创建客户后，admin 登记客户站点：

| 字段 | 说明 |
|---|---|
| client_id | 关联客户 |
| domain | 站点域名（自动标准化去 www） |
| site_name | 站点名称 |
| site_type | official/blog/help |
| has_wordpress | 是否 WordPress 站点（仅记录属性，不影响监测链接来源） |
| status | active/inactive |

**关键**：`has_wordpress` 字段仅用于记录客户属性，**不影响监测链接来源**。统一数据库后，GEOFlow 分发的任何渠道链接都自动可见。

### 6.3 客户生命周期管理

| 操作 | 端点 | 效果 |
|---|---|---|
| 创建 | `POST /admin/clients` | status='active'，可登录 |
| 编辑 | `PUT /admin/clients/{id}` | 更新信息/重置密码 |
| 停用 | `PUT /admin/clients/{id}` body={status:inactive} | 禁止登录，保留数据，停止定时检测 |
| 软删除 | `DELETE /admin/clients/{id}` | status='deleted'，隐藏，停止监测，保留数据 |
| 恢复 | `PUT /admin/clients/{id}` body={status:active} | 恢复登录和监测 |

**数据完整性**：停用/删除客户时，不删除关联的 client_sites、manual_distributions、index_results、citation_results（保留历史数据）。

**审计**：所有生命周期操作记录到 admin_audit_logs。

### 6.4 账号安全校验

**客户账号**（监测系统侧管理）：
- 密码强度：至少 8 位，包含字母+数字
- 重复检测：client_id UNIQUE，contact_email UNIQUE
- 创建时验证：邮箱格式、电话格式

**admin 账号**（在 GEOFlow 侧管理，监测系统不涉及创建）：
- 密码强度：GEOFlow 后台创建 admin 时校验（Laravel 的密码规则）
- 重复检测：GEOFlow users 表 email UNIQUE

---

## 7. DistributionQueryService 实现

位置：`index-monitor/app/services/distribution_query.py`

### 7.1 domain → client_id 匹配（查询时 JOIN）

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
        """查询分发记录（跨 schema JOIN）。"""
        results = []
        if source in (None, "geoflow"):
            geoflow_records = await self._query_geoflow_distributions(client_id, status)
            results.extend(geoflow_records)
        if include_manual and source in (None, "manual"):
            manual_records = await self._query_manual_distributions(client_id, status)
            results.extend(manual_records)
        results.sort(key=lambda x: x.get("distributed_at") or x.get("created_at") or "", reverse=True)
        return results

    async def _query_geoflow_distributions(self, client_id: str | None, status: str | None) -> list[dict]:
        """查 GEOFlow 的 article_distributions（跨 schema JOIN）。
        domain 匹配采用 Python 层处理：先查所有 client_sites 建 domain→client_id 映射，再匹配。
        """
        query = (
            select(GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel, IndexResult)
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

        sites_result = await self.db.execute(select(ClientSite).where(ClientSite.status == "active"))
        domain_map = {self._extract_domain(s.domain): (s.client_id, s.site_type) for s in sites_result.scalars().all()}

        urls = [row[0].remote_url for row in rows]
        citation_map = await self._aggregate_citations(urls)

        records = []
        for row in rows:
            dist, article, channel, index_result = row
            domain = self._extract_domain(dist.remote_url)
            matched = domain_map.get(domain)
            if matched is None:
                continue
            cid, site_type = matched
            if client_id and cid != client_id:
                continue
            records.append(self._serialize_geoflow(dist, article, channel, index_result, cid, site_type, citation_map))
        return records

    def _serialize_geoflow(self, dist, article, channel, index_result, client_id, site_type, citation_map) -> dict:
        import json
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
        """查手动录入的记录（monitor.manual_distributions）。"""
        query = select(ManualDistribution).where(ManualDistribution.status == "synced")
        if client_id:
            query = query.where(ManualDistribution.client_id == client_id)
        result = await self.db.execute(query)
        records = result.scalars().all()

        urls = [r.remote_url for r in records]
        index_map, citation_map = await self._aggregate_index_and_citation(urls)

        return [self._serialize_manual(r, index_map, citation_map) for r in records]

    def _serialize_manual(self, record: ManualDistribution, index_map: dict, citation_map: dict) -> dict:
        """序列化手动录入记录 + 关联检测结果。"""
        url = record.remote_url
        idx = index_map.get(url)
        cit = citation_map.get(url)
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
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "distributed_at": record.created_at.isoformat() if record.created_at else None,
            "index_status": {
                "baidu": idx.baidu_status if idx else "pending",
                "toutiao": idx.toutiao_status if idx else "pending",
                "sogou": idx.sogou_status if idx else "pending",
                "so360": idx.so360_status if idx else "pending",
                "bing": idx.bing_status if idx else "pending",
            } if idx else {k: "pending" for k in ("baidu", "toutiao", "sogou", "so360", "bing")},
            "citation_status": "cited" if cit and cit.get("exact", 0) > 0 else ("not_cited" if cit else "pending"),
            "citation_exact": cit.get("exact", 0) if cit else 0,
            "citation_total": cit.get("total", 0) if cit else 0,
        }

    async def create_manual_distribution(
        self, remote_url: str, admin_user_id: int, admin_name: str,
        client_id: str | None = None, note: str | None = None,
    ) -> dict:
        """运营手动录入 URL。client_id 为 None 时自动匹配 domain。"""
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

        existing_geoflow = await self.db.execute(
            select(GeoflowArticleDistribution).where(
                GeoflowArticleDistribution.remote_url == remote_url,
                GeoflowArticleDistribution.status == "synced",
            )
        )
        if existing_geoflow.scalar_one_or_none():
            raise DistributionConflictError(f"URL 已存在（GEOFlow 推送）：{remote_url}")

        record = ManualDistribution(
            client_id=client_id, remote_url=remote_url, status="synced",
            note=note, created_by_admin_id=admin_user_id,
        )
        self.db.add(record)
        await self.db.commit()

        # 记录审计日志
        await AuditLogService.log(
            self.db, admin_user_id=admin_user_id, admin_name=admin_name,
            action="manual_create_distribution", target_type="distribution",
            target_id=str(record.id),
            detail={"url": remote_url, "client_id": client_id},
        )
        return {"action": "created", "client_id": client_id, "source": "manual"}
```

### 7.2 IndexChecker / CitationChecker 改造

现有 [index_checker.py](../../../index-monitor/app/services/index_checker.py) 和 [citation_checker.py](../../../index-monitor/app/services/citation_checker.py) 从 `article_distributions` 读 URL。改造为同时读 GEOFlow 的表 + 手动录入表：

```python
async def get_pending_urls(self) -> List[Tuple[str, str]]:
    """获取待检测 URL：GEOFlow 分发记录 + 手动录入记录。"""
    geoflow_result = await self.db.execute(
        select(GeoflowArticleDistribution.remote_url, ClientSite.client_id)
        .outerjoin(ClientSite, ClientSite.domain == <domain_expr>)
        .where(GeoflowArticleDistribution.status == "synced", GeoflowArticleDistribution.action != "delete")
    )
    distributed = {row[0]: row[1] for row in geoflow_result.fetchall()}

    manual_result = await self.db.execute(
        select(ManualDistribution.remote_url, ManualDistribution.client_id)
        .where(ManualDistribution.status == "synced")
    )
    for row in manual_result.fetchall():
        distributed.setdefault(row[0], row[1])  # GEOFlow 优先

    result = await self.db.execute(select(IndexResult.url))
    checked_urls = {row[0] for row in result.fetchall()}
    return [(url, cid) for url, cid in distributed.items() if url not in checked_urls]
```

---

## 8. 鉴权设计

### 8.1 admin 鉴权（SSO JWT）

```python
# index-monitor/app/api/deps.py
async def get_current_admin(token: str = Depends(oauth2_scheme)) -> dict:
    """验证 admin JWT（SSO 签发）。不查 DB，JWT 内含 user_id + role。"""
    payload = decode_token(token)
    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if payload.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return {
        "user_id": int(payload["sub"]),
        "name": payload["name"],
        "email": payload["email"],
        "role": payload["role"],
    }

async def get_current_super_admin(admin: dict = Depends(get_current_admin)) -> dict:
    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin

async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> tuple[dict | Client, str]:
    """统一入口：返回 (user, role)。调用方根据 role 判断权限。"""
    payload = decode_token(token)
    user_type = payload.get("type", "client")
    if user_type == "admin":
        admin = await get_current_admin(token)
        return admin, admin["role"]
    # client
    result = await db.execute(select(Client).where(Client.client_id == payload.get("sub")))
    client = result.scalar_one_or_none()
    if not client or client.status != "active":
        raise HTTPException(status_code=401, detail="客户账号不存在或已禁用")
    return client, "client"
```

### 8.2 客户鉴权（现有 client JWT，无需改动）

复用 [deps.py](../../../index-monitor/app/api/deps.py) 的 `get_current_client_id`。客户登录后按 client_id 过滤数据。

### 8.3 权限边界

| 角色 | 来源 | 权限 |
|---|---|---|
| super_admin | SSO from GEOFlow | 全部 + 管理 admin 账号（在 GEOFlow 后台操作） |
| admin | SSO from GEOFlow | 管理客户/站点/分发/手动录入/触发检测/导出/查看审计日志 |
| client | 监测系统独立登录 | 只看自己 client_id 数据 + 导出自己的数据 |

### 8.4 鉴权独立性（重要边界）

**admin 鉴权与 client 鉴权完全独立，互不影响**：

- admin 的 JWT 是 SSO 签发的（从 GEOFlow 获取），与客户密码无关
- admin 查数据走 `GET /admin/distributions`（跨 schema JOIN），与客户登录状态无关
- **客户改密码、停用、软删除均不影响 admin 查看该客户的全部数据**

| 客户操作 | 对客户自己的影响 | 对 admin 的影响 |
|---|---|---|
| 改密码 | 下次登录用新密码 | ❌ 无影响 |
| 停用（inactive） | 无法登录 + 停止定时检测 | ❌ 无影响，admin 正常查看（标注"已停用"） |
| 软删除（deleted） | 从客户端隐藏 | ❌ 无影响，admin 可用 `?include_deleted=true` 查看历史数据 |

**关键原则**：客户状态只影响**客户自己能否登录**，不影响 admin 查看数据。历史数据（分发记录、检测结果、采信记录）永远保留，admin 随时可查。

---

## 9. 管理员端点清单

新增 `index-monitor/app/api/admin_routes.py`，前缀 `/api/v1/admin`：

| 方法 | 路径 | 鉴权 | 功能 |
|---|---|---|---|
| GET | `/sso/login` | 公开 | 触发 SSO 跳转到 GEOFlow 登录 |
| GET | `/sso/callback` | 公开 | 接收 code，换取 userinfo，签发 JWT |
| POST | `/auth/login` | 公开 | 客户独立登录 |
| GET | `/admin/clients` | admin | 客户列表（分页、搜索） |
| POST | `/admin/clients` | admin | 创建客户账号（含安全校验） |
| PUT | `/admin/clients/{id}` | admin | 更新客户（密码重置、状态变更） |
| DELETE | `/admin/clients/{id}` | admin | 软删除客户（status=deleted） |
| GET | `/admin/client_sites` | admin | 站点列表 |
| POST | `/admin/client_sites` | admin | 登记站点（domain 自动标准化去 www） |
| PUT | `/admin/client_sites/{id}` | admin | 更新站点 |
| DELETE | `/admin/client_sites/{id}` | admin | 删除站点（软删除） |
| GET | `/admin/distributions` | admin | 所有分发记录（跨客户） |
| POST | `/distributions` | admin | 手动录入 URL |
| DELETE | `/distributions/{id}` | admin | 删除手动录入的 URL |
| **POST** | **`/admin/distributions/batch-scan`** | **admin** | **批量触发检测** |
| **PUT** | **`/admin/clients/{id}/password`** | **admin** | **重置客户密码（不需旧密码）** |
| GET | `/admin/audit_logs` | admin | 审计日志列表（admin 看自己，super_admin 看所有） |
| POST | `/admin/exports` | admin/client | 创建导出任务 |
| GET | `/admin/exports/{id}/download` | admin/client | 下载导出文件 |
| POST | `/exports` | client | 客户导出自己的数据 |
| **PUT** | **`/auth/password`** | **client** | **客户修改自己的密码（需验证旧密码）** |
| **PUT** | **`/auth/profile`** | **client** | **客户修改自己的资料（联系人/电话）** |

### 9.1 批量触发检测端点

```python
class BatchScanRequest(BaseModel):
    distribution_ids: list[str]
    scan_type: str  # 'index' | 'citation' | 'both'

@router.post("/admin/distributions/batch-scan")
async def batch_scan(req: BatchScanRequest, admin = Depends(get_current_admin), db = ...):
    # 记录审计日志
    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="batch_scan", detail={"ids": req.distribution_ids, "type": req.scan_type},
    )
    # 异步触发检测
    for dist_id in req.distribution_ids:
        if req.scan_type in ("index", "both"):
            await trigger_index_check(dist_id)
        if req.scan_type in ("citation", "both"):
            await trigger_citation_check(dist_id)
    return {"queued": len(req.distribution_ids), "scan_type": req.scan_type}
```

### 9.2 客户导出端点

```python
@router.post("/exports")
async def client_create_export(req: ExportRequest, user = Depends(get_current_client), db = ...):
    # 强制 client_id = 当前客户
    task = await ExportService.create_task(client_id=user.client_id, ...)
    return {"task_id": str(task.id)}
```

### 9.3 客户修改密码端点

```python
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@router.put("/auth/password")
async def change_password(req: ChangePasswordRequest, user = Depends(get_current_client), db: AsyncSession = Depends(get_db)):
    """客户修改自己的密码。需验证旧密码 + 新密码强度校验。"""
    # 1. 验证旧密码
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    # 2. 新密码不能与旧密码相同
    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    # 3. 校验新密码强度（至少 8 位，含字母+数字）
    validate_password_strength(req.new_password)

    # 4. 更新密码
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "密码修改成功"}

@router.put("/auth/profile")
async def update_profile(req: UpdateProfileRequest, user = Depends(get_current_client), db: AsyncSession = Depends(get_db)):
    """客户修改自己的资料（联系人姓名/电话）。client_id 和 email 不可改。"""
    if req.contact_name:
        user.contact_name = req.contact_name
    if req.contact_phone:
        user.contact_phone = req.contact_phone
    await db.commit()
    return {"message": "资料更新成功"}
```

### 9.4 admin 重置客户密码端点

```python
class ResetPasswordRequest(BaseModel):
    new_password: str

@router.put("/admin/clients/{client_id}/password")
async def admin_reset_password(client_id: str, req: ResetPasswordRequest, admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """admin 重置客户密码。不需旧密码，但记录审计日志。"""
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")

    # 校验新密码强度
    validate_password_strength(req.new_password)

    client.password_hash = hash_password(req.new_password)
    await db.commit()

    # 记录审计日志
    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="reset_client_password", target_type="client", target_id=client_id,
    )
    return {"message": f"客户 {client_id} 密码已重置"}
```

**密码强度校验函数**（复用于客户创建/修改/重置）：

```python
# index-monitor/app/utils/validators.py
import re

def validate_password_strength(password: str) -> None:
    """密码强度校验：至少 8 位，包含字母和数字。"""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if not re.search(r'[a-zA-Z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含字母")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="密码必须包含数字")
```

---

## 10. 操作审计日志

### 10.1 AuditLogService

```python
# index-monitor/app/services/audit_log.py
class AuditLogService:
    @staticmethod
    async def log(db: AsyncSession, admin_user_id: int, admin_name: str,
                  action: str, target_type: str = None, target_id: str = None,
                  detail: dict = None, ip_address: str = None, user_agent: str = None):
        log = AdminAuditLog(
            admin_user_id=admin_user_id, admin_name=admin_name, action=action,
            target_type=target_type, target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address=ip_address, user_agent=user_agent,
        )
        db.add(log)
        await db.commit()
```

### 10.2 记录的操作

| action | target_type | 说明 |
|---|---|---|
| sso_login | - | admin SSO 登录 |
| create_client | client | 创建客户 |
| update_client | client | 编辑客户 |
| deactivate_client | client | 停用客户 |
| delete_client | client | 软删除客户 |
| restore_client | client | 恢复客户 |
| create_client_site | client_site | 登记站点 |
| update_client_site | client_site | 更新站点 |
| delete_client_site | client_site | 删除站点 |
| manual_create_distribution | distribution | 手动录入 URL |
| delete_distribution | distribution | 删除手动 URL |
| trigger_index_scan | distribution | 触发收录检测 |
| trigger_citation_scan | distribution | 触发采信检测 |
| batch_scan | - | 批量触发检测 |
| **reset_client_password** | **client** | **admin 重置客户密码** |
| create_export | export_task | 创建导出任务 |

---

## 11. 监测触发机制

### 11.1 不自动触发

推送/录入后**不自动触发**检测。原因：
- 收录检测有延迟（搜索引擎需要时间收录新文章）
- AI 采信检测成本高（调用 DeepSeek + 多个引用检测模型）

### 11.2 三种触发方式

**单个手动触发**（现有 [routes.py](../../../index-monitor/app/api/routes.py)）：
- `POST /scan/trigger/index` / `POST /scan/trigger/citation`

**批量手动触发**（新增）：
- `POST /admin/distributions/batch-scan`（见第 9.1 节）

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

## 12. 监测结果导出（Playwright PDF + openpyxl Excel）

### 12.1 导出类型

| 格式 | 用途 | 技术栈 |
|---|---|---|
| Excel | 明细数据导出（收录明细、采信明细），运营分析用 | `openpyxl` |
| PDF | 完整报告（含图表、摘要、水印、Logo），客户给老板看 | **`Playwright`（Chromium 渲染 HTML→PDF）** |

### 12.2 PDF 导出：Playwright 方案

**为什么选 Playwright**：
- Chromium 渲染 = 最高质量，CSS3 全支持，所见即所得
- 中文完美支持（安装 `fonts-noto-cjk` 后 7 万+ 汉字全覆盖）
- 字体自动嵌入 PDF，查看端无需安装字体，**不掉字/不吞字**
- 图片用 base64 内联，**图片绝不丢失**
- 水印/Logo 用 CSS `position:fixed`，**每页自动显示**
- 格式一致：HTML 模板固定 + CSS 分页控制

**PdfExportService**（`index-monitor/app/services/pdf_export_service.py`）：

```python
from playwright.async_api import async_playwright
import base64, jinja2

class PdfExportService:
    def __init__(self):
        self.browser = None  # 复用浏览器实例

    async def _get_browser(self):
        if self.browser is None:
            pw = await async_playwright().start()
            self.browser = await pw.chromium.launch(
                args=["--no-sandbox", "--font-render-hinting=none"]
            )
        return self.browser

    async def render_pdf(self, template_name: str, context: dict) -> bytes:
        # 1. 渲染 HTML 模板（Jinja2）
        template = self.jinja_env.get_template(template_name)
        context["logo_base64"] = self._file_to_base64("/app/assets/logo.png")
        html = template.render(**context)

        # 2. Chromium 渲染为 PDF
        browser = await self._get_browser()
        page = await browser.new_page()
        await page.set_content(html, wait_until="networkidle")
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,  # 打印背景色（水印/卡片背景）
            margin={"top": "2cm", "bottom": "2.5cm", "left": "2cm", "right": "2cm"},
            display_header_footer=True,
            footer_template='<div style="font-size:10px;text-align:center;width:100%;color:#8c8c8c;">第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>',
        )
        await page.close()
        return pdf_bytes

    def _file_to_base64(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
```

### 12.3 PDF 报告模板（改进版，丰富图表）

**HTML 模板**（`index-monitor/templates/report.html`）：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
    @page {
        size: A4;
        margin: 2cm 2cm 2.5cm 2cm;
    }
    body {
        font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
        color: #262626;
        line-height: 1.6;
    }
    /* 水印：每页固定显示 */
    .watermark {
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%) rotate(-30deg);
        font-size: 80px; font-weight: bold;
        color: rgba(24,144,255,0.06);
        z-index: -1; pointer-events: none;
    }
    /* Logo：每页右上角固定 */
    .logo {
        position: fixed;
        top: 0.5cm; right: 1cm;
        width: 80px; height: auto;
        z-index: 100;
    }
    /* 表格不跨页断裂 */
    table, tr, td, th { page-break-inside: avoid; }
    h1, h2, h3 { page-break-after: avoid; }
    .cover { page-break-after: always; }

    /* 图表不跨页：所有图表容器、统计卡片、数据洞察禁止分页切割 */
    .chart-box, .chart-grid, .stat-card, .stat-grid, .insight {
        page-break-inside: avoid;
        break-inside: avoid;
    }
    /* 图表标题不与图表分离 */
    .chart-title { page-break-after: avoid; }
    /* 统计卡片行不跨页（4 个卡片保持在同一页） */
    .stat-grid { page-break-before: avoid; }
    /* 两列图表网格不跨页 */
    .chart-grid { page-break-before: avoid; }

    /* 统计卡片 */
    .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
    .stat-card { background: white; border: 1px solid #e8e8e8; border-radius: 8px; padding: 16px; text-align: center; }
    .stat-card .label { font-size: 11px; color: #8c8c8c; margin-bottom: 6px; }
    .stat-card .value { font-size: 24px; font-weight: 700; }
    .stat-card .trend { font-size: 10px; margin-top: 4px; }

    /* 图表网格 */
    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
    .chart-box { background: white; border: 1px solid #e8e8e8; border-radius: 8px; padding: 16px; }
    .chart-title { font-size: 13px; font-weight: 600; margin-bottom: 12px; }

    /* 数据洞察 */
    .insight { background: linear-gradient(135deg,#e6f7ff,#f6ffed); border-radius: 8px; padding: 16px; border-left: 4px solid #1890ff; }
</style>
</head>
<body>
    <div class="watermark">知氪AI监测</div>
    <img class="logo" src="data:image/png;base64,{{ logo_base64 }}" alt="logo" />

    <!-- 封面 -->
    <div class="cover">
        <h1>{{ client_name }} 监测报告</h1>
        <p>报告周期：{{ date_from }} ~ {{ date_to }}</p>
        <p>生成时间：{{ generated_at }}</p>
    </div>

    <!-- 数据概览页 -->
    <h2>数据概览</h2>

    <!-- 4 个统计卡片 -->
    <div class="stat-grid">
        <div class="stat-card"><div class="label">收录率</div><div class="value" style="color:#1890ff;">{{ index_rate }}%</div><div class="trend" style="color:#52c41a;">↑ {{ index_trend }}% 较上周</div></div>
        <div class="stat-card"><div class="label">AI 采信率</div><div class="value" style="color:#52c41a;">{{ citation_rate }}%</div><div class="trend" style="color:#52c41a;">↑ {{ citation_trend }}% 较上月</div></div>
        <div class="stat-card"><div class="label">分发总数</div><div class="value" style="color:#fa8c16;">{{ total }}</div><div class="trend" style="color:#52c41a;">↑ {{ new_this_week }} 本周新增</div></div>
        <div class="stat-card"><div class="label">待检测</div><div class="value" style="color:#f5222d;">{{ pending }}</div><div class="trend" style="color:#f5222d;">需处理</div></div>
    </div>

    <!-- 收录趋势（多引擎对比，前端 ECharts 截图 base64 嵌入） -->
    <div class="chart-box" style="margin-bottom:16px;">
        <div class="chart-title">收录趋势（近 30 天 · 多引擎对比）</div>
        <img src="data:image/png;base64,{{ chart_index_trend }}" style="width:100%;" />
    </div>

    <!-- 两列图表 -->
    <div class="chart-grid">
        <div class="chart-box"><div class="chart-title">AI 采信分布</div><img src="data:image/png;base64,{{ chart_citation_pie }}" style="width:100%;" /></div>
        <div class="chart-box"><div class="chart-title">各引擎收录对比</div><img src="data:image/png;base64,{{ chart_engine_bar }}" style="width:100%;" /></div>
    </div>

    <!-- 数据洞察 -->
    <div class="insight">
        <div style="font-weight:600;margin-bottom:8px;">💡 本期数据洞察</div>
        <div style="font-size:12px;color:#595959;line-height:1.8;">{{ insights | safe }}</div>
    </div>

    <!-- 明细表 -->
    <div style="page-break-before:always;">
        <h2>分发记录明细</h2>
        <table style="width:100%;border-collapse:collapse;font-size:11px;">
            <thead><tr style="background:#fafafa;"><th style="padding:8px;border-bottom:2px solid #e8e8e8;">标题</th><th>来源</th><th>渠道</th><th>收录</th><th>采信</th><th>日期</th></tr></thead>
            <tbody>
            {% for d in distributions %}
                <tr><td style="padding:8px;border-bottom:1px solid #f0f0f0;">{{ d.content_title }}</td><td>{{ d.source }}</td><td>{{ d.channel_name or '-' }}</td><td>{{ d.index_status.baidu }}</td><td>{{ d.citation_status }}</td><td>{{ d.distributed_at }}</td></tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
```

### 12.4 图表生成方案

ECharts 图表用**前端截图传后端**方式，保证图表美观且与 dashboard 一致：
1. dashboard 前端用 ECharts 渲染图表 → `echarts.getDataURL()` 转 PNG base64
2. 创建导出任务时，前端把图表截图一起 POST 到后端
3. 后端嵌入 PDF 模板

### 12.5 Excel 导出（openpyxl）

**Excel 报表**（多 sheet）：
- Sheet 1「分发记录」：URL、标题、来源、客户、渠道、发布时间
- Sheet 2「收录检测」：URL、百度/头条/搜狗/360/必应状态、检测时间
- Sheet 3「AI 采信」：URL、模型、问题、命中类型、检测时间
- Sheet 4「汇总统计」：总分发数、收录率、采信率、各引擎收录数

### 12.6 异步导出流程

1. 客户/admin 点击"导出" → `POST /admin/exports` 或 `POST /exports` 创建 `export_tasks` 记录
2. 后台任务处理（APScheduler 或 BackgroundTasks）：
   - 查询数据
   - 生成文件（Playwright PDF / openpyxl Excel）
   - 保存到 `/app/exports/{task_id}.pdf` 或 `.xlsx`
   - 更新 `export_tasks.status = 'completed'`
3. 用户轮询 `GET /admin/exports/{id}` 获取状态
4. 完成后 `GET /admin/exports/{id}/download` 下载

### 12.7 防 bug 保障措施

| Bug 类型 | 保障措施 |
|---|---|
| **掉字/吞字** | 安装 `fonts-noto-cjk`（7万+汉字）+ `fonts-noto-cjk-extra`（罕见字）；CSS 指定 `font-family: "Noto Sans CJK SC"`；Chromium 自动嵌入字体子集到 PDF |
| **图片不显示** | 所有图片转 base64 data URI 内联（Logo、ECharts 截图）；不依赖文件路径 |
| **格式不一致** | Jinja2 固定模板 + CSS `@page` 规则 + `page-break-inside: avoid` 防表格断裂；封面 `page-break-after: always` 单独一页 |
| **图表跨页切割** | 所有图表容器 `.chart-box`、统计卡片 `.stat-grid`、数据洞察 `.insight` 加 `page-break-inside: avoid` + `break-inside: avoid`；图表标题 `.chart-title` 加 `page-break-after: avoid` 防标题与图表分离；空间不足时整块移到下一页 |
| **水印每页显示** | CSS `position:fixed` + `z-index:-1`；Chromium 的 `print_background=True` 确保背景打印 |
| **Logo 每页显示** | CSS `position:fixed` + `top/right` 定位 |
| **页码正确** | Chromium `display_header_footer=True` + `pageNumber`/`totalPages` 模板变量 |
| **特殊字符** | Jinja2 自动转义 `< > & "` 避免解析错误 |

---

## 13. 多渠道分发扩展

### 13.1 统一数据库优势

**统一数据库后，任意渠道自动可见**——监测系统跨 schema 读 GEOFlow 的 `public.article_distributions` 表。无论 GEOFlow 分发到哪个渠道（WordPress/头条/知乎/generic_http_api），只要分发记录 `status='synced'`，监测系统就能自动看到，**不需要为每个渠道单独设计同步机制**。

### 13.2 现有渠道支持

GEOFlow 已支持 3 种渠道类型（[DistributionChannel.php](../../../GEOFlow-main/app/Models/DistributionChannel.php)）：
- `geoflow_agent`：GEOFlow 自有代理
- `wordpress_rest`：WordPress REST API
- `generic_http_api`：通用 HTTP API

### 13.3 本期实现范围

**监测系统侧**（本期做，已完整）：
- domain 匹配逻辑适配所有渠道类型
- 导出报表显示渠道类型
- dashboard 列表显示渠道名称
- **任意渠道的分发记录自动可见**（统一数据库的天然优势，无需额外开发）

**GEOFlow 侧**（本期留接口，不实现具体平台 publisher）：
- 保留现有 publisher 框架（Publisher 基类 + DistributionPublisherManager）
- 文档说明如何新增渠道 publisher（见 13.4）
- `generic_http_api` 渠道配置示例（见 13.4）
- **不实现**头条/知乎/百家号等无公开 API 平台的发布（法律风险，后续独立项目）

### 13.4 新增渠道 publisher 的步骤（GEOFlow 侧，后续扩展指南）

**接口已预留**：GEOFlow 现有 Publisher 框架支持通过以下步骤新增任意渠道：

1. 在 [DistributionChannel.php](../../../GEOFlow-main/app/Models/DistributionChannel.php) 的 `channelType()` 方法加新类型常量
2. 创建新 Publisher 类（继承现有 Publisher 基类），实现 `publish()`/`update()`/`delete()` 方法
3. 在 [DistributionPublisherManager.php](../../../GEOFlow-main/app/Services/GeoFlow/DistributionPublisherManager.php) 注册新 Publisher
4. 配置 `channel_config` 选项（API URL、认证方式等）

**`generic_http_api` 渠道配置示例**（本期可用的通用适配）：

```json
{
  "api_url": "https://your-cms.com/api/articles",
  "auth_type": "bearer",
  "auth_token": "your_token",
  "field_mapping": {
    "title": "title",
    "content": "body",
    "slug": "slug"
  }
}
```

适用于：企业微信 webhook、钉钉群机器人、其他 CMS 的 REST API、任何接受 HTTP POST 的平台。

### 13.5 头条/知乎等平台调研（后续独立项目）

| 平台 | API 现状 | 可行性 |
|---|---|---|
| WordPress | REST API 完善 | ✅ 已支持 |
| 微信公众号 | 有素材管理 API，但受限 | ⚠️ 需调研 |
| 头条号 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |
| 知乎 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |
| 百家号 | 无公开内容发布 API | ❌ 可能需爬虫（违反 ToS） |

**本期不实现爬虫方式发布**（法律风险）。仅支持有合法 API 的平台，通过 `generic_http_api` 适配。

### 13.6 开源项目参考（后续实现时调研）

后续实现多渠道发布时，可参考以下开源项目（2026-07-25 GitHub 调研）：

| 项目 | Star | 语言 | 平台数 | 特点 | 集成方式 |
|---|---|---|---|---|---|
| [Wechatsync](https://github.com/wechatsync/Wechatsync) | 5.5k | TypeScript | 29+ | 最成熟，有 CLI 包，草稿优先，MCP 协议 | Symfony Process 调用 CLI |
| [binggo-island-upload-tool](https://github.com/karmawind/binggo-island-upload-tool) | - | Python | 10 | Python 同语言，CLI+Web+AI Agent，cookie 管理 | 部署为独立服务，HTTP 调用 |
| [SyncCaster](https://github.com/RyanYipeng/SyncCaster) | - | TypeScript | 17+ | 规范化 AST，LaTeX/代码高亮保留 | Chrome 扩展，参考其平台适配逻辑 |
| [MultiPost-Extension](https://gitcode.com/gh_mirrors/mu/MultiPost-Extension) | - | JS | 12+ | 完全免费，无需 API Key | Chrome 扩展 |
| [ZenoClaw](https://github.com/zenolore/zenoclaw) | - | Python | 19 | 连接运行中的 Chrome（debugging port） | Python 服务，HTTP 调用 |

**推荐后续方案**（独立项目时评估）：
- **方案 A**：集成 Wechatsync CLI（Node.js），GEOFlow 通过 Symfony Process 调用——最成熟，29+ 平台
- **方案 B**：部署 binggo-island-upload-tool 作为独立 Python 服务——Python 同语言，有 Web 界面
- **方案 C**：参考开源项目的平台适配逻辑，用 PHP 自研 publisher——纯 PHP，无额外依赖

### 13.7 后续升级路径

当多渠道发布作为独立项目启动时：

1. **评估开源项目**：重新调研 Wechatsync / binggo-island 的活跃度和兼容性
2. **选择集成方案**：A/B/C 三种方案选一（见 13.6）
3. **登录态管理**：设计 cookie/session 管理机制（扫码登录 + 定期刷新）
4. **内容格式适配**：设计 Markdown → 各平台富文本的转换器
5. **法律合规评估**：确认目标平台的 ToS，评估风险
6. **实现 publisher**：在 GEOFlow 现有框架内实现（见 13.4 步骤）
7. **监测系统无需改动**：统一数据库架构下，新渠道的分发记录自动可见

---

## 14. Dashboard UI 设计规范（风格 A：专业数据中台 + 改进版图表）

### 14.1 技术栈

现有：Vue 3 + Element Plus + ECharts + Vite + Vuex + Vue Router。无新增前端依赖。

### 14.2 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│ [深色侧边栏 200px]  │  [顶部导航 56px]                       │
│                     │  面包屑 | 搜索 | 🔔 | 👤 张 ▼         │
│  🌐 知氪AI监测       ├────────────────────────────────────────┤
│                     │                                        │
│  📊 数据总览 (active)│  [内容区，浅色背景 #f5f7fa]            │
│  📝 分发记录         │                                        │
│  🔍 收录检测         │  ┌──────────────────────────────┐     │
│  📈 AI采信检测       │  │  4 个统计卡片（带进度条）     │     │
│  📋 检测报告         │  │  收录率|采信率|分发数|待检测   │     │
│  📤 导出报告         │  └──────────────────────────────┘     │
│  ⚙️ 系统设置         │                                        │
│                     │  ┌────────────┬─────────────┐          │
│  ─────────          │  │ 收录趋势    │ AI 采信分布  │          │
│  站点筛选 ▼         │  │ (多引擎对比) │ (饼图)       │          │
│   • 全部站点         │  │ 折线图      │             │          │
│   • zkeeeai.com     │  ├────────────┴─────────────┤          │
│   • blog.example    │  │ 引擎收录对比│来源分布│本周活动│       │
│                     │  └────────────────────────────┘     │
└─────────────────────┴────────────────────────────────────────┘
```

### 14.3 配色规范

```scss
// 侧边栏（深色）
$sidebar-bg: #001529;
$sidebar-text: rgba(255,255,255,0.65);
$sidebar-text-active: #ffffff;
$sidebar-active-bg: #1890ff;

// 内容区（浅色）
$content-bg: #f5f7fa;
$card-bg: #ffffff;
$border-color: #e8e8e8;

// 品牌色
$primary: #1890ff;         // 百度/主色
$success: #52c41a;         // 已收录/已采信/头条
$warning: #faad14;         // 部分收录/搜狗
$error: #f5222d;           // 未收录/失败
$purple: #722ed1;          // 必应
$orange: #fa8c16;          // 360/分发总数

// 文字
$text-primary: #262626;
$text-secondary: #595959;
$text-tertiary: #8c8c8c;
```

### 14.4 改进版图表清单

| 图表 | 类型 | 数据维度 | 位置 |
|---|---|---|---|
| 收录趋势 | 多引擎对比折线图 | 百度/头条/必应 3 条线 + 渐变填充 | 数据总览（大图） |
| AI 采信分布 | 饼图 | 已采信/部分采信/未采信 3 段 | 数据总览（左半） |
| 各引擎收录对比 | 渐变柱状图 | 百度/头条/搜狗/360/必应 5 个柱 | 数据总览（右半） |
| 来源分布 | 环形图 | GEOFlow vs 手动录入 | 数据总览（左下） |
| 本周活动 | 统计列表 | 新增/收录/采信/导出/待检测 | 数据总览（中下） |
| 统计卡片 | 带进度条卡片 | 收录率/采信率/分发数/待检测 | 数据总览（顶部） |

### 14.5 组件规范

**统计卡片**：白色背景 + 圆角 8px + 柔和阴影 + 大数字 + 趋势箭头 + 进度条

**数据表格**：Element Plus Table + 状态标签
- 收录状态：`<el-tag type="success">已收录</el-tag>` / `<el-tag type="danger">未收录</el-tag>`
- 来源：`<el-tag type="info">GEOFlow</el-tag>` / `<el-tag type="warning">手动</el-tag>`

**图表**：ECharts 折线图（多引擎对比）、饼图（采信分布）、柱状图（引擎对比）、环形图（来源分布）

**批量操作**：表格多选框 +「批量检测」按钮

### 14.6 登录页设计

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
│   全链路监测平台    │   │ 👤 客户账号                  │      │
│                    │   └─────────────────────────────┘      │
│   GEO + SEO        │   ┌─────────────────────────────┐      │
│   一站式优化        │   │ 🔒 密码                      │      │
│                    │   └─────────────────────────────┘      │
│                    │                                         │
│                    │   ┌─────────────────────────────┐      │
│                    │   │        登  录               │      │
│                    │   └─────────────────────────────┘      │
│                    │                                         │
│                    │   管理员入口 →（跳转 SSO 登录）         │
└─────────────────────────────────────────────────────────────┘
```

**登录页区分**：
- 客户登录：`/login`（client JWT，独立登录）
- 管理员登录：点击「管理员入口」→ 跳转 `/sso/login` → GEOFlow SSO 登录
- 两个登录入口共用相同视觉风格

### 14.7 客户多站点分组展示

- 侧边栏底部"站点筛选"下拉框，默认"全部站点"
- 选择具体站点后，所有数据按 `client_sites.domain` 或 `site_type` 过滤

---

## 15. 官网管理入口

### 15.1 入口设计

**官网首页（zkeeeai.com）添加入口**：

1. **顶部导航栏右侧**：「监测平台」链接 → `https://monitor.zkeeeai.com/login`（客户登录）
2. **底部页脚**：「管理员入口」链接 → `https://monitor.zkeeeai.com/sso/login`（管理员 SSO 登录，低调放置）
3. **GEOFlow 后台菜单**：新增「监测系统」菜单项 → 新窗口打开 `https://monitor.zkeeeai.com`（你日常从 GEOFlow 后台跳转，已登录状态自动 SSO）

### 15.2 实现方式

**GEOFlow 前端**（zkeeeai.com）：
- 在模板文件加链接（Laravel blade 模板）
- 不需要鉴权，只是跳转链接

**dashboard 前端**（monitor.zkeeeai.com）：
- `/login` 客户登录页
- `/sso/login` 触发 SSO 跳转（无需单独页面，直接重定向到 GEOFlow）
- 登录后根据 role 跳转不同主页

---

## 16. 测试策略（TDD）

### 16.1 监测系统侧测试（pytest）

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
│   ├── test_sso_auth.py
│   │   - test_sso_callback_valid_code_signs_jwt
│   │   - test_sso_callback_invalid_code_returns_401
│   │   - test_sso_callback_expired_code_returns_401
│   │   - test_get_current_admin_requires_admin_type
│   │   - test_get_current_super_admin_requires_super_role
│   ├── test_client_lifecycle.py
│   │   - test_create_client_validates_password_strength
│   │   - test_create_client_validates_email_unique
│   │   - test_deactivate_client_blocks_login
│   │   - test_soft_delete_client_hides_from_list
│   │   - test_restore_client_re_enables_login
│   ├── test_change_password.py
│   │   - test_client_change_password_success
│   │   - test_client_change_password_wrong_old_returns_400
│   │   - test_client_change_password_same_as_old_returns_400
│   │   - test_client_change_password_weak_new_returns_400
│   │   - test_admin_reset_client_password_success
│   │   - test_admin_reset_password_logs_audit
│   │   - test_admin_reset_password_weak_returns_400
│   ├── test_audit_log.py
│   │   - test_log_create_client_action
│   │   - test_log_batch_scan_action
│   │   - test_admin_sees_own_logs_only
│   │   - test_super_admin_sees_all_logs
│   ├── test_batch_scan.py
│   │   - test_batch_scan_queues_index_check
│   │   - test_batch_scan_queues_citation_check
│   │   - test_batch_scan_queues_both
│   │   - test_batch_scan_logs_audit
│   ├── test_pdf_export.py
│   │   - test_chinese_characters_not_missing（含生僻字龘靐龗）
│   │   - test_image_displayed（base64 内联）
│   │   - test_watermark_on_every_page
│   │   - test_logo_on_every_page
│   │   - test_format_consistency（多次生成页数一致）
│   │   - test_chart_not_split_across_pages（图表不跨页切割）
│   │   - test_table_row_not_split_across_pages（表格行不跨页）
│   │   - test_chart_title_not_separated_from_chart（标题不与图表分离）
│   ├── test_excel_export.py
│   │   - test_excel_has_4_sheets
│   │   - test_excel_sheet_data_correct
│   │   - test_export_task_status_transitions
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
│   │   - test_client_lifecycle_endpoints
│   ├── test_sso_flow.py
│   │   - test_full_sso_flow_geoflow_to_monitor
│   │   - test_sso_login_creates_audit_log
│   ├── test_export_endpoints.py
│   │   - test_admin_export_all_clients
│   │   - test_client_export_only_own_data
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
        - test_sso_login_then_view_dashboard
        - test_batch_scan_triggers_multiple_checks
```

### 16.2 GEOFlow 侧测试（PHPUnit）

```
tests/Feature/Sso/
├── SsoControllerTest.php
│   - test_authorize_redirects_to_login_when_not_authenticated
│   - test_authorize_generates_code_when_authenticated
│   - test_userinfo_returns_user_data_with_role
│   - test_userinfo_invalid_code_returns_400
│   - test_userinfo_one_time_use_code
```

### 16.3 端到端验证

```
deploy/scripts/test-unified-db-e2e.sh
```

验证步骤：
1. GEOFlow 发布文章到 WordPress → `public.article_distributions` 新增记录
2. 监测系统查询 `/distributions` → 看到 GEOFlow 推送的记录（跨 schema JOIN）
3. dashboard 用 admin SSO 登录 → 看到所有分发记录
4. dashboard 用 client 登录 → 只看到自己 domain 的记录
5. 触发收录检测 → IndexChecker 读到 GEOFlow 的 URL
6. 触发 AI 采信检测 → CitationChecker 读到 GEOFlow 的 URL
7. GEOFlow 删除文章 → 监测系统查询时自动看不到（无需同步删除）
8. 运营手动录入 URL → 创建到 `monitor.manual_distributions`
9. 运营手动录入已存在的 URL → 409 冲突
10. 导出 Excel → 下载文件包含所有 sheet
11. 导出 PDF → 下载文件包含图表/水印/Logo/页码，中文不掉字
12. 官网点击"监测平台" → 跳转到客户登录页
13. 官网点击"管理员入口" → 跳转 SSO 登录 → GEOFlow 登录后回到监测 dashboard
14. admin 创建客户 → 客户可登录 → admin 停用客户 → 客户无法登录 → admin 恢复客户 → 客户可登录
15. admin 批量选择 3 条 URL 触发检测 → 3 条检测任务入队
16. admin 查看审计日志 → 看到自己的所有操作
17. 客户修改密码（旧密码错误 → 400；新密码太弱 → 400；正确旧密码+合规新密码 → 成功）→ 用新密码重新登录成功

---

## 17. 部署配置

### 17.1 新增配置项

遵循 project_memory 硬约束"API keys must not be hardcoded, use .env.prod"。

`.env.prod`（GEOFlow 侧）：
```
# SSO 配置
SSO_REDIS_PREFIX=sso:code:
SSO_CODE_TTL=30
```

`.env.prod`（监测系统侧）：
```
# 改为连 GEOFlow 的 PG
POSTGRES_HOST=geoflow-postgres
POSTGRES_PORT=5432
POSTGRES_DB=${GEOFLOW_DB_NAME}
POSTGRES_USER=${GEOFLOW_DB_USER}
POSTGRES_PASSWORD=${GEOFLOW_DB_PASSWORD}
MONITOR_SCHEMA=monitor

# SSO 配置
GEOFLOW_BASE_URL=https://zkeeeai.com
MONITOR_BASE_URL=https://monitor.zkeeeai.com
SSO_JWT_SECRET=<部署时生成>
SSO_JWT_EXPIRE_DAYS=7

# Client JWT
CLIENT_JWT_SECRET=<部署时生成>
```

### 17.2 依赖项安装

**监测系统侧 Python 依赖**（`index-monitor/requirements.txt` 新增）：
```
openpyxl>=3.1.0        # Excel 导出
playwright>=1.40.0     # PDF 导出（Chromium 渲染）
apscheduler>=3.10.0    # 定时任务
httpx>=0.25.0          # SSO 回调调用 GEOFlow API
bcrypt>=4.0.0          # 客户密码验证（Laravel users 用 bcrypt）
```

**Playwright 浏览器安装**（Dockerfile）：
```dockerfile
RUN pip install playwright && playwright install chromium
```

**中文字体安装**（Dockerfile）：
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    && rm -rf /var/lib/apt/lists/*
```

**GEOFlow 侧 PHP 依赖**：无新增。

**Dashboard 前端依赖**：无新增（现有 Element Plus + ECharts 足够）。

### 17.3 docker-compose 变更

**docker-compose.prod.yml**：
- 删除 `postgres` 服务（geo-postgres，废弃）
- `index-monitor` 服务的 `POSTGRES_HOST` 改为 GEOFlow 的 PG 容器名
- `index-monitor` 加入 GEOFlow 的 docker network
- 保留 `redis` 服务

**GEOFlow 的 docker-compose.yml**：
- 无变更（GEOFlow 不感知监测系统）
- 确保 PG 容器对监测系统容器可见

### 17.4 DB 迁移

**监测系统侧**（新建 Alembic 迁移）：
```bash
cd index-monitor
alembic revision -m "create monitor schema and migrate tables"
# 迁移内容：
#   - CREATE SCHEMA IF NOT EXISTS monitor;
#   - 所有监测系统表 ALTER SET SCHEMA monitor
#   - 新建 monitor.manual_distributions 表
#   - 新建 monitor.admin_audit_logs 表
#   - 新建 monitor.export_tasks 表
#   - clients 表增加 status/contact_name/contact_email/contact_phone 字段
#   - client_sites 表增加 has_wordpress 字段 + domain UNIQUE 约束
#   - 不建 admins 表（SSO 方式）
alembic upgrade head
```

**GEOFlow 侧**：
- 新建 SsoController + 路由（无 DB schema 变更）

### 17.5 数据迁移流程（生产环境）

1. 备份监测系统现有 PG
2. 在 GEOFlow 的 PG 创建 `monitor` schema
3. 运行监测系统的 Alembic 迁移（连 GEOFlow 的 PG）
4. 更新监测系统的 `.env.prod` 指向 GEOFlow 的 PG
5. 部署 GEOFlow 的 SsoController
6. 重启所有容器
7. 验证跨 schema 查询正常
8. 验证 SSO 登录流程正常
9. 废弃监测系统的 `postgres:15-alpine` 容器

---

## 18. 实现顺序（TDD）

### Phase 1：数据库统一（基础）
1. 写 monitor schema 创建迁移 + 测试
2. 写监测系统表迁移到 monitor schema + 测试
3. 写跨 schema 查询模型（GeoflowUser/Article/Distribution/Channel）+ 测试
4. 改监测系统的 database.py 连接配置 + 测试
5. 本地验证跨 schema JOIN 查询

### Phase 2：SSO + 数据模型
6. GEOFlow 侧写 SsoController + 路由 + 测试
7. 监测系统侧写 SSO callback 端点 + 测试
8. 写 admin JWT 鉴权（get_current_admin + get_current_super_admin）+ 测试
9. 写 manual_distributions 表迁移 + 模型 + 测试
10. 写 admin_audit_logs 表迁移 + 模型 + 测试
11. 写 export_tasks 表迁移 + 模型 + 测试
12. 写 clients 表生命周期字段（status/contact_*）+ 测试
13. 写 client_sites.domain UNIQUE 约束 + has_wordpress 字段 + 测试

### Phase 3：核心查询服务
14. 写 DistributionQueryService._extract_domain + 测试
15. 写 DistributionQueryService._query_geoflow_distributions + 测试
16. 写 DistributionQueryService._query_manual_distributions + 测试
17. 写 DistributionQueryService.list_distributions + 测试
18. 写 DistributionQueryService.create_manual_distribution + 测试

### Phase 4：IndexChecker/CitationChecker 改造
19. 改 IndexChecker.get_pending_urls 读 GEOFlow + 手动表 + 测试
20. 改 CitationChecker.get_pending_urls 读 GEOFlow + 手动表 + 测试

### Phase 5：管理员端点 + 审计 + 批量
21. 写客户生命周期端点（创建/编辑/停用/删除/恢复）+ 安全校验 + 测试
22. 写 admin 端点（clients/client_sites/distributions）+ 测试
23. 写手动录入端点 POST /distributions + 测试
24. 写 domain 标准化（去 www）+ 测试
25. 写 AuditLogService + 审计日志端点 + 测试
26. 写批量触发检测端点 + 测试

### Phase 6：监测结果导出
27. 写 PdfExportService（Playwright 渲染）+ PDF 模板 + 测试（含中文/图片/水印/Logo 验证）
28. 写 ExcelExportService（openpyxl 4 sheet）+ 测试
29. 写导出端点（POST /admin/exports + POST /exports + GET download）+ 测试
30. 写导出任务后台处理 + 测试

### Phase 7：Dashboard 前端
31. 改造登录页（风格 A）+ 客户登录 + SSO 入口
32. 改造数据总览页（4 统计卡片 + 5 图表：趋势/饼图/柱状图/环形图/活动统计）
33. 新增分发记录页（表格 + 收录/采信状态 + 来源标签 + 多选 + 批量检测）
34. 新增导出报告功能（导出对话框 + 图表截图 + 下载）
35. 新增站点筛选 + 客户切换（admin）
36. 新增审计日志查看页（admin）

### Phase 8：官网入口 + 定时任务 + 端到端
37. 官网首页加监测平台入口 + 管理员入口
38. GEOFlow 后台加监测系统菜单
39. 写定时收录检测任务
40. 写端到端测试脚本 `test-unified-db-e2e.sh`
41. 本地完整测试 → 云端部署 → 生产验证

---

## 19. 验收标准

1. 监测系统连 GEOFlow 的 PG，跨 schema 查询 `public.article_distributions` 正常
2. GEOFlow 发布文章（任意渠道）→ 监测系统 `/distributions` 端点实时看到记录（无同步延迟）
3. GEOFlow 删除文章 → 监测系统查询时自动看不到（无需同步删除逻辑）
4. **admin 通过 SSO 登录**（GEOFlow 登录后自动跳转监测 dashboard，无需二次登录）
5. admin 在 GEOFlow 改角色 → 下次 SSO 登录后监测系统权限自动生效
6. 客户在 `/login` 独立登录 → 只看到自己 client_id 下的分发记录
7. 运营手动录入 URL（domain 已登记）→ 创建成功，source='manual'
8. 运营手动录入 URL（domain 未登记）→ 400 错误
9. 运营手动录入已存在的 URL → 409 冲突
10. IndexChecker 读取 GEOFlow + 手动录入的 URL 执行收录检测
11. CitationChecker 读取 GEOFlow + 手动录入的 URL 执行 AI 采信检测
12. **admin 批量选择 URL 触发检测** → 多条检测任务入队
13. **admin 所有操作记录到审计日志**（创建客户/录入 URL/触发检测/导出等）
14. **客户生命周期完整**：创建→登录→停用→无法登录→恢复→可登录→软删除→隐藏
15. **客户密码安全校验**：密码强度不足/邮箱重复 → 创建失败
16. **客户能自行修改密码**：`PUT /auth/password` 验证旧密码 + 新密码强度校验 + 新旧不能相同
17. **客户能修改自己资料**：`PUT /auth/profile` 修改联系人/电话（client_id 和 email 不可改）
18. **admin 能重置客户密码**：`PUT /admin/clients/{id}/password` 不需旧密码 + 记录审计日志
19. 导出 Excel → 下载文件包含 4 个 sheet
20. **导出 PDF → 含封面/4 统计卡片/趋势折线图/饼图/柱状图/数据洞察/明细表**
21. **PDF 中文不掉字（含生僻字）、图片不丢失、水印 Logo 每页显示、格式每次一致**
22. **客户能导出自己的 PDF 报告**（只含自己 client_id 数据）
23. 官网点击"监测平台" → 跳转客户登录页
24. 官网点击"管理员入口" → SSO 登录后进入监测 dashboard
25. GEOFlow 后台点击"监测系统" → 新窗口打开监测 dashboard（已 SSO 登录）
26. dashboard 风格 A（深色侧边栏 + 浅色内容区 + 4 统计卡片 + 5 图表 + 批量操作）
27. 废弃监测系统的 `postgres:15-alpine` 容器，服务器节省 ~300MB 内存
28. 所有单元/集成测试通过
29. 端到端测试脚本 17 步全部通过

---

## 20. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 跨 schema JOIN 性能问题 | PostgreSQL 跨 schema 查询性能等同同 schema；必要时加索引 |
| GEOFlow 改 article_distributions 表结构影响监测系统 | 监测系统只读，且只依赖核心字段；表结构变更前协调 |
| 监测系统写入 monitor schema 影响 GEOFlow | schema 隔离，互不干扰 |
| 数据迁移过程停机 | 本地先验证；生产选择低峰期；准备回滚方案（第 3.2 节） |
| GEOFlow PG 宕机导致监测系统不可用 | 监测系统依赖 GEOFlow 的 PG，需共同保障 PG 高可用；可后续做只读副本 |
| keywords 字段格式不一致 | 实现前先 `SELECT keywords FROM public.articles LIMIT 5` 验证，查询后 Python 解析 |
| 导出大文件阻塞 API | 异步导出 + export_tasks 状态跟踪 |
| **Playwright Chromium 镜像体积大（+500MB）** | 服务器 14GB 内存够用；复用浏览器实例减少启动开销 |
| **Chromium 启动慢** | 首次启动 ~2s，后续复用浏览器实例；导出任务异步处理不影响用户体验 |
| **SSO 依赖 GEOFlow 可用** | GEOFlow 宕机时 admin 无法登录监测系统；需共同保障 GEOFlow 可用；client 登录不受影响 |
| **SSO code 被重放攻击** | code 一次性使用（Redis del），30s 过期；HTTPS 传输 |
| admin 账号被盗 | JWT 过期 7 天 + 操作日志审计 + GEOFlow 禁用账号后 SSO 失效 |
| 客户看到非自己 client_id 的数据 | 所有查询强制按 client_id 过滤 + admin/client 鉴权隔离 |
| docker network 配置错误 | 本地先验证；部署脚本检查容器连通性 |

---

## 21. 未来扩展点（不在本期实现）

1. **GEOFlow 后台嵌入监测 dashboard**：iframe + 一次性 token 鉴权（统一数据库后更简单）
2. **webhook 通知**：监测完成后通知客户（邮件/钉钉/企微）
3. **更多渠道 publisher**：微信公众号素材 API、其他有合法 API 的平台
4. **客户自助管理站点**：客户自己登记 domain（需 admin 审核）
5. **PG 只读副本**：监测系统查询走只读副本，避免影响 GEOFlow 写入
6. **实时监测**：WebSocket 推送检测结果到 dashboard（替代轮询）
7. **批量导入 URL**：CSV/Excel 批量录入（本期 YAGNI，后续按需加）
8. **客户自助录入 URL**：客户自己在 dashboard 录入（本期 YAGNI，后续按需加）
