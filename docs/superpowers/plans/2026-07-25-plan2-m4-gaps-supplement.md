# M4 关键缺口补全 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 闭合 M3 里程碑审查发现的两项关键缺口——(1) export task 触发器（APScheduler 扫 pending）；(2) charts 字段端到端上传（前端 ECharts `getDataURL()` → `ExportRequest` → `ExportTask` → PDF 模板）。附带修复 Dashboard 的 `citation_count` 写死为 0 的 TODO。

**架构：**
- 后端 `ExportTask` 加 `charts` JSONB 列（alembic 008 迁移）；`ExportRequest` 加 `charts` 字段；`ExportService._assemble_data` 从 `task.charts` 读取（替换写死的 `{}`）
- `scheduler.py` 加 `scheduled_export_processor`，每 30 秒扫 pending 导出任务调用 `ExportService.process_task`
- 前端 `Dashboard.vue` 暴露 ECharts 实例引用，提供 `getChartsDataURL()` 方法；admin 可见"导出报告（含图表）"按钮，点击时截图传入 `ExportDialog`；`ExportDialog` 接收可选 `charts` prop，提交时一并上传

**技术栈：** SQLAlchemy 2.0 + alembic + APScheduler + Pydantic + Vue 3 + Element Plus + ECharts

**前置条件：**
- M1 + M2 + M3 已完成（commit `fac321a`）
- M4 主计划已存在（`2026-07-25-plan2-m4-frontend-website-e2e.md`）
- 本计划是 M4 的**前置补全**，必须在 M4 主计划任务 2（Dashboard 改造）/任务 4（Exports 页面）/任务 9（定时任务）之前执行
- 本地 Docker 环境 `geo-postgres-local` + `index-monitor` 容器运行中
- alembic 当前版本 `007`

**关联文档：**
- [M3 里程碑审查结论（progress.md 尾部）](../../../.superpowers/sdd/progress.md)
- [设计文档第 12.4 节 图表渲染](../specs/2026-07-25-geoflow-monitor-db-sync-design.md)
- [M4 主计划](2026-07-25-plan2-m4-frontend-website-e2e.md)

**全局约束（逐字来自 project_memory + M3 审查）：**
- 后端代码改动必须在 Docker 容器内验证（python:3.11-slim，主机 Python 3.14 装不上锁定依赖——M1 Task 2 裁定）
- 前端代码改动必须 `npm run build` 验证
- 所有测试遵循 TDD（先写失败测试 → 运行确认失败 → 实现 → 运行确认通过 → commit）
- 不破坏 M3 既有 18 个测试（4 PDF + 3 Excel + 8 端点 + 3 ExportService）
- `charts` 是 JSONB，存储 base64 数据 URL 字符串（前端 ECharts `getDataURL()` 生成，格式 `data:image/png;base64,...`）
- PDF 图表不跨页切割（`page-break-inside: avoid`，M3 已实现，本计划不改动模板）
- API keys 必须用环境变量，禁止硬编码
- monitor schema 的表用 `monitor_table_args()`

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `index-monitor/app/models/export_task.py` | ExportTask ORM 模型 | 修改：加 `charts` JSONB 列 |
| `index-monitor/alembic/versions/008_add_charts_to_export_tasks.py` | 数据库迁移 | 创建：加 `charts` 列到 `monitor.export_tasks` |
| `index-monitor/app/api/export_routes.py` | 导出端点 | 修改：`ExportRequest` 加 `charts` 字段 + 两个创建端点写入 `task.charts` |
| `index-monitor/app/services/export_service.py` | 导出编排服务 | 修改：`_assemble_data` 从 `task.charts` 读取（替换写死的 `{}`） |
| `index-monitor/app/services/scheduler.py` | 定时任务调度 | 修改：加 `scheduled_export_processor` + `start_scheduler` 注册 |
| `index-monitor/tests/unit/test_export_service.py` | ExportService 单元测试 | 修改：加 charts 字段测试（2 个） |
| `index-monitor/tests/unit/test_scheduler.py` | scheduler 单元测试 | 创建：加 export_processor 注册测试（1 个） |
| `index-monitor/tests/integration/test_export_charts_flow.py` | charts 端到端集成测试 | 创建：验证端点写入 + _assemble_data 读取（1 个） |
| `dashboard/src/views/Dashboard.vue` | 数据总览页 | 修改：暴露 ECharts 实例 + `getChartsDataURL()` + 修复 `citation_count` + 加导出按钮 |
| `dashboard/src/components/ExportDialog.vue` | 导出对话框 | 修改：接收 `charts` prop + 提交时上传 |
| `dashboard/src/views/Exports.vue` | 导出报告页 | 修改：从 Dashboard 触发时传 charts（兼容无 charts 场景） |

---

## 任务 1：ExportTask 加 charts 列 + alembic 008 迁移

