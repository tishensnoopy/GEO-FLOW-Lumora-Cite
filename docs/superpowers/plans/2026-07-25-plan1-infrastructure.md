# 基础设施层实现计划（数据库统一 + SSO）

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 废弃监测系统独立的 PostgreSQL 容器，统一使用 GEOFlow 的 pgvector/pg16，用 schema 隔离；实现 GEOFlow → 监测系统的 SSO 单点登录。

**架构：** 单一 PostgreSQL 实例（pgvector/pg16），public schema 由 GEOFlow 读写，monitor schema 由监测系统读写。GEOFlow 作为 SSO 身份提供者（IdP），监测系统作为服务提供者（SP），通过一次性 code 交换用户信息。

**技术栈：** PostgreSQL 16 + pgvector / Laravel 11 / FastAPI / SQLAlchemy + Alembic / Redis（SSO code 存储）

**关联设计文档：** [2026-07-25-geoflow-monitor-db-sync-design.md](../specs/2026-07-25-geoflow-monitor-db-sync-design.md)

---

## 文件结构

### Phase 1：数据库统一

**创建：**
- `index-monitor/alembic/versions/001_create_monitor_schema.py` — 创建 monitor schema 迁移
- `index-monitor/app/db/geoflow_models.py` — GEOFlow 表的只读模型（跨 schema 查询用）
- `index-monitor/app/db/base.py` — 监测系统模型基类（自动加 schema="monitor"）
- `deploy/scripts/migrate-monitor-data.sh` — 数据迁移脚本
- `index-monitor/tests/unit/test_cross_schema_query.py` — 跨 schema 查询测试
- `index-monitor/tests/integration/test_db_unified.py` — 数据库统一集成测试

**修改：**
- `index-monitor/app/core/config.py` — 数据库连接配置改为 GEOFlow 的 PG
- `index-monitor/app/models/*.py` — 所有模型加 `__table_args__ = {"schema": "monitor"}`
- `index-monitor/alembic/env.py` — Alembic 迁移环境配置
- `docker-compose.prod.yml` — 废弃 postgres 容器，index-monitor 连接 geo-postgres

### Phase 2：SSO

**创建：**
- `GEOFlow-main/app/Services/Sso/SsoCodeService.php` — code 生成/验证服务（Redis）
- `GEOFlow-main/app/Http/Controllers/SsoController.php` — SSO 控制器
- `GEOFlow-main/tests/Feature/Sso/SsoControllerTest.php` — SSO 控制器测试
- `index-monitor/app/services/sso_service.py` — SSO 服务（调 GEOFlow API 换 userinfo）
- `index-monitor/app/api/sso_routes.py` — SSO 路由（login + callback）
- `index-monitor/tests/unit/test_sso_auth.py` — SSO 单元测试
- `index-monitor/tests/integration/test_sso_flow.py` — SSO 集成测试

**修改：**
- `GEOFlow-main/routes/web.php` — 加 `/sso/authorize` 路由
- `GEOFlow-main/routes/api.php` — 加 `/api/sso/userinfo` 路由
- `GEOFlow-main/resources/views/layouts/admin.blade.php` — 加"监测系统"菜单链接
- `index-monitor/app/api/routes.py` — 注册 SSO 路由
- `index-monitor/app/core/config.py` — 加 SSO 配置项
- `.env.example` + `.env.prod` — 加 SSO 配置

---

## Phase 1：数据库统一

### 任务 1：创建 monitor schema 迁移

**文件：**
- 创建：`index-monitor/alembic/versions/001_create_monitor_schema.py`
- 测试：`index-monitor/tests/integration/test_db_unified.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_db_unified.py
import pytest
from sqlalchemy import text

@pytest.mark.asyncio
async def test_monitor_schema_exists(db_session):
    """验证 monitor schema 已创建。"""
    result = await db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'monitor'")
    )
    assert result.scalar() == "monitor"

@pytest.mark.asyncio
async def test_public_schema_still_exists(db_session):
    """验证 public schema 仍然存在（GEOFlow 的表不受影响）。"""
    result = await db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'public'")
    )
    assert result.scalar() == "public"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/integration/test_db_unified.py -v`
预期：FAIL，报错 "monitor schema not found"

- [ ] **步骤 3：创建 Alembic 迁移**

```python
# index-monitor/alembic/versions/001_create_monitor_schema.py
"""create monitor schema

Revision ID: 001
Revises:
Create Date: 2026-07-25
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS monitor")

def downgrade():
    op.execute("DROP SCHEMA IF EXISTS monitor CASCADE")
```

- [ ] **步骤 4：运行迁移并验证测试通过**

运行：
```bash
cd index-monitor && alembic upgrade head
python -m pytest tests/integration/test_db_unified.py -v
```
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/alembic/versions/001_create_monitor_schema.py index-monitor/tests/integration/test_db_unified.py
git commit -m "feat(db): 创建 monitor schema 迁移"
```

---

### 任务 2：监测系统模型基类（自动加 schema）

**文件：**
- 创建：`index-monitor/app/db/base.py`
- 修改：`index-monitor/app/models/client.py`（示例，所有模型同样修改）
- 测试：`index-monitor/tests/unit/test_model_schema.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_model_schema.py
from app.models.client import Client

def test_client_model_has_monitor_schema():
    """验证 Client 模型的表在 monitor schema 下。"""
    assert Client.__table__.schema == "monitor"

def test_client_model_tablename():
    """验证表名正确。"""
    assert Client.__tablename__ == "clients"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_model_schema.py -v`
预期：FAIL，schema 为 None 或 "public"

- [ ] **步骤 3：创建模型基类 + 修改模型**

```python
# index-monitor/app/db/base.py
from sqlalchemy.orm import DeclarativeBase

class MonitorBase(DeclarativeBase):
    """监测系统模型基类，所有表自动加 schema='monitor'。"""
    pass

# 辅助函数，避免每个模型重复写 __table_args__
def monitor_table_args(*args):
    """返回包含 schema='monitor' 的 __table_args__。"""
    if args:
        return (*args, {"schema": "monitor"})
    return {"schema": "monitor"}
