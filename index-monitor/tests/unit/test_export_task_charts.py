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