**文件：**
- 修改：`index-monitor/app/models/export_task.py`
- 创建：`index-monitor/alembic/versions/008_add_charts_to_export_tasks.py`
- 测试：`index-monitor/tests/unit/test_export_task_charts.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_export_task_charts.py
"""ExportTask 模型 charts 列测试。

验证：
1. ExportTask 有 charts 列（JSONB）
2. charts 列可读写 base64 数据 URL 字典
3. charts 列默认为 NULL（向后兼容 M3 既有任务）

设计文档第 12.4 节：图表用 base64 内联。
"""
import pytest
from sqlalchemy import select

from app.models.export_task import ExportTask


@pytest.mark.asyncio
async def test_export_task_has_charts_column(db_session):
    """ExportTask 模型有 charts 列。"""
    # 通过 ORM 写入带 charts 的任务
    task = ExportTask(
        requested_by="test_admin",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
        charts={
            "trend": "data:image/png;base64,iVBORw0KGgo=",
            "pie": "data:image/png;base64,iVBORw0KGgo=",
        },
    )
    db_session.add(task)
    await db_session.commit()

    # 读回验证
    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task.id)
    )
    fetched = result.scalar_one()
    assert fetched.charts is not None
    assert fetched.charts["trend"] == "data:image/png;base64,iVBORw0KGgo="
    assert fetched.charts["pie"] == "data:image/png;base64,iVBORw0KGgo="


@pytest.mark.asyncio
async def test_export_task_charts_nullable(db_session):
    """charts 列可为 NULL（向后兼容 M3 既有任务）。"""
    task = ExportTask(
        requested_by="test_admin",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
        # 不设 charts
    )
    db_session.add(task)
    await db_session.commit()

    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task.id)
    )
    fetched = result.scalar_one()
    assert fetched.charts is None
```

- [ ] **步骤 2：运行测试验证失败**

运行（在 Docker 容器内）：

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_task_charts.py -v
```

预期：FAIL，报错 `AttributeError: 'ExportTask' object has no attribute 'charts'` 或 `psycopg.errors.UndefinedColumn: column "charts" does not exist`

- [ ] **步骤 3：修改 ExportTask 模型加 charts 列**

```python
# index-monitor/app/models/export_task.py（修改）
"""导出任务记录。

异步导出 PDF/Excel 时先创建任务记录（status='pending'），后台处理完成后
更新 status='completed' + file_path。设计文档第 12.6 节。

状态机：pending → processing → completed / failed

charts 字段（M4 补全）：JSONB，存储前端 ECharts getDataURL() 生成的
base64 数据 URL 字典，如 {"trend": "data:image/png;base64,...", "pie": "..."}。
设计文档第 12.4 节：图表用 base64 内联。
"""
from sqlalchemy import Column, String, DateTime, Text, Integer, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    charts = Column(JSONB, nullable=True)  # 图表 base64 数据 URL 字典（M4 补全）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **步骤 4：创建 alembic 008 迁移**

```python
# index-monitor/alembic/versions/008_add_charts_to_export_tasks.py
"""add charts column to export_tasks

Revision ID: 008
Revises: 007
Create Date: 2026-07-25

M4 补全：ExportTask 加 charts JSONB 列，存储前端 ECharts getDataURL()
生成的 base64 数据 URL 字典。设计文档第 12.4 节。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "export_tasks",
        sa.Column("charts", JSONB, nullable=True),
        schema="monitor",
    )


def downgrade():
    op.drop_column("export_tasks", "charts", schema="monitor")
```

- [ ] **步骤 5：在 Docker 容器内运行迁移**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  alembic upgrade head
# 预期输出：Running upgrade 007 -> 008, add charts column to export_tasks

docker compose -f docker-compose.local.yml exec index-monitor \
  alembic current
# 预期输出：008 (head)
```

- [ ] **步骤 6：运行测试验证通过**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_task_charts.py -v
```

预期：2 passed

- [ ] **步骤 7：回归 M3 既有测试**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_service.py tests/unit/test_pdf_export.py \
         tests/unit/test_excel_export.py tests/integration/test_export_routes.py -v
```

预期：M3 既有 18 个测试全部 PASS（0 回归）

- [ ] **步骤 8：Commit**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add index-monitor/app/models/export_task.py \
        index-monitor/alembic/versions/008_add_charts_to_export_tasks.py \
        index-monitor/tests/unit/test_export_task_charts.py
git commit -m "feat(monitor): add charts JSONB column to ExportTask

- ExportTask.charts：存储前端 ECharts getDataURL() 生成的 base64 字典
- alembic 008 迁移：monitor.export_tasks 加 charts 列（nullable，向后兼容）
- 闭合 M3 审查缺口 2 的后端模型层
设计文档第 12.4 节。"
```

---

## 任务 2：ExportRequest 加 charts 字段 + ExportService 读取

**文件：**
- 修改：`index-monitor/app/api/export_routes.py`
- 修改：`index-monitor/app/services/export_service.py`
- 测试：`index-monitor/tests/unit/test_export_service.py`（追加）
- 创建：`index-monitor/tests/integration/test_export_charts_flow.py`

- [ ] **步骤 1：编写失败的测试（ExportService._assemble_data 读取 charts）**

追加到 `index-monitor/tests/unit/test_export_service.py`：

```python
# 追加到 index-monitor/tests/unit/test_export_service.py 末尾

@pytest.mark.asyncio
async def test_assemble_data_reads_charts_from_task(db_session, ensure_geoflow_tables):
    """_assemble_data 从 task.charts 读取 charts 字段（而非写死 {}）。

    闭合 M3 审查缺口 2：ExportService._assemble_data 写死 "charts": {}。
    """
    from app.services.export_service import ExportService
    from app.models.export_task import ExportTask

    task = ExportTask(
        requested_by="test_admin",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
        charts={
            "trend": "data:image/png;base64,AAA",
            "pie": "data:image/png;base64,BBB",
        },
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session)
    data = await service._assemble_data(task)

    assert data["charts"] == {
        "trend": "data:image/png;base64,AAA",
        "pie": "data:image/png;base64,BBB",
    }


@pytest.mark.asyncio
async def test_assemble_data_charts_empty_when_task_charts_none(db_session, ensure_geoflow_tables):
    """task.charts 为 NULL 时，_assemble_data 返回空字典（向后兼容）。"""
    from app.services.export_service import ExportService
    from app.models.export_task import ExportTask

    task = ExportTask(
        requested_by="test_admin",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
        # charts=None
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session)
    data = await service._assemble_data(task)

    assert data["charts"] == {}
```