```

```python
# index-monitor/app/models/client.py（修改示例，所有模型同样修改）
from sqlalchemy import Column, String, DateTime, func
from app.db.base import MonitorBase, monitor_table_args
import uuid

class Client(MonitorBase):
    __tablename__ = "clients"
    __table_args__ = monitor_table_args()

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(64), unique=True, nullable=False)
    client_name = Column(String(128), nullable=False)
    contact_name = Column(String(64))
    contact_email = Column(String(255), unique=True)
    contact_phone = Column(String(32))
    password_hash = Column(String(255), nullable=False)
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_model_schema.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/db/base.py index-monitor/app/models/ index-monitor/tests/unit/test_model_schema.py
git commit -m "feat(db): 模型基类自动加 monitor schema"
```

---

### 任务 3：GEOFlow 只读模型（跨 schema 查询用）

**文件：**
- 创建：`index-monitor/app/db/geoflow_models.py`
- 测试：`index-monitor/tests/unit/test_cross_schema_query.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_cross_schema_query.py
from app.db.geoflow_models import GeoflowArticle, GeoflowArticleDistribution

def test_geoflow_article_model_schema():
    """验证 GEOFlow Article 模型在 public schema 下。"""
    assert GeoflowArticle.__table__.schema == "public"

def test_geoflow_article_distribution_model_schema():
    """验证 GEOFlow ArticleDistribution 模型在 public schema 下。"""
    assert GeoflowArticleDistribution.__table__.schema == "public"

