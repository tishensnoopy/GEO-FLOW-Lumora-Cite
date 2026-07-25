# index-monitor/tests/unit/test_export_service.py
"""ExportService 测试：任务状态机 + 数据组装。"""
import os
import pytest

from app.services.export_service import ExportService


@pytest.fixture(autouse=True, scope="module")
def ensure_geoflow_tables():
    """Module 级 autouse fixture：确保 GEOFlow public schema 表存在。

    ExportService._assemble_data 会调 DistributionQueryService.list_distributions，
    后者跨 schema JOIN ``public.article_distributions``。测试 DB public schema
    默认无 GEOFlow 真实表，且 ``tests/integration/test_cross_schema_join.py``
    的 module fixture teardown 会 DROP 这些表。本 fixture 在模块开始时用
    ``GeoflowBase.metadata.create_all`` 建表（IF NOT EXISTS 幂等）。

    与 ``test_distribution_query_service.py`` 中同款 fixture 保持一致。
    用 sync engine（psycopg2）避免 strict asyncio 模式下 module 级 async
    fixture 与 per-test 事件循环冲突。
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


@pytest.mark.asyncio
async def test_process_pdf_task_completes(db_session, tmp_path):
    """处理 PDF 导出任务：pending → processing → completed。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None,  # admin 导出全部
        requested_by="测试管理员",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session, output_dir=str(tmp_path))
    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.file_path is not None
    assert os.path.exists(task.file_path)
    assert task.file_path.endswith(".pdf")

    # 清理
    if os.path.exists(task.file_path):
        os.remove(task.file_path)
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_process_excel_task_completes(db_session, tmp_path):
    """处理 Excel 导出任务。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None,
        requested_by="测试管理员",
        requested_by_role="admin",
        export_type="excel",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session, output_dir=str(tmp_path))
    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.file_path.endswith(".xlsx")

    if os.path.exists(task.file_path):
        os.remove(task.file_path)
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_process_task_records_error_on_failure(db_session, monkeypatch):
    """导出失败时 status=failed + error_message 记录。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None, requested_by="admin", requested_by_role="admin",
        export_type="pdf", status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session)

    # Mock PdfExportService.generate_pdf 抛异常
    async def mock_fail(*args, **kwargs):
        raise RuntimeError("模拟渲染失败")
    monkeypatch.setattr(service.pdf_service, "generate_pdf", mock_fail)

    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "failed"
    assert "模拟渲染失败" in task.error_message

    await db_session.delete(task)
    await db_session.commit()