- [ ] **步骤 2：编写失败的集成测试（端点写入 charts）**

```python
# index-monitor/tests/integration/test_export_charts_flow.py
"""charts 字段端到端集成测试：端点 → ExportTask → _assemble_data。

验证 M3 审查缺口 2 的完整数据流：
1. POST /api/v1/admin/exports 接受 charts 字段
2. ExportTask.charts 持久化
3. ExportService._assemble_data 读取 task.charts
"""
import pytest
from sqlalchemy import select

from app.models.export_task import ExportTask


def _admin_headers():
    """生成 admin JWT headers（与 test_export_routes.py 一致）。"""
    from app.core.security import create_access_token
    token = create_access_token(
        {"sub": "test_super_admin", "role": "super_admin", "name": "Test Admin", "user_id": "u1"}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_create_export_persists_charts(client, db_session):
    """POST /api/v1/admin/exports 接受 charts 字段并持久化到 ExportTask.charts。"""
    charts_payload = {
        "trend": "data:image/png;base64,iVBORw0KGgo=",
        "pie": "data:image/png;base64,iVBORw0KGgo=",
    }
    resp = await client.post(
        "/api/v1/admin/exports",
        json={
            "export_type": "pdf",
            "charts": charts_payload,
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # 验证 DB 中 charts 字段
    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task_id)
    )
    task = result.scalar_one()
    assert task.charts == charts_payload


@pytest.mark.asyncio
async def test_admin_create_export_without_charts_still_works(client, db_session):
    """不传 charts 字段时，端点正常工作（向后兼容 M3 既有调用方）。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "pdf"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    result = await db_session.execute(
        select(ExportTask).where(ExportTask.id == task_id)
    )
    task = result.scalar_one()
    assert task.charts is None
```

- [ ] **步骤 3：运行测试验证失败**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_service.py::test_assemble_data_reads_charts_from_task \
         tests/unit/test_export_service.py::test_assemble_data_charts_empty_when_task_charts_none \
         tests/integration/test_export_charts_flow.py -v
```

预期：
- `test_assemble_data_reads_charts_from_task` FAIL（`data["charts"] == {}` 而非传入的字典）
- `test_assemble_data_charts_empty_when_task_charts_none` PASS（当前写死 `{}` 恰好匹配）
- `test_admin_create_export_persists_charts` FAIL（`task.charts is None`，端点未写入）
- `test_admin_create_export_without_charts_still_works` PASS

- [ ] **步骤 4：修改 ExportRequest 加 charts 字段 + 端点写入**

修改 `index-monitor/app/api/export_routes.py` 的 `ExportRequest` 类和两个创建端点：

```python
# 修改 ExportRequest 类（替换第 43-49 行）
class ExportRequest(BaseModel):
    export_type: str  # 'pdf' | 'excel'
    client_id: Optional[str] = None
    # 用 date 而非 str：Pydantic 自动解析 ISO 字符串（"2026-07-01"）为 date 对象，
    # 直接传给 ExportTask.date_from（Date 列），asyncpg 原生支持 date 类型。
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    # charts：前端 ECharts getDataURL() 生成的 base64 数据 URL 字典。
    # 格式 {"trend": "data:image/png;base64,...", "pie": "..."}。
    # 设计文档第 12.4 节。None = 不带图表（向后兼容）。
    charts: Optional[dict] = None
```

修改 `admin_create_export` 端点（在 ExportTask 构造时加 `charts=req.charts`）：

```python
# 修改 admin_create_export 中的 ExportTask 构造（替换第 66-74 行）
    task = ExportTask(
        client_id=req.client_id,
        requested_by=admin["name"],
        requested_by_role="admin",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        charts=req.charts,
        status="pending",
    )
```

修改 `client_create_export` 端点（同样加 `charts=req.charts`）：

```python
# 修改 client_create_export 中的 ExportTask 构造（替换第 105-113 行）
    task = ExportTask(
        client_id=user.client_id,
        requested_by=user.client_id,
        requested_by_role="client",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        charts=req.charts,
        status="pending",
    )
```

- [ ] **步骤 5：修改 ExportService._assemble_data 从 task.charts 读取**

修改 `index-monitor/app/services/export_service.py` 的 `_assemble_data` 返回值（替换第 149 行）：

```python
# 替换第 140-150 行的 return 语句
        return {
            "client_name": task.client_id or "全部客户",
            "date_from": task.date_from.isoformat() if task.date_from else "",
            "date_to": task.date_to.isoformat() if task.date_to else "",
            "distributions": distributions,
            "index_results": index_results,
            "citation_results": citation_results,
            "summary": summary,
            "stats": summary,  # PDF 模板用 stats 字段
            "charts": task.charts or {},  # 从 task.charts 读取（M4 补全，替换写死的 {}）
        }