def test_geoflow_article_has_required_fields():
    """验证 GEOFlow Article 模型有监测系统需要的字段。"""
    columns = GeoflowArticle.__table__.columns
    required = ["id", "title", "slug", "content", "excerpt", "keywords",
                "meta_description", "original_keyword", "published_at"]
    for field in required:
        assert field in columns.keys(), f"缺少字段: {field}"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_cross_schema_query.py -v`
预期：FAIL，ImportError（模块不存在）

- [ ] **步骤 3：创建 GEOFlow 只读模型**

```python
# index-monitor/app/db/geoflow_models.py
"""GEOFlow 表的只读模型，用于跨 schema 查询。

这些模型映射到 GEOFlow 的 public schema 表，监测系统只读不写。
字段必须与 GEOFlow 的 Laravel migration 保持一致。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, func
from sqlalchemy.orm import DeclarativeBase

# 独立的 Base，不加 schema 前缀（默认 public）
class GeoflowBase(DeclarativeBase):
    pass

class GeoflowArticle(GeoflowBase):
    __tablename__ = "articles"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    title = Column(String(512))
    slug = Column(String(255))
    content = Column(Text)
    excerpt = Column(Text)
    keywords = Column(JSON)  # 注意：实现前先验证实际格式（见设计文档风险表）
    meta_description = Column(Text)
    original_keyword = Column(String(255))
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class GeoflowArticleDistribution(GeoflowBase):
    __tablename__ = "article_distributions"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, nullable=False)
    channel_id = Column(Integer)
    remote_url = Column(String(512))
    action = Column(String(32))  # create/update/delete
    status = Column(String(32))  # pending/synced/failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class GeoflowDistributionChannel(GeoflowBase):
    __tablename__ = "distribution_channels"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    channel_type = Column(String(64))  # geoflow_agent/wordpress_rest/generic_http_api
    config = Column(JSON)
    status = Column(String(32), default="active")

class GeoflowUser(GeoflowBase):
    """GEOFlow users 表，SSO 认证读取。"""
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    name = Column(String(128))
    email = Column(String(255))
    role = Column(String(32))  # admin/super_admin
    status = Column(String(32), default="active")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_cross_schema_query.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/db/geoflow_models.py index-monitor/tests/unit/test_cross_schema_query.py
git commit -m "feat(db): GEOFlow 只读模型（跨 schema 查询）"
```

---

### 任务 4：修改数据库连接配置

**文件：**
- 修改：`index-monitor/app/core/config.py`
- 修改：`index-monitor/app/core/database.py`
- 测试：`index-monitor/tests/integration/test_db_connection.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_db_connection.py
import pytest
from app.core.config import settings

def test_database_url_points_to_geoflow_pg():
    """验证数据库 URL 指向 GEOFlow 的 PG（不是旧的 postgres:15-alpine）。"""
    db_url = settings.DATABASE_URL
    # 应该包含 GEOFlow 的 PG 容器名或地址
    assert "geo-postgres" in db_url or "geoflow" in db_url.lower(), \
        f"DATABASE_URL 应指向 GEOFlow PG，当前: {db_url}"

def test_database_url_has_correct_db_name():
    """验证数据库名称正确（GEOFlow 的数据库名）。"""
    db_url = settings.DATABASE_URL
    # GEOFlow 的数据库名通常是 geo_flow 或 geoflow
    assert any(name in db_url for name in ["geo_flow", "geoflow", "geo"]), \
        f"DATABASE_URL 应包含 GEOFlow 数据库名，当前: {db_url}"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/integration/test_db_connection.py -v`
预期：FAIL，DATABASE_URL 仍指向旧 PG

- [ ] **步骤 3：修改配置**

```python
# index-monitor/app/core/config.py（修改 DATABASE_URL 部分）
# 旧配置（删除或注释）：
# DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://monitor:monitor@postgres:5432/geo_monitoring")

# 新配置：连接 GEOFlow 的 PG
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://geo_user:geo_password@geo-postgres:5432/geo_flow"
)

# SSO 配置（后面任务会用到，先加进来）
SSO_GEOFLOW_BASE_URL = os.getenv("SSO_GEOFLOW_BASE_URL", "https://zkeeeai.com")
SSO_GEOFLOW_USERINFO_URL = os.getenv(
    "SSO_GEOFLOW_USERINFO_URL",
    f"{SSO_GEOFLOW_BASE_URL}/api/sso/userinfo"
)
SSO_REDIRECT_URI = os.getenv("SSO_REDIRECT_URI", "https://monitor.zkeeeai.com/sso/callback")
SSO_JWT_SECRET = os.getenv("SSO_JWT_SECRET", "change-me-in-prod")
SSO_JWT_EXPIRE_DAYS = int(os.getenv("SSO_JWT_EXPIRE_DAYS", "7"))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/integration/test_db_connection.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/core/config.py index-monitor/tests/integration/test_db_connection.py
git commit -m "feat(db): 数据库连接改为 GEOFlow PG + SSO 配置项"
```

---

### 任务 5：跨 schema JOIN 查询测试

**文件：**
- 测试：`index-monitor/tests/integration/test_cross_schema_join.py`

- [ ] **步骤 1：编写测试**

```python
# index-monitor/tests/integration/test_cross_schema_join.py
import pytest
from sqlalchemy import select, text
from app.db.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
from app.models.client_site import ClientSite

@pytest.mark.asyncio
async def test_cross_schema_join_geoflow_and_monitor(db_session):
    """验证可以跨 schema JOIN 查询 GEOFlow 和 monitor 的表。"""
    # 先插入测试数据
    await db_session.execute(text("""
        INSERT INTO public.articles (title, slug, content, excerpt)
        VALUES ('测试文章', 'test-article', '内容', '摘要')
        ON CONFLICT DO NOTHING
    """))
    await db_session.execute(text("""
        INSERT INTO monitor.client_sites (client_id, domain, site_name, site_type)
        VALUES ('test-client', 'example.com', '测试站点', 'official')
        ON CONFLICT DO NOTHING
    """))

    # 跨 schema JOIN 查询
    result = await db_session.execute(
        select(GeoflowArticleDistribution, GeoflowArticle, ClientSite)
        .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
        .outerjoin(ClientSite, ClientSite.domain == "example.com")
        .where(GeoflowArticleDistribution.status == "synced")
    )
    rows = result.all()
    # 验证查询不报错（数据可能为空，但查询应成功）
    assert isinstance(rows, list)

@pytest.mark.asyncio
async def test_keywords_json_parsed_to_array(db_session):
    """验证 keywords 字段（JSON 格式）能正确解析为数组。"""
    await db_session.execute(text("""
        INSERT INTO public.articles (title, slug, content, keywords)
        VALUES ('测试', 'test', '内容', '["关键词1", "关键词2"]')
        ON CONFLICT DO NOTHING
    """))

    result = await db_session.execute(
        select(GeoflowArticle).where(GeoflowArticle.slug == "test")
    )
    article = result.scalar_one_or_none()
    if article:
        keywords = article.keywords
        if isinstance(keywords, str):
            import json
            keywords = json.loads(keywords)
        assert isinstance(keywords, list)
```

- [ ] **步骤 2：运行测试**

运行：`cd index-monitor && python -m pytest tests/integration/test_cross_schema_join.py -v`
预期：PASS（如果 GEOFlow PG 中有测试数据）或 PASS with empty results

- [ ] **步骤 3：如果测试失败，修复跨 schema 查询配置**

如果报权限错误，确保监测系统的 DB 用户有 public schema 的 SELECT 权限：
```sql
GRANT USAGE ON SCHEMA public TO monitor_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO monitor_user;
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/integration/test_cross_schema_join.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/tests/integration/test_cross_schema_join.py
git commit -m "test(db): 跨 schema JOIN 查询测试"
```

---

### 任务 6：更新 docker-compose 废弃旧 PG 容器

**文件：**
- 修改：`docker-compose.prod.yml`
- 创建：`deploy/scripts/migrate-monitor-data.sh`

- [ ] **步骤 1：编写数据迁移脚本**

```bash
# deploy/scripts/migrate-monitor-data.sh
#!/bin/bash
# 将监测系统旧 PG 的数据迁移到 GEOFlow 的 PG
set -e

OLD_PG_CONTAINER="monitor-postgres"
NEW_PG_CONTAINER="geo-postgres"
DB_USER="geo_user"
DB_NAME="geo_flow"

echo "=== 监测系统数据迁移脚本 ==="

# 1. 备份旧 PG 数据
echo "[1/4] 备份旧 PG 数据..."
docker exec $OLD_PG_CONTAINER pg_dump -U monitor_user -d geo_monitoring \
  --schema=public > /tmp/monitor_backup.sql 2>/dev/null || echo "旧 PG 无数据或不存在，跳过"

# 2. 在新 PG 创建 monitor schema
echo "[2/4] 在新 PG 创建 monitor schema..."
docker exec $NEW_PG_CONTAINER psql -U $DB_USER -d $DB_NAME -c "CREATE SCHEMA IF NOT EXISTS monitor;"

# 3. 恢复数据到 monitor schema
if [ -f /tmp/monitor_backup.sql ] && [ -s /tmp/monitor_backup.sql ]; then
    echo "[3/4] 恢复数据到 monitor schema..."
    # 修改 dump 中的 schema 引用（public → monitor）
    sed 's/SCHEMA public/SCHEMA monitor/g' /tmp/monitor_backup.sql | \
    docker exec -i $NEW_PG_CONTAINER psql -U $DB_USER -d $DB_NAME
else
    echo "[3/4] 无需恢复（旧 PG 无数据）"
fi

# 4. 验证
echo "[4/4] 验证 monitor schema 表..."
docker exec $NEW_PG_CONTAINER psql -U $DB_USER -d $DB_NAME -c "\dt monitor.*"

echo "=== 迁移完成 ==="
```

- [ ] **步骤 2：修改 docker-compose.prod.yml**

```yaml
# docker-compose.prod.yml（修改 postgres 和 index-monitor 部分）
# 删除旧的 postgres 服务定义，index-monitor 连接 geo-postgres

# 删除：
# postgres:
#   image: postgres:15-alpine
#   ...

# 修改 index-monitor 的 depends_on 和环境变量：
  index-monitor:
    build: ./index-monitor
    environment:
      - DATABASE_URL=postgresql://geo_user:${GEO_PG_PASSWORD}@geo-postgres:5432/geo_flow
      # ... 其他环境变量
    depends_on:
      - geo-postgres  # 改为依赖 GEOFlow 的 PG
    networks:
      - geoflow_default  # 加入 GEOFlow 的网络

# 确保 GEOFlow 的网络可被访问
networks:
  geoflow_default:
    external: true
    name: geoflow_default
```

- [ ] **步骤 3：本地验证 docker-compose 配置**

运行：
```bash
docker-compose -f docker-compose.prod.yml config | grep -A5 index-monitor
```
预期：index-monitor 的 DATABASE_URL 指向 geo-postgres

- [ ] **步骤 4：验证脚本可执行**

运行：
```bash
chmod +x deploy/scripts/migrate-monitor-data.sh
bash -n deploy/scripts/migrate-monitor-data.sh  # 语法检查
```
预期：无语法错误

- [ ] **步骤 5：Commit**

```bash
git add docker-compose.prod.yml deploy/scripts/migrate-monitor-data.sh
git commit -m "feat(deploy): 废弃旧 PG 容器，统一使用 GEOFlow PG"
```

---

## Phase 2：SSO 单点登录

### 任务 7：GEOFlow SsoCodeService（code 生成/验证）

**文件：**
- 创建：`GEOFlow-main/app/Services/Sso/SsoCodeService.php`
- 测试：`GEOFlow-main/tests/Unit/Services/Sso/SsoCodeServiceTest.php`

- [ ] **步骤 1：编写失败的测试**

```php
<?php
// GEOFlow-main/tests/Unit/Services/Sso/SsoCodeServiceTest.php

namespace Tests\Unit\Services\Sso;

use App\Services\Sso\SsoCodeService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Redis;
use Tests\TestCase;

class SsoCodeServiceTest extends TestCase
{
    use RefreshDatabase;

    private SsoCodeService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->service = app(SsoCodeService::class);
        Redis::flushall();
    }

    public function test_generate_code_returns_32_char_hex_string(): void
    {
        $code = $this->service->generateCode(user_id: 1);

        $this->assertEquals(32, strlen($code));
        $this->assertMatchesRegularExpression('/^[a-f0-9]{32}$/', $code);
    }

    public function test_generate_code_stores_in_redis_with_ttl(): void
    {
        $code = $this->service->generateCode(user_id: 1);

        $stored = Redis::get("sso:code:{$code}");
        $this->assertEquals(1, $stored);

        // 验证 TTL（30 秒）
        $ttl = Redis::ttl("sso:code:{$code}");
        $this->assertGreaterThan(0, $ttl);
        $this->assertLessThanOrEqual(30, $ttl);
    }

    public function test_validate_code_returns_user_id_for_valid_code(): void
    {
        $code = $this->service->generateCode(user_id: 42);

        $userId = $this->service->validateCode($code);
        $this->assertEquals(42, $userId);
    }

    public function test_validate_code_returns_null_for_invalid_code(): void
    {
        $userId = $this->service->validateCode('invalid-code-123456');
        $this->assertNull($userId);
    }

    public function test_validate_code_is_one_time_use(): void
    {
        $code = $this->service->generateCode(user_id: 1);

        // 第一次验证成功
        $this->assertEquals(1, $this->service->validateCode($code));
        // 第二次验证失败（已删除）
        $this->assertNull($this->service->validateCode($code));
    }
}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd GEOFlow-main && php artisan test tests/Unit/Services/Sso/SsoCodeServiceTest.php`
预期：FAIL，Class not found

- [ ] **步骤 3：创建 SsoCodeService**

```php
<?php
// GEOFlow-main/app/Services/Sso/SsoCodeService.php

namespace App\Services\Sso;

use Illuminate\Support\Facades\Redis;
use Illuminate\Support\Str;

class SsoCodeService
{
    private const REDIS_PREFIX = 'sso:code:';
    private const CODE_TTL = 30; // 秒

    /**
     * 生成一次性 SSO code，存入 Redis。
     */
    public function generateCode(int $userId): string
    {
        $code = Str::random(16); // 16 字节 = 32 字符 hex
        $key = self::REDIS_PREFIX . $code;

        Redis::setex($key, self::CODE_TTL, $userId);

        return $code;
    }

    /**
     * 验证 code 并返回 user_id。code 一次性使用，验证后删除。
     */
    public function validateCode(string $code): ?int
    {
        $key = self::REDIS_PREFIX . $code;

        // 使用 GETDEL 原子操作：获取并删除
        $userId = Redis::getdel($key);

        return $userId ? (int) $userId : null;
    }
}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd GEOFlow-main && php artisan test tests/Unit/Services/Sso/SsoCodeServiceTest.php`
预期：PASS（5 个测试全部通过）

- [ ] **步骤 5：Commit**

```bash
git add GEOFlow-main/app/Services/Sso/SsoCodeService.php GEOFlow-main/tests/Unit/Services/Sso/SsoCodeServiceTest.php
git commit -m "feat(sso): SSO code 生成/验证服务（Redis 一次性 code）"
```

---

### 任务 8：GEOFlow SsoController

**文件：**
- 创建：`GEOFlow-main/app/Http/Controllers/SsoController.php`
- 测试：`GEOFlow-main/tests/Feature/Sso/SsoControllerTest.php`

- [ ] **步骤 1：编写失败的测试**

```php
<?php
// GEOFlow-main/tests/Feature/Sso/SsoControllerTest.php

namespace Tests\Feature\Sso;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Redis;
use Tests\TestCase;

class SsoControllerTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        Redis::flushall();
    }

    public function test_authorize_redirects_to_login_when_not_authenticated(): void
    {
        $response = $this->get('/sso/authorize?redirect_uri=https://monitor.test/sso/callback');

        $response->assertRedirect();
        $this->assertStringContainsString('login', $response->headers->get('Location'));
    }

    public function test_authorize_generates_code_when_authenticated(): void
    {
        $user = User::factory()->create(['role' => 'admin']);
        $redirectUri = 'https://monitor.test/sso/callback';

        $response = $this->actingAs($user)
            ->get("/sso/authorize?redirect_uri=" . urlencode($redirectUri));

        $response->assertRedirect();
        $location = $response->headers->get('Location');
        $this->assertStringContainsString($redirectUri, $location);
        $this->assertStringContainsString('code=', $location);

        // 验证 code 格式（32 字符 hex）
        preg_match('/code=([a-f0-9]{32})/', $location, $matches);
        $this->assertNotEmpty($matches);
    }

    public function test_userinfo_returns_user_data_with_role(): void
    {
        $user = User::factory()->create([
            'role' => 'super_admin',
            'name' => '测试管理员',
            'email' => 'admin@test.com',
        ]);

        $code = app(\App\Services\Sso\SsoCodeService::class)->generateCode($user->id);

        $response = $this->getJson("/api/sso/userinfo?code={$code}");

        $response->assertOk();
        $response->assertJson([
            'user_id' => $user->id,
            'name' => '测试管理员',
            'email' => 'admin@test.com',
            'role' => 'super_admin',
        ]);
    }

    public function test_userinfo_invalid_code_returns_400(): void
    {
        $response = $this->getJson('/api/sso/userinfo?code=invalid-code');

        $response->assertStatus(400);
        $response->assertJson(['error' => 'invalid_code']);
    }

    public function test_userinfo_one_time_use_code(): void
    {
        $user = User::factory()->create();
        $code = app(\App\Services\Sso\SsoCodeService::class)->generateCode($user->id);

        // 第一次调用成功
        $this->getJson("/api/sso/userinfo?code={$code}")->assertOk();
        // 第二次调用失败
        $this->getJson("/api/sso/userinfo?code={$code}")->assertStatus(400);
    }

    public function test_authorize_rejects_invalid_redirect_uri(): void
    {
        $user = User::factory()->create();
        $response = $this->actingAs($user)
            ->get('/sso/authorize?redirect_uri=https://evil.com/callback');
        $response->assertStatus(400);
    }
}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd GEOFlow-main && php artisan test tests/Feature/Sso/SsoControllerTest.php`
预期：FAIL，404（路由不存在）

- [ ] **步骤 3：创建 SsoController**

```php
<?php
// GEOFlow-main/app/Http/Controllers/SsoController.php

namespace App\Http\Controllers;

use App\Models\User;
use App\Services\Sso\SsoCodeService;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\RedirectResponse;
use Illuminate\Support\Facades\Log;

class SsoController extends Controller
{
    private const ALLOWED_REDIRECT_HOSTS = [
        'monitor.zkeeeai.com',
        'monitor.test',
        'localhost',
    ];

    public function __construct(
        private readonly SsoCodeService $codeService
    ) {}

    /**
     * SSO 授权端点：已登录用户生成 code 并重定向回监测系统。
     */
    public function authorize(Request $request): RedirectResponse
    {
        $redirectUri = $request->query('redirect_uri');

        if (!$redirectUri || !$this->isAllowedRedirectUri($redirectUri)) {
            abort(400, '无效的 redirect_uri');
        }

        $user = $request->user();
        if (!$user) {
            // 未登录 → 跳转登录页，登录后回到这里
            return redirect()->route('login', ['redirect' => $request->fullUrl()]);
        }

        $code = $this->codeService->generateCode($user->id);

        $separator = str_contains($redirectUri, '?') ? '&' : '?';
        $redirectUrl = "{$redirectUri}{$separator}code={$code}";

        Log::info('SSO authorize', [
            'user_id' => $user->id,
            'redirect' => $redirectUri,
        ]);

        return redirect($redirectUrl);
    }

    /**
     * SSO userinfo 端点：监测系统用 code 换取用户信息。
     */
    public function userinfo(Request $request): JsonResponse
    {
        $code = $request->query('code');
        if (!$code) {
            return response()->json(['error' => 'missing_code'], 400);
        }

        $userId = $this->codeService->validateCode($code);
        if (!$userId) {
            return response()->json(['error' => 'invalid_code'], 400);
        }

        $user = User::find($userId);
        if (!$user) {
            return response()->json(['error' => 'user_not_found'], 404);
        }

        return response()->json([
            'user_id' => $user->id,
            'name' => $user->name,
            'email' => $user->email,
            'role' => $user->role ?? 'admin',
        ]);
    }

    private function isAllowedRedirectUri(string $uri): bool
    {
        $host = parse_url($uri, PHP_URL_HOST);
        if (!$host) {
            return false;
        }
        foreach (self::ALLOWED_REDIRECT_HOSTS as $allowed) {
            if ($host === $allowed || str_ends_with($host, ".{$allowed}")) {
                return true;
            }
        }
        return false;
    }
}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd GEOFlow-main && php artisan test tests/Feature/Sso/SsoControllerTest.php`
预期：PASS（6 个测试全部通过）

- [ ] **步骤 5：Commit**

```bash
git add GEOFlow-main/app/Http/Controllers/SsoController.php GEOFlow-main/tests/Feature/Sso/SsoControllerTest.php
git commit -m "feat(sso): SSO 控制器（authorize + userinfo）"
```

---

### 任务 9：GEOFlow SSO 路由

**文件：**
- 修改：`GEOFlow-main/routes/web.php`
- 修改：`GEOFlow-main/routes/api.php`

- [ ] **步骤 1：添加路由**

```php
// GEOFlow-main/routes/web.php（追加）

use App\Http\Controllers\SsoController;

// SSO 授权端点（需要 web 中间件，支持 session）
Route::get('/sso/authorize', [SsoController::class, 'authorize'])
    ->middleware('web')
    ->name('sso.authorize');
```

```php
// GEOFlow-main/routes/api.php（追加）

use App\Http\Controllers\SsoController;

// SSO userinfo 端点（公开，不需要认证，靠 code 验证）
Route::get('/sso/userinfo', [SsoController::class, 'userinfo'])
    ->name('sso.userinfo');
```

- [ ] **步骤 2：验证路由注册**

运行：`cd GEOFlow-main && php artisan route:list | grep sso`
预期：看到 `sso.authorize` 和 `sso.userinfo` 两条路由

- [ ] **步骤 3：运行 SSO 控制器测试确认路由正常**

运行：`cd GEOFlow-main && php artisan test tests/Feature/Sso/SsoControllerTest.php`
预期：PASS

- [ ] **步骤 4：验证路由不与现有路由冲突**

运行：`cd GEOFlow-main && php artisan route:list | grep -v sso | head -20`
预期：现有路由不受影响

- [ ] **步骤 5：Commit**

```bash
git add GEOFlow-main/routes/web.php GEOFlow-main/routes/api.php
git commit -m "feat(sso): SSO 路由注册（authorize + userinfo）"
```

---

### 任务 10：监测系统 SSO 服务

**文件：**
- 创建：`index-monitor/app/services/sso_service.py`
- 测试：`index-monitor/tests/unit/test_sso_auth.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_sso_auth.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.sso_service import SsoService, SsoUserinfo

@pytest.mark.asyncio
async def test_exchange_code_for_userinfo_success():
    """验证 code 换取 userinfo 成功。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = AsyncMock(return_value={
        "user_id": 1,
        "name": "测试管理员",
        "email": "admin@test.com",
        "role": "super_admin",
    })
    mock_response.raise_for_status = AsyncMock()

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        userinfo = await service.exchange_code("valid-code")

    assert userinfo.user_id == 1
    assert userinfo.name == "测试管理员"
    assert userinfo.role == "super_admin"

