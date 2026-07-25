# M1：数据模型 + 鉴权地基 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 建立 Plan 2 全部功能所需的数据模型（4 张新表 + 2 张表扩展字段）和鉴权依赖（super_admin + unified user + 密码强度校验）。

**架构：** 所有新表归属 `monitor` schema（用 `monitor_table_args()`）；鉴权复用 `app/core/auth.py` 的 `verify_admin_jwt`（已存在），补 `get_current_super_admin` / `get_current_user`；密码强度校验独立为 `app/utils/validators.py`。

**前置条件：**
- Plan 1 已完成（alembic 002 已迁移表到 monitor schema）
- 本地 PG 容器 `geo-postgres-local` 运行中
- `alembic current` 输出 `002 (move monitor tables from public to monitor schema)`

**关联设计文档：** [第 4 节 数据模型](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#4-数据模型) + [第 8 节 鉴权设计](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#8-鉴权设计) + [第 21.6 节 合规](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#216-操作留痕与合规)

---

## 任务 1：ManualDistribution 模型 + 迁移

**文件：**
- 创建：`index-monitor/app/models/manual_distribution.py`
- 创建：`index-monitor/alembic/versions/003_create_manual_distributions.py`
- 修改：`index-monitor/app/models/__init__.py`（注册模型）
- 测试：`index-monitor/tests/unit/test_manual_distribution.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_manual_distribution.py
"""ManualDistribution 模型测试。

验证目标：
1. 模型 __tablename__ = 'manual_distributions'，schema='monitor'
2. 字段集合与设计文档第 4.1 节一致
3. UniqueConstraint(client_id, remote_url) 存在且命名正确
4. DB 反射表结构与模型一致（集成测试，需 db_session fixture）
"""
import pytest
from sqlalchemy import inspect, UniqueConstraint

from app.models.manual_distribution import ManualDistribution


def test_manual_distribution_tablename():
    assert ManualDistribution.__tablename__ == "manual_distributions"


def test_manual_distribution_schema_is_monitor():
    """表必须归属 monitor schema（通过 monitor_table_args）。"""
    table_args = ManualDistribution.__table_args__
    # monitor_table_args 返回 (UniqueConstraint, {"schema": "monitor"})
    schema_dict = table_args[-1] if isinstance(table_args, tuple) else table_args
    assert schema_dict.get("schema") == "monitor"


def test_manual_distribution_required_columns():
    """字段集合与设计文档第 4.1 节一致。"""
    cols = {c.name for c in ManualDistribution.__table__.columns}
    expected = {
        "id", "client_id", "remote_url", "status", "note",
        "created_by_admin_id", "created_at", "updated_at",
    }
    assert cols == expected, f"缺失字段：{expected - cols}，多余字段：{cols - expected}"


def test_manual_distribution_unique_constraint():
    """UniqueConstraint(client_id, remote_url) 必须存在且命名为 uq_manual_client_url。"""
    table_args = ManualDistribution.__table_args__
    constraints = [a for a in table_args if isinstance(a, UniqueConstraint)] if isinstance(table_args, tuple) else []
    assert len(constraints) == 1, f"期望 1 个 UniqueConstraint，实际 {len(constraints)}"
    uc = constraints[0]
    col_names = tuple(sorted(c.name for c in uc.columns))
    assert col_names == ("client_id", "remote_url")
    assert uc.name == "uq_manual_client_url"


@pytest.mark.asyncio
async def test_manual_distribution_table_exists_in_db(db_session):
    """DB 中 monitor.manual_distributions 表存在且列匹配（集成测试）。"""
    sync_url = (
        f"postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow"
    )
    from sqlalchemy import create_engine
    engine = create_engine(sync_url)
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names(schema="monitor"))
    assert "manual_distributions" in db_tables, "monitor.manual_distributions 表不存在，请先运行 alembic upgrade head"
    db_cols = {c["name"] for c in inspector.get_columns("manual_distributions", schema="monitor")}
    model_cols = {c.name for c in ManualDistribution.__table__.columns}
    assert db_cols == model_cols, f"DB 列={db_cols}，模型列={model_cols}"
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_manual_distribution.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.models.manual_distribution'`

- [ ] **步骤 3：编写模型实现代码**

```python
# index-monitor/app/models/manual_distribution.py
"""手动录入的 URL 分发记录。

运营 admin 可手动录入 URL（不依赖 GEOFlow 分发），用于监测非 GEOFlow 渠道
发布的文章。与 GEOFlow 的 public.article_distributions 互补：
- GEOFlow 分发 → 跨 schema 查询自动可见（source='geoflow'）
- 手动录入 → 写入 monitor.manual_distributions（source='manual'）

唯一约束 (client_id, remote_url)：同一客户的同一 URL 不能重复录入。
跨客户允许同一 URL（不同客户可能监测同一篇文章）。
"""
from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ManualDistribution(Base):
    __tablename__ = "manual_distributions"
    __table_args__ = monitor_table_args(
        UniqueConstraint("client_id", "remote_url", name="uq_manual_client_url"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    note = Column(Text, nullable=True)
    created_by_admin_id = Column(Integer, nullable=True)  # GEOFlow admins.id
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

```python
# index-monitor/app/models/manual_distribution.py（修正：导入 Integer）
from sqlalchemy import Column, String, DateTime, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ManualDistribution(Base):
    __tablename__ = "manual_distributions"
    __table_args__ = monitor_table_args(
        UniqueConstraint("client_id", "remote_url", name="uq_manual_client_url"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    note = Column(Text, nullable=True)
    created_by_admin_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 4：编写 Alembic 迁移**

```python
# index-monitor/alembic/versions/003_create_manual_distributions.py
"""create manual_distributions table

Revision ID: 003
Revises: 002
Create Date: 2026-07-25

新建 monitor.manual_distributions 表——运营手动录入的 URL 分发记录。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_distributions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("remote_url", sa.String(512), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="synced", index=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_by_admin_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "remote_url", name="uq_manual_client_url"),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("manual_distributions", schema="monitor")
```

- [ ] **步骤 5：运行迁移 + 测试验证通过 + Commit**

```bash
# 运行迁移
cd index-monitor && alembic upgrade head

# 运行测试
pytest tests/unit/test_manual_distribution.py -v
# 预期：PASS

# 注册模型到 __init__.py（如果存在该文件且需要显式注册）
# Commit
git add index-monitor/app/models/manual_distribution.py \
        index-monitor/app/models/__init__.py \
        index-monitor/alembic/versions/003_create_manual_distributions.py \
        index-monitor/tests/unit/test_manual_distribution.py
git commit -m "feat(monitor): add ManualDistribution model + migration 003

新建 monitor.manual_distributions 表用于运营手动录入 URL。
唯一约束 (client_id, remote_url) 防同一客户重复录入。
设计文档第 4.1 节。"
```

---

## 任务 2：AdminAuditLog 模型 + 迁移

**文件：**
- 创建：`index-monitor/app/models/admin_audit_log.py`
- 创建：`index-monitor/alembic/versions/004_create_admin_audit_logs.py`
- 测试：`index-monitor/tests/unit/test_admin_audit_log.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_admin_audit_log.py
"""AdminAuditLog 模型测试。

验证目标：
1. __tablename__ = 'admin_audit_logs'，schema='monitor'
2. 字段集合与设计文档第 4.1 节一致
3. DB 反射表结构与模型一致
"""
import pytest
from sqlalchemy import inspect

from app.models.admin_audit_log import AdminAuditLog


def test_audit_log_tablename():
    assert AdminAuditLog.__tablename__ == "admin_audit_logs"


def test_audit_log_schema_is_monitor():
    table_args = AdminAuditLog.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_audit_log_required_columns():
    cols = {c.name for c in AdminAuditLog.__table__.columns}
    expected = {
        "id", "admin_user_id", "admin_name", "action",
        "target_type", "target_id", "detail",
        "ip_address", "user_agent", "created_at",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


@pytest.mark.asyncio
async def test_audit_log_table_exists_in_db(db_session):
    from sqlalchemy import create_engine
    sync_url = "postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow"
    engine = create_engine(sync_url)
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names(schema="monitor"))
    assert "admin_audit_logs" in db_tables
    db_cols = {c["name"] for c in inspector.get_columns("admin_audit_logs", schema="monitor")}
    model_cols = {c.name for c in AdminAuditLog.__table__.columns}
    assert db_cols == model_cols
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_admin_audit_log.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.models.admin_audit_log'`

- [ ] **步骤 3：编写模型实现代码**

```python
# index-monitor/app/models/admin_audit_log.py
"""管理员操作审计日志。

记录 admin 在监测系统的所有操作（创建客户/录入 URL/触发检测/导出等），
用于合规追溯。设计文档第 10 节。

字段说明：
- admin_user_id：GEOFlow admins.id（SSO 传递）
- admin_name：操作时 admin 显示名（冗余存储，避免 admin 改名后日志失联）
- action：操作类型（见设计文档第 10.2 节 action 清单）
- target_type/target_id：操作对象（client/distribution/client_site/export_task）
- detail：JSON 字符串，操作详情（如 {"url": "...", "client_id": "..."}）
- ip_address/user_agent：请求来源（合规留痕）
"""
from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_user_id = Column(Integer, nullable=False, index=True)
    admin_name = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
```

- [ ] **步骤 4：编写 Alembic 迁移**

```python
# index-monitor/alembic/versions/004_create_admin_audit_logs.py
"""create admin_audit_logs table

Revision ID: 004
Revises: 003
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("admin_user_id", sa.Integer, nullable=False, index=True),
        sa.Column("admin_name", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("admin_audit_logs", schema="monitor")
```

- [ ] **步骤 5：运行迁移 + 测试验证通过 + Commit**

```bash
cd index-monitor && alembic upgrade head
pytest tests/unit/test_admin_audit_log.py -v
# 预期：PASS

git add index-monitor/app/models/admin_audit_log.py \
        index-monitor/alembic/versions/004_create_admin_audit_logs.py \
        index-monitor/tests/unit/test_admin_audit_log.py
git commit -m "feat(monitor): add AdminAuditLog model + migration 004

新建 monitor.admin_audit_logs 表记录 admin 操作（合规留痕）。
设计文档第 10 节。"
```

---

## 任务 3：ExportTask 模型 + 迁移

**文件：**
- 创建：`index-monitor/app/models/export_task.py`
- 创建：`index-monitor/alembic/versions/005_create_export_tasks.py`
- 测试：`index-monitor/tests/unit/test_export_task.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_export_task.py
"""ExportTask 模型测试。"""
import pytest
from sqlalchemy import inspect

from app.models.export_task import ExportTask


def test_export_task_tablename():
    assert ExportTask.__tablename__ == "export_tasks"


def test_export_task_schema_is_monitor():
    table_args = ExportTask.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_export_task_required_columns():
    cols = {c.name for c in ExportTask.__table__.columns}
    expected = {
        "id", "client_id", "requested_by", "requested_by_role",
        "export_type", "date_from", "date_to", "status",
        "file_path", "file_size", "error_message",
        "created_at", "completed_at",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


def test_export_task_status_default():
    """status 默认 'pending'。"""
    status_col = ExportTask.__table__.columns["status"]
    assert status_col.default.arg == "pending"


@pytest.mark.asyncio
async def test_export_task_table_exists_in_db(db_session):
    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow")
    inspector = inspect(engine)
    assert "export_tasks" in set(inspector.get_table_names(schema="monitor"))
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_export_task.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.models.export_task'`

- [ ] **步骤 3：编写模型实现代码**

```python
# index-monitor/app/models/export_task.py
"""导出任务记录。

异步导出 PDF/Excel 时先创建任务记录（status='pending'），后台处理完成后
更新 status='completed' + file_path。设计文档第 12.6 节。

状态机：pending → processing → completed / failed
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ExportTask(Base):
    __tablename__ = "export_tasks"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=True, index=True)  # null = 全部客户（admin 导出）
    requested_by = Column(String(128), nullable=False)  # admin username 或 client_id
    requested_by_role = Column(String(32), nullable=False)  # 'admin' | 'client'
    export_type = Column(String(16), nullable=False)  # 'pdf' | 'excel'
    date_from = Column(Date, nullable=True)
    date_to = Column(Date, nullable=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    file_path = Column(String(512), nullable=True)
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **步骤 4：编写 Alembic 迁移**

```python
# index-monitor/alembic/versions/005_create_export_tasks.py
"""create export_tasks table

Revision ID: 005
Revises: 004
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=True, index=True),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("requested_by_role", sa.String(32), nullable=False),
        sa.Column("export_type", sa.String(16), nullable=False),
        sa.Column("date_from", sa.Date, nullable=True),
        sa.Column("date_to", sa.Date, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("export_tasks", schema="monitor")
```

- [ ] **步骤 5：运行迁移 + 测试验证通过 + Commit**

```bash
cd index-monitor && alembic upgrade head
pytest tests/unit/test_export_task.py -v
# 预期：PASS

git add index-monitor/app/models/export_task.py \
        index-monitor/alembic/versions/005_create_export_tasks.py \
        index-monitor/tests/unit/test_export_task.py
git commit -m "feat(monitor): add ExportTask model + migration 005

新建 monitor.export_tasks 表跟踪导出任务状态。
设计文档第 12.6 节。"
```

---

## 任务 4：ArchivedDistribution 模型 + 迁移

**文件：**
- 创建：`index-monitor/app/models/archived_distribution.py`
- 创建：`index-monitor/alembic/versions/006_create_archived_distributions.py`
- 测试：`index-monitor/tests/unit/test_archived_distribution.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_archived_distribution.py
"""ArchivedDistribution 模型测试。

GEOFlow 文章删除后，监测系统跨 schema JOIN 查不到，历史检测结果丢失。
本表保留删除时的文章快照。设计文档第 21.4 节。
"""
import pytest
from sqlalchemy import inspect

from app.models.archived_distribution import ArchivedDistribution


def test_archived_distribution_tablename():
    assert ArchivedDistribution.__tablename__ == "archived_distributions"


def test_archived_distribution_schema_is_monitor():
    table_args = ArchivedDistribution.__table_args__
    schema_dict = table_args if isinstance(table_args, dict) else table_args[-1]
    assert schema_dict.get("schema") == "monitor"


def test_archived_distribution_required_columns():
    cols = {c.name for c in ArchivedDistribution.__table__.columns}
    expected = {
        "id", "client_id", "remote_url", "geoflow_article_id",
        "content_title", "content_slug", "content_excerpt", "content_body",
        "content_keywords", "meta_description", "original_keyword", "published_at",
        "archived_at", "archived_reason",
    }
    assert cols == expected, f"缺失：{expected - cols}，多余：{cols - expected}"


@pytest.mark.asyncio
async def test_archived_distribution_table_exists_in_db(db_session):
    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow")
    inspector = inspect(engine)
    assert "archived_distributions" in set(inspector.get_table_names(schema="monitor"))
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_archived_distribution.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.models.archived_distribution'`

- [ ] **步骤 3：编写模型实现代码**

```python
# index-monitor/app/models/archived_distribution.py
"""GEOFlow 文章删除后的归档分发记录。

当 GEOFlow 侧文章被删除（article_distributions.status != 'synced' 或记录消失），
监测系统定时任务将该分发记录的历史数据归档到本表，保留文章内容快照。
设计文档第 21.4 节。

查询时 DistributionQueryService 同时查 GEOFlow 实时表 + 本归档表，
合并结果，归档记录标注 source='archived'。
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ArchivedDistribution(Base):
    __tablename__ = "archived_distributions"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    remote_url = Column(String(512), nullable=False, index=True)
    geoflow_article_id = Column(Integer, nullable=True)
    # 文章快照（删除时的内容副本）
    content_title = Column(String(512), nullable=True)
    content_slug = Column(String(255), nullable=True)
    content_excerpt = Column(Text, nullable=True)
    content_body = Column(Text, nullable=True)
    content_keywords = Column(JSON, nullable=True)
    meta_description = Column(Text, nullable=True)
    original_keyword = Column(String(255), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    # 归档信息
    archived_at = Column(DateTime(timezone=True), server_default=func.now())
    archived_reason = Column(String(64), default="geoflow_deleted")
```

- [ ] **步骤 4：编写 Alembic 迁移**

```python
# index-monitor/alembic/versions/006_create_archived_distributions.py
"""create archived_distributions table

Revision ID: 006
Revises: 005
Create Date: 2026-07-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "archived_distributions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(64), nullable=False, index=True),
        sa.Column("remote_url", sa.String(512), nullable=False, index=True),
        sa.Column("geoflow_article_id", sa.Integer, nullable=True),
        sa.Column("content_title", sa.String(512), nullable=True),
        sa.Column("content_slug", sa.String(255), nullable=True),
        sa.Column("content_excerpt", sa.Text, nullable=True),
        sa.Column("content_body", sa.Text, nullable=True),
        sa.Column("content_keywords", sa.dialects.postgresql.JSON, nullable=True),
        sa.Column("meta_description", sa.Text, nullable=True),
        sa.Column("original_keyword", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("archived_reason", sa.String(64), server_default="geoflow_deleted"),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("archived_distributions", schema="monitor")
```

- [ ] **步骤 5：运行迁移 + 测试验证通过 + Commit**

```bash
cd index-monitor && alembic upgrade head
pytest tests/unit/test_archived_distribution.py -v
# 预期：PASS

git add index-monitor/app/models/archived_distribution.py \
        index-monitor/alembic/versions/006_create_archived_distributions.py \
        index-monitor/tests/unit/test_archived_distribution.py
git commit -m "feat(monitor): add ArchivedDistribution model + migration 006

GEOFlow 文章删除后保留历史快照。设计文档第 21.4 节。"
```

---

## 任务 5：扩展 Client 表（contact_* + agreed_* 字段）

**文件：**
- 修改：`index-monitor/app/models/client.py:9-22`（Client 类）
- 创建：`index-monitor/alembic/versions/007_extend_clients_and_client_sites.py`
- 测试：`index-monitor/tests/unit/test_client_lifecycle_fields.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_client_lifecycle_fields.py
"""Client 表扩展字段测试。

验证目标（设计文档第 6.1 节 + 第 21.6 节）：
1. Client 模型有 contact_name/contact_email/contact_phone 字段
2. Client 模型有 agreed_terms_at/agreed_privacy_at 字段
3. DB 反射表结构与模型一致
4. contact_email 有 UNIQUE 索引
"""
import pytest
from sqlalchemy import inspect

from app.models.client import Client


def test_client_has_contact_fields():
    cols = {c.name for c in Client.__table__.columns}
    assert "contact_name" in cols, "Client 缺 contact_name 字段"
    assert "contact_email" in cols, "Client 缺 contact_email 字段"
    assert "contact_phone" in cols, "Client 缺 contact_phone 字段"


def test_client_has_agreed_fields():
    cols = {c.name for c in Client.__table__.columns}
    assert "agreed_terms_at" in cols, "Client 缺 agreed_terms_at 字段"
    assert "agreed_privacy_at" in cols, "Client 缺 agreed_privacy_at 字段"


def test_client_contact_email_is_unique():
    """contact_email 必须 UNIQUE（设计文档第 6.1 节）。"""
    email_col = Client.__table__.columns["contact_email"]
    assert email_col.unique is True, "contact_email 必须有 UNIQUE 约束"


@pytest.mark.asyncio
async def test_client_extended_columns_in_db(db_session):
    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow")
    inspector = inspect(engine)
    db_cols = {c["name"] for c in inspector.get_columns("clients", schema="monitor")}
    for col in ("contact_name", "contact_email", "contact_phone", "agreed_terms_at", "agreed_privacy_at"):
        assert col in db_cols, f"DB monitor.clients 缺 {col}"
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_client_lifecycle_fields.py -v`
预期：FAIL，`AssertionError: Client 缺 contact_name 字段`

- [ ] **步骤 3：修改 Client 模型**

```python
# index-monitor/app/models/client.py（修改 Client 类，增加字段）
from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), unique=True, nullable=False)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(32))
    company_name = Column(String(255))
    status = Column(String(32), default="active", nullable=False)
    # 设计文档第 6.1 节：客户生命周期联系信息
    contact_name = Column(String(128), nullable=True)
    contact_email = Column(String(255), nullable=True, unique=True)
    contact_phone = Column(String(32), nullable=True)
    # 设计文档第 21.6 节：合规留痕（首次同意用户协议/隐私政策时间）
    agreed_terms_at = Column(DateTime(timezone=True), nullable=True)
    agreed_privacy_at = Column(DateTime(timezone=True), nullable=True)
    # 登录留痕
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClientSite(Base):
    __tablename__ = "client_sites"
    __table_args__ = monitor_table_args(
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),
        UniqueConstraint("domain", name="client_sites_domain_unique_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    site_name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    site_type = Column(String(32), default="official")
    has_wordpress = Column(Boolean, default=False)  # 设计文档第 6.2 节
    wordpress_api_url = Column(String(512))
    wordpress_api_token = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 4：编写 Alembic 迁移（同时扩展 Client + ClientSite）**

```python
# index-monitor/alembic/versions/007_extend_clients_and_client_sites.py
"""extend clients and client_sites tables

Revision ID: 007
Revises: 006
Create Date: 2026-07-25

扩展 monitor.clients：
- contact_name / contact_email（UNIQUE）/ contact_phone（设计文档第 6.1 节）
- agreed_terms_at / agreed_privacy_at（设计文档第 21.6 节合规）
- last_login_at（客户最后登录时间）

扩展 monitor.client_sites：
- has_wordpress 字段（设计文档第 6.2 节）
- domain UNIQUE 约束（client_sites_domain_unique_key）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 扩展 clients 表
    op.add_column("clients", sa.Column("contact_name", sa.String(128), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("contact_email", sa.String(255), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("contact_phone", sa.String(32), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("agreed_terms_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("agreed_privacy_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.add_column("clients", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True), schema="monitor")
    op.create_unique_constraint("clients_contact_email_key", "clients", ["contact_email"], schema="monitor")

    # 扩展 client_sites 表
    op.add_column("client_sites", sa.Column("has_wordpress", sa.Boolean, server_default="false"), schema="monitor")
    op.create_unique_constraint("client_sites_domain_unique_key", "client_sites", ["domain"], schema="monitor")


def downgrade() -> None:
    op.drop_constraint("client_sites_domain_unique_key", "client_sites", schema="monitor")
    op.drop_column("client_sites", "has_wordpress", schema="monitor")

    op.drop_constraint("clients_contact_email_key", "clients", schema="monitor")
    op.drop_column("clients", "last_login_at", schema="monitor")
    op.drop_column("clients", "agreed_privacy_at", schema="monitor")
    op.drop_column("clients", "agreed_terms_at", schema="monitor")
    op.drop_column("clients", "contact_phone", schema="monitor")
    op.drop_column("clients", "contact_email", schema="monitor")
    op.drop_column("clients", "contact_name", schema="monitor")
```

- [ ] **步骤 5：运行迁移 + 测试验证通过 + Commit**

```bash
cd index-monitor && alembic upgrade head
pytest tests/unit/test_client_lifecycle_fields.py -v
# 预期：PASS

# 同时确认现有 test_models.py 仍通过（client_sites 新增约束不应破坏旧测试）
pytest tests/test_models.py -v
# 预期：PASS（如果失败，需检查 test_composite_unique_in_db 是否需要更新）

git add index-monitor/app/models/client.py \
        index-monitor/alembic/versions/007_extend_clients_and_client_sites.py \
        index-monitor/tests/unit/test_client_lifecycle_fields.py
git commit -m "feat(monitor): extend Client + ClientSite fields (migration 007)

Client: contact_name/contact_email(UNIQUE)/contact_phone + agreed_*_at + last_login_at
ClientSite: has_wordpress + domain UNIQUE 约束
设计文档第 6.1/6.2/21.6 节。"
```

---

## 任务 6：ClientSite domain UNIQUE 约束 + has_wordpress 字段

**说明：** 此任务已合并到任务 5 的迁移 007 中（同时扩展两张表避免多个迁移）。
任务 5 已完成 `has_wordpress` 字段 + `client_sites_domain_unique_key` 约束。

**额外测试验证：**

- [ ] **步骤 1：编写 domain UNIQUE 集成测试**

```python
# index-monitor/tests/unit/test_client_site_domain_unique.py
"""ClientSite domain UNIQUE 约束测试。

设计文档第 4.1 节：一个 domain 只属于一个客户。
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.client import ClientSite


def test_client_site_has_wordpress_field():
    cols = {c.name for c in ClientSite.__table__.columns}
    assert "has_wordpress" in cols


def test_client_site_domain_unique_constraint_in_model():
    """模型声明了 domain UNIQUE 约束。"""
    from sqlalchemy import UniqueConstraint
    table_args = ClientSite.__table_args__
    constraints = [a for a in table_args if isinstance(a, UniqueConstraint)] if isinstance(table_args, tuple) else []
    domain_uc = [uc for uc in constraints if "domain" in [c.name for c in uc.columns]]
    assert len(domain_uc) == 1, "期望 domain UNIQUE 约束"
    assert domain_uc[0].name == "client_sites_domain_unique_key"


@pytest.mark.asyncio
async def test_client_site_domain_unique_in_db(db_session):
    """DB 中 domain UNIQUE 约束存在。"""
    from sqlalchemy import create_engine
    engine = create_engine("postgresql+psycopg2://geo_user:geo_password@localhost:5432/geo_flow")
    inspector = inspect(engine)
    uniques = inspector.get_unique_constraints("client_sites", schema="monitor")
    domain_uc = [u for u in uniques if u["column_names"] == ["domain"]]
    assert len(domain_uc) == 1, f"期望 domain 单列 UNIQUE，实际 {uniques}"
    assert domain_uc[0]["name"] == "client_sites_domain_unique_key"
    engine.dispose()
```

- [ ] **步骤 2：运行测试验证通过（迁移 007 已执行）**

运行：`cd index-monitor && pytest tests/unit/test_client_site_domain_unique.py -v`
预期：PASS（任务 5 已执行迁移 007）

- [ ] **步骤 3：Commit**

```bash
git add index-monitor/tests/unit/test_client_site_domain_unique.py
git commit -m "test(monitor): verify ClientSite domain UNIQUE + has_wordpress

补充 domain 单列 UNIQUE 约束的独立测试（迁移 007 已落地）。
设计文档第 4.1 节：一个 domain 只属于一个客户。"
```

---

## 任务 7：鉴权依赖补全 + 密码强度校验

**文件：**
- 修改：`index-monitor/app/api/deps.py`（补 `get_current_super_admin` + `get_current_user`）
- 创建：`index-monitor/app/utils/validators.py`
- 创建：`index-monitor/app/utils/__init__.py`（如不存在）
- 测试：`index-monitor/tests/unit/test_auth_deps.py`
- 测试：`index-monitor/tests/unit/test_validators.py`

**背景：** `app/core/auth.py` 已有 `get_current_admin`（用 `SSO_JWT_SECRET`），`app/api/deps.py` 已有 `get_current_client_id`（用 `SECRET_KEY`）。本任务补全 super_admin 校验 + 统一入口 + 密码强度。

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_validators.py
"""密码强度校验测试。设计文档第 9.4 节。"""
import pytest
from fastapi import HTTPException

from app.utils.validators import validate_password_strength


def test_password_too_short_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("ab1")
    assert exc.value.status_code == 400
    assert "至少 8 位" in exc.value.detail


def test_password_no_letter_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("12345678")
    assert "字母" in exc.value.detail


def test_password_no_digit_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("abcdefgh")
    assert "数字" in exc.value.detail


def test_password_valid_passes():
    # 不抛异常即通过
    validate_password_strength("abc12345")
    validate_password_strength("PassWord2026")


def test_password_exactly_8_chars_passes():
    validate_password_strength("a1b2c3d4")
```

```python
# index-monitor/tests/unit/test_auth_deps.py
"""鉴权依赖测试：get_current_super_admin + get_current_user。

get_current_admin 已在 app/core/auth.py 实现（Plan 1），本任务补 super_admin 校验。
"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _make_admin_token(role: str = "admin") -> str:
    """签发测试用 admin JWT。"""
    payload = {
        "sub": "1",
        "name": "测试管理员",
        "role": role,
        "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")


@pytest.mark.asyncio
async def test_get_current_super_admin_with_super_admin_token():
    from app.api.deps import get_current_super_admin
    from fastapi.security import HTTPAuthorizationCredentials
    token = _make_admin_token(role="super_admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    result = await get_current_super_admin(credentials=creds)
    assert result["role"] == "super_admin"


@pytest.mark.asyncio
async def test_get_current_super_admin_rejects_plain_admin():
    from app.api.deps import get_current_super_admin
    from fastapi.security import HTTPAuthorizationCredentials
    from fastapi import HTTPException
    token = _make_admin_token(role="admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        await get_current_super_admin(credentials=creds)
    assert exc.value.status_code == 403
    assert "超级管理员" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_returns_admin_dict_for_admin_token():
    from app.api.deps import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials
    token = _make_admin_token(role="admin")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user, role = await get_current_user(credentials=creds)
    assert isinstance(user, dict)
    assert role == "admin"


@pytest.mark.asyncio
async def test_get_current_user_returns_client_for_client_token(db_session):
    """client JWT 用 SECRET_KEY 签发，get_current_user 识别 type=client 时查 DB。"""
    from app.api.deps import get_current_user
    from app.core.security import create_access_token
    from app.models.client import Client
    from sqlalchemy import select

    # 先确保有一个 client（用 test 夹具或直接插入）
    token = create_access_token({"sub": "test_client_001", "role": "client", "type": "client"})
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # 如果 DB 没有 test_client_001，get_current_user 应抛 401
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=creds, db=db_session)
    assert exc.value.status_code == 401
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_validators.py tests/unit/test_auth_deps.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.utils.validators'` + `ImportError: cannot import name 'get_current_super_admin'`

- [ ] **步骤 3：编写 validators 实现**

```python
# index-monitor/app/utils/__init__.py
# 空文件，标记 app.utils 为 Python 包
```

```python
# index-monitor/app/utils/validators.py
"""输入校验工具函数。

设计文档第 9.4 节：密码强度校验（至少 8 位，含字母+数字）。
复用于客户创建/修改密码/admin 重置密码。
"""
import re

from fastapi import HTTPException


def validate_password_strength(password: str) -> None:
    """校验密码强度：至少 8 位，包含字母和数字。

    Parameters
    ----------
    password : str
        待校验的明文密码。

    Raises
    ------
    HTTPException
        - 400：密码少于 8 位
        - 400：密码不含字母
        - 400：密码不含数字
    """
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if not re.search(r'[a-zA-Z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含字母")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="密码必须包含数字")
```

- [ ] **步骤 4：修改 deps.py 补全鉴权依赖**

```python
# index-monitor/app/api/deps.py（完整替换）
"""鉴权依赖集合。

职责分工：
- app/core/auth.py：admin JWT 验证（verify_admin_jwt + get_current_admin），用 SSO_JWT_SECRET
- app/api/deps.py（本文件）：super_admin 校验 + 统一入口 get_current_user + client 鉴权

JWT 双轨制：
- admin JWT：SSO 签发，用 SSO_JWT_SECRET，payload type='admin'
- client JWT：客户登录签发，用 SECRET_KEY，payload type='client'
"""
from typing import Any, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.client import Client

# admin 用 HTTPBearer（SSO_JWT_SECRET），client 用 OAuth2PasswordBearer（SECRET_KEY）
# 统一用 HTTPBearer 接收 Bearer token，内部按 type 字段分流
_security = HTTPBearer(auto_error=False)


async def get_current_client_id(token: str = Depends(_security)) -> str:
    """从 client JWT 提取 client_id（向后兼容，旧路由仍可用）。"""
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的 token")
    payload = decode_token(token.credentials)
    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的 token")
    return client_id


async def get_current_super_admin(
    admin: dict = Depends(get_current_admin),
) -> dict[str, Any]:
    """要求 super_admin 角色。admin 已由 get_current_admin 验证。"""
    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return admin


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: AsyncSession = Depends(get_db),
) -> tuple[Union[dict, Client], str]:
    """统一鉴权入口：返回 (user, role)。

    根据 JWT payload 的 type 字段分流：
    - type='admin'：调用 get_current_admin 验证，返回 (admin_dict, role)
    - type='client'（默认）：用 SECRET_KEY 解码，查 monitor.clients 表，返回 (Client 对象, 'client')

    调用方根据 role 判断权限边界。
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing_token")

    token = credentials.credentials

    # 先尝试用 SSO_JWT_SECRET 解码（admin token）
    import jwt
    try:
        payload = jwt.decode(token, settings.SSO_JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") == "admin":
            # admin token：直接调用 verify_admin_jwt 复用完整校验逻辑
            # （包含 type/role/sub 校验 + 过期检查）
            from app.core.auth import verify_admin_jwt
            admin = verify_admin_jwt(token)
            return admin, admin["role"]
    except jwt.InvalidTokenError:
        pass  # 不是 admin token，尝试 client token

    # client token：用 SECRET_KEY 解码
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid_token")

    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=401, detail="invalid_token")

    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    if not client or client.status != "active":
        raise HTTPException(status_code=401, detail="客户账号不存在或已禁用")

    return client, "client"
```

- [ ] **步骤 5：运行测试验证通过 + Commit**

```bash
cd index-monitor && pytest tests/unit/test_validators.py tests/unit/test_auth_deps.py -v
# 预期：PASS

# 确认现有 SSO 测试仍通过
pytest tests/integration/ -v --tb=short
# 预期：PASS

git add index-monitor/app/utils/__init__.py \
        index-monitor/app/utils/validators.py \
        index-monitor/app/api/deps.py \
        index-monitor/tests/unit/test_validators.py \
        index-monitor/tests/unit/test_auth_deps.py
git commit -m "feat(monitor): add super_admin dep + unified get_current_user + password validator

- get_current_super_admin：校验 role=super_admin
- get_current_user：统一入口，按 JWT type 分流 admin/client
- validate_password_strength：至少 8 位 + 字母 + 数字
设计文档第 8 节 + 第 9.4 节。"
```

---

## M1 完成检查清单

执行完所有 7 个任务后，运行以下验证：

- [ ] **全量测试通过**

```bash
cd index-monitor && pytest tests/ -v --tb=short
# 预期：所有测试 PASS（含原有 + M1 新增）
```

- [ ] **Alembic 版本正确**

```bash
cd index-monitor && alembic current
# 预期：007 (extend clients and client_sites tables)
```

- [ ] **DB 表结构完整**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_flow -c \
  "SELECT tablename FROM pg_tables WHERE schemaname='monitor' ORDER BY tablename"
# 预期包含：admin_audit_logs, archived_distributions, article_distributions,
#           citation_results, clients, client_sites, export_tasks,
#           index_history, index_results, manual_distributions, system_config
```

- [ ] **Commit 历史**

```bash
git log --oneline feat/rebrand-dual-domain..HEAD
# 预期：7 个 commit（任务 1-7 各一个）
```

- [ ] **推送到远程**

```bash
git push origin feat/unified-db-and-monitoring
```

---

## M1 验收标准对照

| 验收标准编号 | 内容 | 对应任务 |
|-------------|------|---------|
| 1 | 监测系统连 GEOFlow 的 PG，跨 schema 查询正常 | 前置（Plan 1 已完成）|
| 4 | admin 通过 SSO 登录 | 任务 7（get_current_admin 已存在）|
| 5 | admin 改角色 → 下次 SSO 登录自动生效 | 任务 7（JWT 含 role）|
| 14 | 客户生命周期完整：创建→登录→停用→恢复→软删除 | 任务 5（status 字段已存在 + contact_*）|
| 15 | 客户密码安全校验：强度不足/邮箱重复 → 创建失败 | 任务 5（contact_email UNIQUE）+ 任务 7（validate_password_strength）|
| 42 | DB 权限隔离：monitor_user 对 public 只读，对 monitor 读写 | 前置（Plan 1 已完成）|

---

## 下一步

M1 完成后，进入 [M2：核心查询 + 检测改造 + admin 端点](./2026-07-25-plan2-m2-query-services-admin.md)。