```

- [ ] **步骤 6：运行测试验证通过**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_service.py::test_assemble_data_reads_charts_from_task \
         tests/unit/test_export_service.py::test_assemble_data_charts_empty_when_task_charts_none \
         tests/integration/test_export_charts_flow.py -v
```

预期：4 passed

- [ ] **步骤 7：回归 M3 既有测试**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_service.py tests/unit/test_pdf_export.py \
         tests/unit/test_excel_export.py tests/integration/test_export_routes.py -v
```

预期：M3 既有 18 个测试 + 新增 4 个 = 22 passed（0 回归）

- [ ] **步骤 8：Commit**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add index-monitor/app/api/export_routes.py \
        index-monitor/app/services/export_service.py \
        index-monitor/tests/unit/test_export_service.py \
        index-monitor/tests/integration/test_export_charts_flow.py
git commit -m "feat(monitor): wire charts field through ExportRequest → ExportTask → ExportService

- ExportRequest 加 charts 字段（Optional[dict]）
- admin/client 创建端点写入 task.charts
- ExportService._assemble_data 从 task.charts 读取（替换写死的 {}）
- 闭合 M3 审查缺口 2 的后端数据流
设计文档第 12.4 节。"
```

---

## 任务 3：APScheduler 扫 pending export task

**文件：**
- 修改：`index-monitor/app/services/scheduler.py`
- 创建：`index-monitor/tests/unit/test_scheduler.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_scheduler.py
"""scheduler 定时任务测试。

验证 M3 审查缺口 1 的触发器：start_scheduler 注册 export_processor 任务。
不直接调用 scheduled_export_processor（依赖 async_session 上下文，集成测试覆盖）。
"""
from app.services.scheduler import start_scheduler, scheduler


def test_start_scheduler_registers_export_processor():
    """start_scheduler 注册了 export_processor 定时任务（每 30 秒扫 pending）。"""
    # 清空已有任务（避免重复注册抛错）
    scheduler.remove_all_jobs()

    start_scheduler()

    job_ids = [job.id for job in scheduler.get_jobs()]
    assert "index_check" in job_ids, "收录检测定时任务未注册"
    assert "export_processor" in job_ids, "导出处理定时任务未注册"

    # 验证 export_processor 的触发器是 IntervalTrigger（每 30 秒）
    export_job = scheduler.get_job("export_processor")
    assert export_job is not None
    assert export_job.trigger.__class__.__name__ == "IntervalTrigger"
    assert export_job.trigger.interval.total_seconds() == 30


def test_start_scheduler_registers_index_check():
    """start_scheduler 仍注册 index_check 任务（每日 02:00，向后兼容）。"""
    scheduler.remove_all_jobs()
    start_scheduler()

    index_job = scheduler.get_job("index_check")
    assert index_job is not None
    assert index_job.trigger.__class__.__name__ == "CronTrigger"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_scheduler.py -v
```

预期：`test_start_scheduler_registers_export_processor` FAIL（`export_processor` not in job_ids）

- [ ] **步骤 3：修改 scheduler.py 加 scheduled_export_processor**

完整替换 `index-monitor/app/services/scheduler.py`：

```python
# index-monitor/app/services/scheduler.py
"""定时任务调度。

收录检测：每日 02:00（M1 Task 4 已有）
导出处理：每 30 秒扫 pending 导出任务（M4 补全，闭合 M3 审查缺口 1）

设计文档第 21.1 节 + M3 里程碑审查结论。
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.database import async_session
from app.services.index_checker import IndexChecker
from app.services.export_service import ExportService
from app.models.export_task import ExportTask

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scheduled_index_check():
    """每日 02:00 收录检测。"""
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()


async def scheduled_export_processor():
    """每 30 秒扫描 pending 导出任务并处理。

    闭合 M3 审查缺口 1：端点→ExportService 调用链断裂。
    端点只创建 pending 任务返回 202，实际处理由本调度器触发。

    单次最多处理 5 条（防止单轮过载），单条失败不影响其他任务。
    """
    async with async_session() as db:
        # 查 pending 任务（按创建时间升序，限 5 条）
        result = await db.execute(
            select(ExportTask)
            .where(ExportTask.status == "pending")
            .order_by(ExportTask.created_at.asc())
            .limit(5)
        )
        tasks = result.scalars().all()

        if not tasks:
            return

        service = ExportService(db)
        for task in tasks:
            try:
                await service.process_task(str(task.id))
            except Exception:
                # 单条失败不阻塞其他任务；ExportService.process_task 内部
                # 已记录 error_message + status=failed，此处仅兜底
                logger.exception(f"导出任务 {task.id} 处理失败")


def start_scheduler():
    # 收录检测：每日 02:00
    scheduler.add_job(
        scheduled_index_check,
        CronTrigger(hour=2, minute=0),
        id="index_check",
        replace_existing=True,
    )
    # 导出处理：每 30 秒扫 pending（M4 补全）
    scheduler.add_job(
        scheduled_export_processor,
        IntervalTrigger(seconds=30),
        id="export_processor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "APScheduler 已启动：收录检测(每日 02:00) + 导出处理(每 30 秒)"
    )


def stop_scheduler():
    # wait=True：等待当前正在执行的任务完成后再关闭，避免定时任务被强制中断
    scheduler.shutdown(wait=True)
```