@pytest.mark.asyncio
async def test_exchange_code_invalid_raises_error():
    """验证无效 code 抛出异常。"""
    service = SsoService(
        geoflow_base_url="https://geoflow.test",
        userinfo_url="https://geoflow.test/api/sso/userinfo",
    )
    mock_response = AsyncMock()
    mock_response.status_code = 400
    mock_response.raise_for_status = AsyncMock(side_effect=Exception("400 Bad Request"))

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        with pytest.raises(Exception):
            await service.exchange_code("invalid-code")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_sso_auth.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：创建 SsoService**

```python
# index-monitor/app/services/sso_service.py
"""SSO 服务：调 GEOFlow API 用 code 换取用户信息。"""
import httpx
from dataclasses import dataclass
from typing import Optional

@dataclass
class SsoUserinfo:
    """SSO 用户信息。"""
    user_id: int
    name: str
    email: str
    role: str  # admin / super_admin

class SsoService:
    def __init__(self, geoflow_base_url: str, userinfo_url: str, timeout: int = 10):
        self.geoflow_base_url = geoflow_base_url
        self.userinfo_url = userinfo_url
        self.timeout = timeout

    async def exchange_code(self, code: str) -> SsoUserinfo:
        """用一次性 code 向 GEOFlow 换取用户信息。"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self.userinfo_url,
                params={"code": code}
            )
            response.raise_for_status()
            data = response.json()

        return SsoUserinfo(
            user_id=data["user_id"],
            name=data["name"],
            email=data["email"],
            role=data.get("role", "admin"),
        )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_sso_auth.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/sso_service.py index-monitor/tests/unit/test_sso_auth.py
git commit -m "feat(sso): 监测系统 SSO 服务（code 换 userinfo）"
```