- [ ] **步骤 4：运行测试验证通过**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_scheduler.py -v
```

预期：2 passed

- [ ] **步骤 5：容器内启动验证**

```bash
# 重启 index-monitor 容器使 scheduler 生效
docker compose -f docker-compose.local.yml restart index-monitor

# 等待 5 秒后查看日志
sleep 5
docker compose -f docker-compose.local.yml logs --tail 20 index-monitor | grep -i scheduler
# 预期：包含 "APScheduler 已启动：收录检测(每日 02:00) + 导出处理(每 30 秒)"
```

- [ ] **步骤 6：回归测试**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/ -v --tb=short -q
```

预期：全部 PASS（0 回归）

- [ ] **步骤 7：Commit**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add index-monitor/app/services/scheduler.py \
        index-monitor/tests/unit/test_scheduler.py
git commit -m "feat(monitor): add scheduled_export_processor to scan pending export tasks

- scheduler.py 加 scheduled_export_processor（每 30 秒扫 pending）
- 单次最多 5 条，单条失败不阻塞其他
- 闭合 M3 审查缺口 1：端点→ExportService 调用链断裂
设计文档第 21.1 节。"
```

---

## 任务 4：前端 Dashboard 暴露 ECharts getDataURL + 修复 citation_count + 加导出按钮

**文件：**
- 修改：`dashboard/src/views/Dashboard.vue`

**说明：** 本任务基于 M4 主计划任务 2 的 Dashboard.vue 代码（行 401-588）。M4 主计划任务 2 创建初始 Dashboard.vue，本任务在其基础上做三处增强：
1. 暴露 ECharts 实例到 `chartInstances` 对象（用于 `getDataURL`）
2. 修复 `fetchStats` 中 `citation_count: 0` 的 TODO（调用 `/stats/citation`）
3. 加 admin 可见的"导出报告（含图表）"按钮，点击时截图传入 ExportDialog

如果 M4 主计划任务 2 尚未执行，本任务应**合并到 M4 主计划任务 2 一起实现**（即在创建 Dashboard.vue 时直接包含这些增强）。如果 M4 主计划任务 2 已执行，则本任务在其基础上修改。

- [ ] **步骤 1：编写 Dashboard.vue 增强版（含 ECharts 实例引用 + citation_count 修复 + 导出按钮）**

```vue
<!-- dashboard/src/views/Dashboard.vue -->
<template>
  <div class="dashboard-container">
    <!-- 4 统计卡片 -->
    <div class="stats-row">
      <StatCard :value="stats.total_distributions" label="分发总数" icon="Document" color="blue" />
      <StatCard :value="stats.indexed_count" label="已收录" icon="CircleCheck" color="green" />
      <StatCard :value="stats.citation_count" label="AI 采信" icon="ChatDotRound" color="orange" />
      <StatCard :value="indexRate + '%'" label="平均收录率" icon="TrendCharts" color="purple" />
    </div>

    <!-- 操作栏（admin 可见导出按钮，含图表截图） -->
    <div class="action-bar" v-if="isAdmin">
      <el-button type="primary" @click="openExportDialog" :disabled="!chartsReady">
        <el-icon><Download /></el-icon> 导出报告（含图表）
      </el-button>
      <span v-if="!chartsReady" class="hint">图表渲染中…</span>
    </div>

    <!-- 5 图表 -->
    <div class="charts-grid">
      <div class="chart-card large">
        <h3>多引擎收录趋势</h3>
        <div ref="trendChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>AI 采信分布</h3>
        <div ref="pieChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>引擎收录对比</h3>
        <div ref="barChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>来源分布</h3>
        <div ref="ringChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>活动统计</h3>
        <div ref="activityChartRef" class="chart-body"></div>
      </div>
    </div>

    <!-- 导出对话框（接收 charts 截图） -->
    <ExportDialog v-model="showExportDialog" :charts="chartsData" @created="onExportCreated" />
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import ExportDialog from '@/components/ExportDialog.vue'
import { api } from '@/api'

const stats = ref({ total_distributions: 0, indexed_count: 0, citation_count: 0, avg_index_rate: 0 })
const indexRate = computed(() => (stats.value.avg_index_rate * 100).toFixed(1))
const isAdmin = computed(() => localStorage.getItem('role') === 'admin')

// ECharts 实例引用（用于 getDataURL 截图导出）
const chartInstances = {}
const chartsReady = ref(false)

// 导出对话框状态
const showExportDialog = ref(false)
const chartsData = ref({})

const trendChartRef = ref(null)
const pieChartRef = ref(null)
const barChartRef = ref(null)
const ringChartRef = ref(null)
const activityChartRef = ref(null)

onMounted(async () => {
  await fetchStats()
  await nextTick()
  initCharts()
  chartsReady.value = true
})

async function fetchStats() {
  try {
    const resp = await api.get('/admin/distributions')
    const items = resp.data.items || []
    const indexed = items.filter(i => Object.values(i.index_status || {}).some(s => s === 'indexed')).length

    // 修复 citation_count TODO（M4 补全）：调用 /stats/citation 获取采信数
    // 端点不存在或失败时降级为 0，不阻塞 Dashboard 渲染
    let citationCount = 0
    try {
      const citationResp = await api.get('/stats/citation')
      // /stats/citation 返回结构兼容：优先 total，其次 citation_count
      citationCount = citationResp.data?.total ?? citationResp.data?.citation_count ?? 0
    } catch {
      // 端点不存在或失败时降级为 0
      citationCount = 0
    }

    stats.value = {
      total_distributions: items.length,
      indexed_count: indexed,
      citation_count: citationCount,
      avg_index_rate: items.length > 0 ? indexed / items.length : 0,
    }
  } catch (err) {
    console.error('获取统计失败', err)
  }
}