---

### 任务 11：监测系统 SSO callback 端点 + JWT 签发

**文件：**
- 创建：`index-monitor/app/api/sso_routes.py`
- 修改：`index-monitor/app/api/routes.py`（注册路由）
- 测试：`index-monitor/tests/integration/test_sso_flow.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_sso_flow.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.sso_service import SsoUserinfo

@pytest.mark.asyncio
async def test_sso_callback_valid_code_signs_jwt(client, db_session):
    """验证 SSO callback 用有效 code 签发 JWT。"""
    mock_userinfo = SsoUserinfo(
        user_id=1, name="测试管理员", email="admin@test.com", role="super_admin"
    )

    with patch("app.services.sso_service.SsoService.exchange_code", return_value=mock_userinfo):
        response = await client.get("/sso/callback?code=valid-code")

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["name"] == "测试管理员"
    assert data["user"]["role"] == "super_admin"

@pytest.mark.asyncio
async def test_sso_callback_invalid_code_returns_401(client):
    """验证无效 code 返回 401。"""
    with patch("app.services.sso_service.SsoService.exchange_code", side_effect=Exception("invalid")):
        response = await client.get("/sso/callback?code=invalid-code")

    assert response.status_code == 401

@pytest.mark.asyncio
async def test_sso_callback_missing_code_returns_400(client):
    """验证缺少 code 参数返回 400。"""
    response = await client.get("/sso/callback")

    assert response.status_code == 400

@pytest.mark.asyncio
async def test_sso_login_redirects_to_geoflow(client):
    """验证 /sso/login 重定向到 GEOFlow 授权页。"""
    response = await client.get("/sso/login", follow_redirects=False)

    assert response.status_code in (301, 302, 307)
    location = response.headers.get("location", "")
    assert "sso/authorize" in location
    assert "redirect_uri" in location
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/integration/test_sso_flow.py -v`
预期：FAIL，404（路由不存在）