function initCharts() {
  // 趋势图
  if (trendChartRef.value) {
    const chart = echarts.init(trendChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['百度', '头条', '搜狗', '360', '必应'] },
      xAxis: { type: 'category', data: ['7/19', '7/20', '7/21', '7/22', '7/23', '7/24', '7/25'] },
      yAxis: { type: 'value' },
      series: [
        { name: '百度', type: 'line', data: [5, 8, 12, 15, 18, 22, 25], smooth: true },
        { name: '头条', type: 'line', data: [3, 5, 7, 9, 11, 13, 15], smooth: true },
        { name: '搜狗', type: 'line', data: [2, 3, 4, 5, 6, 7, 8], smooth: true },
        { name: '360', type: 'line', data: [1, 2, 3, 4, 5, 6, 7], smooth: true },
        { name: '必应', type: 'line', data: [4, 6, 8, 10, 12, 14, 16], smooth: true },
      ],
    })
    chartInstances.trend = chart
  }

  // 饼图：AI 采信分布
  if (pieChartRef.value) {
    const chart = echarts.init(pieChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        radius: '60%',
        data: [
          { value: 35, name: '千问' },
          { value: 25, name: '豆包' },
          { value: 20, name: 'DeepSeek' },
          { value: 15, name: '文心' },
          { value: 5, name: '未命中' },
        ],
      }],
    })
    chartInstances.pie = chart
  }

  // 柱状图：引擎收录对比
  if (barChartRef.value) {
    const chart = echarts.init(barChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['百度', '头条', '搜狗', '360', '必应'] },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: [25, 15, 8, 7, 16], itemStyle: { color: '#3498db' } }],
    })
    chartInstances.bar = chart
  }

  // 环形图：来源分布
  if (ringChartRef.value) {
    const chart = echarts.init(ringChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        data: [
          { value: 40, name: 'GEOFlow 推送' },
          { value: 10, name: '手动录入' },
        ],
      }],
    })
    chartInstances.ring = chart
  }

  // 活动统计
  if (activityChartRef.value) {
    const chart = echarts.init(activityChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'] },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: [12, 18, 15, 22, 28, 8, 5], itemStyle: { color: '#9c27b0' } }],
    })
    chartInstances.activity = chart
  }
}

/**
 * 获取 PDF 导出所需的图表截图（base64 数据 URL）。
 * 只截 trend（趋势图）和 pie（AI 采信分布），与 report.html 模板的 charts.trend/charts.pie 占位一一对应。
 */
function getChartsDataURL() {
  const result = {}
  const opts = { type: 'png', pixelRatio: 2, backgroundColor: '#fff' }
  if (chartInstances.trend) {
    result.trend = chartInstances.trend.getDataURL(opts)
  }
  if (chartInstances.pie) {
    result.pie = chartInstances.pie.getDataURL(opts)
  }
  return result
}

function openExportDialog() {
  chartsData.value = getChartsDataURL()
  showExportDialog.value = true
}

function onExportCreated(taskId) {
  ElMessage.success(`导出任务已创建：${taskId}，预计 30 秒内完成`)
}
</script>