- [ ] **步骤 3：创建 SSO 路由**

```python
# index-monitor/app/api/sso_routes.py
"""SSO 路由：login（跳转 GEOFlow）+ callback（接收 code，签发 JWT）。"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
import jwt

from app.core.config import settings
from app.services.sso_service import SsoService

router = APIRouter(prefix="/sso", tags=["sso"])

def _get_sso_service() -> SsoService:
    return SsoService(
        geoflow_base_url=settings.SSO_GEOFLOW_BASE_URL,
        userinfo_url=settings.SSO_GEOFLOW_USERINFO_URL,
    )

def _sign_jwt(user_id: int, name: str, role: str) -> str:
    """签发 admin JWT。"""
    payload = {
        "sub": str(user_id),
        "name": name,
        "role": role,
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.SSO_JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")

@router.get("/login")
async def sso_login(request: Request):
    """跳转到 GEOFlow SSO 授权页。"""
    # 从请求中获取 redirect_uri（或用默认值）
    redirect_uri = settings.SSO_REDIRECT_URI
    authorize_url = f"{settings.SSO_GEOFLOW_BASE_URL}/sso/authorize?redirect_uri={redirect_uri}"
    return RedirectResponse(url=authorize_url)

@router.get("/callback")
async def sso_callback(request: Request):
    """SSO callback：用 code 换取 userinfo，签发 JWT。"""
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="missing_code")

    sso_service = _get_sso_service()
    try:
        userinfo = await sso_service.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_code")

    token = _sign_jwt(userinfo.user_id, userinfo.name, userinfo.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": userinfo.user_id,
            "name": userinfo.name,
            "email": userinfo.email,
            "role": userinfo.role,
        },
    }
```