<style scoped>
.dashboard-container { padding: 20px; }
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}
.action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.action-bar .hint {
  color: #999;
  font-size: 13px;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.chart-card {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.chart-card.large { grid-column: span 3; }
.chart-card h3 { margin: 0 0 15px 0; color: #2c3e50; }
.chart-body { height: 300px; }

/* 响应式 */
@media (max-width: 1199px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .charts-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-card.large { grid-column: span 2; }
}
@media (max-width: 768px) {
  .stats-row { grid-template-columns: 1fr; }
  .charts-grid { grid-template-columns: 1fr; }
  .chart-card.large { grid-column: span 1; }
}
</style>
```

- [ ] **步骤 2：本地构建验证**

```bash
cd dashboard && npm run build
# 预期：构建成功，无报错
```

- [ ] **步骤 3：本地 dev 验证**

```bash
cd dashboard && npm run dev
# 浏览器访问 http://localhost:5173/login，admin 登录后：
# 1. 4 个统计卡片显示（蓝/绿/橙/紫）
# 2. AI 采信卡片数值来自 /stats/citation（非写死 0）
# 3. 5 个图表渲染
# 4. admin 可见"导出报告（含图表）"按钮
# 5. 图表渲染中按钮 disabled，渲染完 enabled
# 6. 点击按钮弹出 ExportDialog
```

- [ ] **步骤 4：Commit**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add dashboard/src/views/Dashboard.vue
git commit -m "feat(dashboard): expose ECharts getDataURL + fix citation_count + add export button

- 暴露 ECharts 实例到 chartInstances，提供 getChartsDataURL()
- 修复 citation_count：调用 /stats/citation 获取（失败降级 0）
- admin 可见导出按钮，点击截图传入 ExportDialog
- 闭合 M3 审查缺口 2 的前端数据源
设计文档第 12.4 节 + 第 13.2 节。"
```

---

## 任务 5：前端 ExportDialog 接收 charts + Exports 页面适配

**文件：**
- 修改：`dashboard/src/components/ExportDialog.vue`
- 修改：`dashboard/src/views/Exports.vue`

**说明：** 本任务基于 M4 主计划任务 4 的 ExportDialog.vue 和 Exports.vue 代码。M4 主计划任务 4 创建初始版本，本任务在其基础上增强：
1. `ExportDialog` 接收可选 `charts` prop，提交时一并上传
2. `Exports` 页面的 dialog 不传 charts（用于历史数据导出，无图表截图）
3. 从 Dashboard 触发的导出带 charts（通过 Dashboard 内嵌的 ExportDialog）

- [ ] **步骤 1：编写 ExportDialog 增强版（接收 charts prop）**

```vue
<!-- dashboard/src/components/ExportDialog.vue -->
<template>
  <el-dialog v-model="visible" title="导出报告" width="450px">
    <el-form :model="form" label-width="100px">
      <el-form-item label="导出格式">
        <el-radio-group v-model="form.export_type">
          <el-radio label="pdf">PDF 报告</el-radio>
          <el-radio label="excel">Excel 明细</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="时间范围">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
      </el-form-item>
      <el-form-item v-if="hasCharts && form.export_type === 'pdf'">
        <el-alert
          title="本次导出将包含当前图表截图（趋势图 + AI 采信分布）"
          type="info"
          :closable="false"
          show-icon
        />
      </el-form-item>
      <el-form-item v-if="!hasCharts && form.export_type === 'pdf'">
        <el-alert
          title="本次导出不含图表截图（从导出报告页触发）。如需含图表，请从数据总览页导出。"
          type="warning"
          :closable="false"
          show-icon
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="submit" :loading="loading">开始导出</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const props = defineProps({
  modelValue: Boolean,
  // charts：可选，前端 ECharts getDataURL() 生成的 base64 字典。
  // 从 Dashboard 触发时传入，从 Exports 页面触发时不传（undefined）。
  charts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'created'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const dateRange = ref([])
const form = reactive({ export_type: 'pdf' })

// 是否携带图表截图（charts 非空对象）
const hasCharts = computed(() => props.charts && Object.keys(props.charts).length > 0)

async function submit() {
  loading.value = true
  try {
    const endpoint = localStorage.getItem('role') === 'admin' ? '/admin/exports' : '/exports'
    const payload = {
      export_type: form.export_type,
      date_from: dateRange.value?.[0] || null,
      date_to: dateRange.value?.[1] || null,
    }
    // 仅 PDF 且有图表时上传 charts（Excel 不需要图表，减小 payload）
    if (form.export_type === 'pdf' && hasCharts.value) {
      payload.charts = props.charts
    }
    const resp = await api.post(endpoint, payload)
    ElMessage.success(`导出任务已创建：${resp.data.task_id}`)
    visible.value = false
    emit('created', resp.data.task_id)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '导出失败')
  } finally {
    loading.value = false
  }
}
</script>
```

- [ ] **步骤 2：修改 Exports.vue 的 dialog 调用（不传 charts）**

修改 `dashboard/src/views/Exports.vue` 中 `<ExportDialog>` 的调用（替换第 953 行附近）：

```vue
<!-- 替换 Exports.vue 中的 ExportDialog 调用 -->
<!-- 原：<ExportDialog v-model="showDialog" @created="fetchTasks" /> -->
<!-- 改：不传 charts（从 Exports 页面触发的导出不含图表截图） -->
<ExportDialog v-model="showDialog" :charts="{}" @created="fetchTasks" />
```

- [ ] **步骤 3：本地构建验证**

```bash
cd dashboard && npm run build
# 预期：构建成功，无报错
```

- [ ] **步骤 4：本地 dev 验证**

```bash
cd dashboard && npm run dev
# 验证场景 1：从数据总览页点击"导出报告（含图表）"
#   - 弹出 ExportDialog，显示蓝色提示"本次导出将包含当前图表截图"
#   - 提交后 payload 含 charts 字段
# 验证场景 2：从导出报告页点击"新建导出"
#   - 弹出 ExportDialog，显示橙色提示"本次导出不含图表截图"
#   - 提交后 payload 不含 charts 字段
# 验证场景 3：切换为 Excel 格式
#   - 不显示图表提示（Excel 不需要图表）
```

- [ ] **步骤 5：端到端验证（含后端调度器）**

```bash
# 1. 确保 Docker 容器运行
docker compose -f docker-compose.local.yml ps
# 预期：postgres + redis + index-monitor 三容器 running/healthy

# 2. 浏览器访问 Dashboard，admin 登录，点击"导出报告（含图表）"
# 3. 提交后 30 秒内，scheduler 应处理 pending 任务
# 4. 刷新导出报告页，任务状态应从 pending → processing → completed
# 5. 下载 PDF，验证包含趋势图和 AI 采信分布图（非空白）

# 或用 curl 验证调度器：
docker compose -f docker-compose.local.yml exec index-monitor \
  python -c "
import asyncio
from app.services.scheduler import scheduled_export_processor
asyncio.run(scheduled_export_processor())
print('export processor executed')
"
```

- [ ] **步骤 6：Commit**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add dashboard/src/components/ExportDialog.vue \
        dashboard/src/views/Exports.vue
git commit -m "feat(dashboard): ExportDialog accepts charts prop + Exports page adaptation

- ExportDialog 接收可选 charts prop，PDF 且有图表时上传
- 显示图表提示信息（蓝色含图表 / 橙色不含图表）
- Exports 页面不传 charts（历史数据导出）
- Dashboard 触发的导出带 charts（任务 4 已实现）
- 闭合 M3 审查缺口 2 的前端数据流
设计文档第 12.4 节 + 第 13.4 节。"
```

---

## 补全完成检查清单

- [ ] **后端 charts 字段端到端打通**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_export_task_charts.py \
         tests/unit/test_export_service.py \
         tests/integration/test_export_charts_flow.py -v
# 预期：全部 PASS
```

- [ ] **调度器触发器就位**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/unit/test_scheduler.py -v
# 预期：2 passed

docker compose -f docker-compose.local.yml logs --tail 30 index-monitor | grep "APScheduler"
# 预期：包含"导出处理(每 30 秒)"
```

- [ ] **前端构建成功**

```bash
cd dashboard && npm run build
# 预期：dist/ 目录生成，无报错
```

- [ ] **M3 既有测试 0 回归**

```bash
docker compose -f docker-compose.local.yml exec index-monitor \
  pytest tests/ -v --tb=short -q
# 预期：M3 既有 18 + 新增 5 = 23 passed（0 回归）
```

- [ ] **端到端冒烟**

```bash
# 创建 pending 任务 → 等待 30 秒 → 验证状态变为 completed
docker compose -f docker-compose.local.yml exec index-monitor \
  python -c "
import asyncio
from sqlalchemy import select
from app.core.database import async_session
from app.models.export_task import ExportTask
from datetime import datetime, timezone

async def main():
    async with async_session() as db:
        task = ExportTask(
            requested_by='smoke_test',
            requested_by_role='admin',
            export_type='pdf',
            status='pending',
            charts={'trend': 'data:image/png;base64,iVBORw0KGgo=', 'pie': 'data:image/png;base64,iVBORw0KGgo='},
        )
        db.add(task)
        await db.commit()
        print(f'Created task: {task.id}')

asyncio.run(main())
"

# 等待 35 秒（scheduler 30 秒间隔 + 5 秒处理时间）
sleep 35

# 检查任务状态
docker compose -f docker-compose.local.yml exec index-monitor \
  python -c "
import asyncio
from sqlalchemy import select
from app.core.database import async_session
from app.models.export_task import ExportTask

async def main():
    async with async_session() as db:
        result = await db.execute(
            select(ExportTask).where(ExportTask.requested_by == 'smoke_test').order_by(ExportTask.created_at.desc()).limit(1)
        )
        task = result.scalar_one_or_none()
        if task:
            print(f'status={task.status}, file_path={task.file_path}, error={task.error_message}')

asyncio.run(main())
"
# 预期：status=completed, file_path 非空
```

---

## 与 M4 主计划的衔接

本补全计划完成后，M4 主计划（`2026-07-25-plan2-m4-frontend-website-e2e.md`）的执行需注意：

| M4 主计划任务 | 与本补全计划的关系 |
|--------------|-------------------|
| 任务 1：改造登录页 | 无依赖，独立执行 |
| 任务 2：改造数据总览页 | **合并执行**：M4 主计划任务 2 的 Dashboard.vue 代码已被本补全计划任务 4 替换增强版（含 ECharts 实例引用 + citation_count 修复 + 导出按钮）。执行 M4 任务 2 时直接用本补全计划任务 4 的代码 |
| 任务 3：新增分发记录页 | 无依赖，独立执行 |
| 任务 4：新增导出报告页 | **合并执行**：M4 主计划任务 4 的 ExportDialog.vue 已被本补全计划任务 5 替换增强版（接收 charts prop）。Exports.vue 的 dialog 调用改为 `:charts="{}"`。执行 M4 任务 4 时直接用本补全计划任务 5 的代码 |
| 任务 5：新增站点筛选 | 无依赖，独立执行 |
| 任务 6：新增审计日志页 | 无依赖，独立执行 |
| 任务 7：官网首页入口 | 无依赖，独立执行 |
| 任务 8：GEOFlow 后台菜单 | 无依赖，独立执行 |
| 任务 9：定时任务 + 归档 | **部分合并**：M4 主计划任务 9 的 scheduler.py 已被本补全计划任务 3 替换（含 export_processor + archive 任务）。执行 M4 任务 9 时只需追加 `scheduled_archive_scan` 和 `scheduled_monthly_archive`，保留本补全的 `scheduled_export_processor` |
| 任务 10：E2E 脚本 | 无依赖，独立执行 |
| 任务 11：本地测试 → 部署 | 无依赖，独立执行 |

---

## 计划完成

本补全计划的 5 个任务完成后，M3 里程碑审查发现的两个关键缺口全部闭合：

1. ✅ **缺口 1（export task 触发器）**：scheduler.py 加 `scheduled_export_processor`，每 30 秒扫 pending 任务调用 `ExportService.process_task`
2. ✅ **缺口 2（charts 字段上传）**：`ExportRequest.charts` → `ExportTask.charts` → `ExportService._assemble_data` → `PdfExportService` → `report.html` 端到端打通；前端 Dashboard 暴露 ECharts `getDataURL()` 并通过 ExportDialog 上传

附带修复：Dashboard 的 `citation_count` 从写死 0 改为调用 `/stats/citation` 获取（失败降级 0）。

之后可进入 M4 主计划的子代理驱动执行（11 任务，含 3 个合并任务）。