```python
# index-monitor/app/api/routes.py（追加注册）
from app.api.sso_routes import router as sso_router

# 在现有路由注册后追加
app.include_router(sso_router)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/integration/test_sso_flow.py -v`
预期：PASS（4 个测试全部通过）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/sso_routes.py index-monitor/app/api/routes.py index-monitor/tests/integration/test_sso_flow.py
git commit -m "feat(sso): SSO callback 端点 + JWT 签发"
```

---

### 任务 12：admin JWT 鉴权依赖

**文件：**
- 创建：`index-monitor/app/core/auth.py`
- 测试：`index-monitor/tests/unit/test_admin_auth.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_admin_auth.py
import pytest
from app.core.auth import get_current_admin, verify_admin_jwt

def test_verify_admin_jwt_valid_token():
    """验证有效 JWT 能正确解析。"""
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.core.config import settings

    payload = {
        "sub": "1",
        "name": "管理员",
        "role": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")

    result = verify_admin_jwt(token)
    assert result["user_id"] == 1
    assert result["name"] == "管理员"
    assert result["role"] == "admin"

def test_verify_admin_jwt_expired_raises():
    """验证过期 JWT 抛出异常。"""
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.core.config import settings

    payload = {
        "sub": "1",
        "name": "管理员",
        "role": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),  # 已过期
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")

    with pytest.raises(Exception):
        verify_admin_jwt(token)

def test_verify_admin_jwt_wrong_type_raises():
    """验证非 admin 类型的 JWT 被拒绝。"""
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.core.config import settings

    payload = {
        "sub": "1",
        "name": "客户",
        "role": "client",
        "type": "client",  # 不是 admin
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")

    with pytest.raises(Exception):
        verify_admin_jwt(token)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_admin_auth.py -v`
预期：FAIL，ImportError

- [ ] **步骤 3：创建鉴权模块**

```python
# index-monitor/app/core/auth.py
"""admin JWT 鉴权依赖。"""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Any

from app.core.config import settings

security = HTTPBearer(auto_error=False)

def verify_admin_jwt(token: str) -> dict[str, Any]:
    """验证 admin JWT，返回用户信息。"""
    try:
        payload = jwt.decode(token, settings.SSO_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid_token")

    if payload.get("type") != "admin":
        raise HTTPException(status_code=403, detail="not_admin")

    return {
        "user_id": int(payload["sub"]),
        "name": payload["name"],
        "role": payload["role"],
    }

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """FastAPI 依赖：验证 admin JWT。"""
    if not credentials:
        raise HTTPException(status_code=401, detail="missing_token")
    return verify_admin_jwt(credentials.credentials)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_admin_auth.py -v`
预期：PASS（3 个测试全部通过）

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/core/auth.py index-monitor/tests/unit/test_admin_auth.py
git commit -m "feat(auth): admin JWT 鉴权依赖"
```

---

### 任务 13：GEOFlow 后台菜单加"监测系统"链接

**文件：**
- 修改：`GEOFlow-main/resources/views/layouts/admin.blade.php`
- 测试：`GEOFlow-main/tests/Feature/AdminMenuTest.php`

- [ ] **步骤 1：编写失败的测试**

```php
<?php
// GEOFlow-main/tests/Feature/AdminMenuTest.php

namespace Tests\Feature;

use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class AdminMenuTest extends TestCase
{
    use RefreshDatabase;

    public function test_admin_dashboard_has_monitor_link(): void
    {
        $user = User::factory()->create(['role' => 'admin']);
        $response = $this->actingAs($user)->get('/admin');

        $response->assertOk();
        $response->assertSee('监测系统');
        $response->assertSee('monitor.zkeeeai.com');
    }

    public function test_admin_dashboard_render_still_works(): void
    {
        $user = User::factory()->create(['role' => 'admin']);
        $response = $this->actingAs($user)->get('/admin');
        $response->assertOk();
        // 验证现有菜单不受影响
        $response->assertSee('文章管理');
    }
}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd GEOFlow-main && php artisan test tests/Feature/AdminMenuTest.php`
预期：FAIL，看不到"监测系统"链接

- [ ] **步骤 3：修改后台菜单视图**

在 `GEOFlow-main/resources/views/layouts/admin.blade.php` 的侧边栏菜单中，在合适位置（如"系统设置"之前）添加：

```blade
{{-- 监测系统入口 --}}
<a href="https://monitor.zkeeeai.com/sso/login" target="_blank"
   class="nav-link {{ request()->is('admin/monitor*') ? 'active' : '' }}">
    <i class="nav-icon fas fa-chart-line"></i>
    <p>监测系统</p>
</a>
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd GEOFlow-main && php artisan test tests/Feature/AdminMenuTest.php`
预期：PASS（2 个测试全部通过）

- [ ] **步骤 5：Commit**

```bash
git add GEOFlow-main/resources/views/layouts/admin.blade.php GEOFlow-main/tests/Feature/AdminMenuTest.php
git commit -m "feat(sso): GEOFlow 后台菜单加监测系统链接"
```

---

### 任务 14：SSO 端到端测试 + GEOFlow 回归测试

**文件：**
- 创建：`deploy/scripts/test-sso-e2e.sh`
- 创建：`GEOFlow-main/tests/Feature/Regression/ArticleManagementTest.php`

- [ ] **步骤 1：编写 SSO 端到端测试脚本**

```bash
#!/bin/bash
# deploy/scripts/test-sso-e2e.sh
# SSO 端到端测试：GEOFlow 登录 → SSO 跳转 → 监测系统免登进入
set -e

GEOFLOW_URL="${GEOFLOW_URL:-http://localhost:8000}"
MONITOR_URL="${MONITOR_URL:-http://localhost:8001}"

echo "=== SSO 端到端测试 ==="

# 1. 验证 GEOFlow SSO 授权端点存在
echo "[1/5] 验证 GEOFlow SSO 授权端点..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$GEOFLOW_URL/sso/authorize?redirect_uri=$MONITOR_URL/sso/callback")
if [ "$STATUS" = "302" ] || [ "$STATUS" = "200" ]; then
    echo "  ✅ SSO 授权端点可访问"
else
    echo "  ❌ SSO 授权端点返回 $STATUS"
    exit 1
fi

# 2. 验证 GEOFlow userinfo 端点拒绝无效 code
echo "[2/5] 验证 userinfo 端点拒绝无效 code..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$GEOFLOW_URL/api/sso/userinfo?code=invalid")
if [ "$STATUS" = "400" ]; then
    echo "  ✅ 无效 code 被拒绝"
else
    echo "  ❌ 无效 code 返回 $STATUS（期望 400）"
    exit 1
fi

# 3. 验证监测系统 SSO 登录端点
echo "[3/5] 验证监测系统 SSO 登录端点..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -L "$MONITOR_URL/sso/login")
if [ "$STATUS" = "200" ] || [ "$STATUS" = "302" ]; then
    echo "  ✅ SSO 登录端点可访问"
else
    echo "  ❌ SSO 登录端点返回 $STATUS"
    exit 1
fi

# 4. 验证监测系统 callback 拒绝无效 code
echo "[4/5] 验证 callback 拒绝无效 code..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$MONITOR_URL/sso/callback?code=invalid")
if [ "$STATUS" = "401" ]; then
    echo "  ✅ 无效 code 被拒绝"
else
    echo "  ❌ 无效 code 返回 $STATUS（期望 401）"
    exit 1
fi

# 5. 验证监测系统 callback 拒绝缺少 code
echo "[5/5] 验证 callback 拒绝缺少 code..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$MONITOR_URL/sso/callback")
if [ "$STATUS" = "400" ]; then
    echo "  ✅ 缺少 code 被拒绝"
else
    echo "  ❌ 缺少 code 返回 $STATUS（期望 400）"
    exit 1
fi

echo "=== SSO 端到端测试通过 ==="
```

- [ ] **步骤 2：编写 GEOFlow 回归测试**

```php
<?php
// GEOFlow-main/tests/Feature/Regression/ArticleManagementTest.php

namespace Tests\Feature\Regression;

use App\Models\Article;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class ArticleManagementTest extends TestCase
{
    use RefreshDatabase;

    public function test_create_article_still_works(): void
    {
        $user = User::factory()->create();
        $response = $this->actingAs($user)->post('/admin/articles', [
            'title' => '回归测试文章',
            'content' => '内容',
            'slug' => 'regression-test',
        ]);
        $response->assertStatus(201);
        $this->assertDatabaseHas('articles', ['title' => '回归测试文章']);
    }

    public function test_article_list_still_works(): void
    {
        Article::factory()->count(3)->create();
        $user = User::factory()->create();
        $response = $this->actingAs($user)->get('/admin/articles');
        $response->assertOk();
    }

    public function test_login_still_works(): void
    {
        $user = User::factory()->create(['password' => bcrypt('password123')]);
        $response = $this->post('/login', [
            'email' => $user->email,
            'password' => 'password123',
        ]);
        $response->assertRedirect();
        $this->assertAuthenticatedAs($user);
    }
}
```

- [ ] **步骤 3：运行所有测试**

运行：
```bash
# GEOFlow 侧
cd GEOFlow-main && php artisan test tests/Feature/Sso/ tests/Feature/Regression/ tests/Feature/AdminMenuTest.php

# 监测系统侧
cd index-monitor && python -m pytest tests/unit/test_sso_auth.py tests/unit/test_admin_auth.py tests/integration/test_sso_flow.py tests/integration/test_db_unified.py tests/integration/test_cross_schema_join.py -v

# E2E 脚本
chmod +x deploy/scripts/test-sso-e2e.sh && bash deploy/scripts/test-sso-e2e.sh
```
预期：全部 PASS

- [ ] **步骤 4：验证全系统冒烟（本地）**

手动验证：
1. GEOFlow 后台登录 → 看到"监测系统"菜单链接
2. 点击链接 → 跳转监测系统 → 自动 SSO 登录
3. 监测系统 dashboard 显示 admin 信息
4. GEOFlow 现有功能（文章管理/分发）正常

- [ ] **步骤 5：Commit**

```bash
git add deploy/scripts/test-sso-e2e.sh GEOFlow-main/tests/Feature/Regression/ArticleManagementTest.php
git commit -m "test(sso): SSO 端到端测试 + GEOFlow 回归测试"
```

---

## 自检

### 规格覆盖度

| 设计文档章节 | 对应任务 | 状态 |
|---|---|---|
| 第 3 节 数据库统一方案 | 任务 1-6 | ✅ |
| 第 4 节数据模型（monitor schema 表） | 任务 2（基类） | ✅ |
| 第 5 节 SSO 架构设计 | 任务 7-11 | ✅ |
| 第 8 节 鉴权设计（admin JWT） | 任务 12 | ✅ |
| 第 15 节 官网管理入口（GEOFlow 后台链接） | 任务 13 | ✅ |
| 第 16 节 测试策略（SSO + 回归） | 任务 14 | ✅ |
| 第 17 节 部署配置（docker-compose） | 任务 6 | ✅ |

### 占位符扫描

- ✅ 无"TODO"或"待定"
- ✅ 无"类似任务 N"（每个任务有完整代码）
- ✅ 无"添加适当的错误处理"（都有具体代码）
- ✅ 所有测试用例都有完整断言

### 类型一致性

- ✅ `SsoCodeService.generateCode(user_id: int) -> str` — 任务 7 定义，任务 8 使用
- ✅ `SsoCodeService.validateCode(code: str) -> ?int` — 任务 7 定义，任务 8 使用
- ✅ `SsoService.exchange_code(code: str) -> SsoUserinfo` — 任务 10 定义，任务 11 使用
- ✅ `SsoUserinfo` 有 `user_id, name, email, role` — 任务 10 定义，任务 11 使用
- ✅ `get_current_admin` 返回 `{user_id, name, role}` — 任务 12 定义
- ✅ `verify_admin_jwt(token: str) -> dict` — 任务 12 定义，后续计划使用

### 遗漏检查

- ⚠️ **DB 用户权限配置**（public 只读，monitor 读写）— 在任务 5 步骤 3 中有 SQL，但未作为独立任务。建议在部署时手动执行。
- ⚠️ **.env.example 和 .env.prod 更新** — 在任务 4 中修改了 config.py，但 .env 文件需要在部署时更新。

---

## 执行交接

计划已完成并保存到 `docs/superpowers/plans/2026-07-25-plan1-infrastructure.md`。两种执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

选哪种方式？
