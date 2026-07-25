# index-monitor/app/services/export_service.py
"""导出任务编排服务：状态机 + 数据组装 + 调用 PdfExportService/ExcelExportService。

设计文档第 12.6 节。

状态机：pending → processing → completed / failed
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_result import CitationResult
from app.models.export_task import ExportTask
from app.models.index_result import IndexResult
from app.services.distribution_query import DistributionQueryService
from app.services.pdf_export_service import PdfExportService
from app.services.excel_export_service import ExcelExportService

logger = logging.getLogger(__name__)


class ExportService:
    def __init__(self, db: AsyncSession, output_dir: str = "/app/exports"):
        self.db = db
        self.output_dir = output_dir
        self.pdf_service = PdfExportService(output_dir=output_dir)
        self.excel_service = ExcelExportService(output_dir=output_dir)

    async def process_task(self, task_id: str) -> None:
        """处理导出任务（同步调用，但内部用 async Playwright）。

        生产环境可改为后台任务（APScheduler / Celery），此处保持简单。
        """
        result = await self.db.execute(
            select(ExportTask).where(ExportTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            logger.error(f"导出任务 {task_id} 不存在")
            return

        # 标记 processing
        task.status = "processing"
        await self.db.commit()

        try:
            # 组装数据
            export_data = await self._assemble_data(task)

            # 调用对应导出服务
            if task.export_type == "pdf":
                file_path = await self.pdf_service.generate_pdf(
                    export_data, filename=f"export_{task.id}.pdf"
                )
            elif task.export_type == "excel":
                file_path = await self.excel_service.generate_excel(
                    export_data, filename=f"export_{task.id}.xlsx"
                )
            else:
                raise ValueError(f"不支持的导出类型：{task.export_type}")

            # 标记 completed
            task.file_path = file_path
            task.file_size = os.path.getsize(file_path)
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            await self.db.commit()

            logger.info(f"导出任务 {task_id} 完成：{file_path}")

        except Exception as e:
            logger.exception(f"导出任务 {task_id} 失败")
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def _assemble_data(self, task: ExportTask) -> dict:
        """组装导出数据。"""
        query_service = DistributionQueryService(self.db)

        # 查分发记录
        distributions = await query_service.list_distributions(
            client_id=task.client_id
        )

        # 查收录检测结果
        urls = [d["remote_url"] for d in distributions if d.get("remote_url")]
        index_results = []
        if urls:
            ir_result = await self.db.execute(
                select(IndexResult).where(IndexResult.url.in_(urls))
            )
            index_results = [
                {
                    "url": ir.url,
                    "baidu": ir.baidu_status,
                    "toutiao": ir.toutiao_status,
                    "sogou": ir.sogou_status,
                    "so360": ir.so360_status,
                    "bing": ir.bing_status,
                    "checked_at": ir.updated_at.isoformat() if ir.updated_at else None,
                }
                for ir in ir_result.scalars().all()
            ]

        # 查采信检测结果
        citation_results = []
        if urls:
            cr_result = await self.db.execute(
                select(CitationResult).where(CitationResult.url.in_(urls))
            )
            citation_results = [
                {
                    "url": cr.url,
                    "model": cr.model,
                    "question": cr.question,
                    "hit_type": cr.hit_type,
                    "checked_at": cr.checked_at.isoformat() if cr.checked_at else None,
                }
                for cr in cr_result.scalars().all()
            ]

        # 统计汇总
        indexed_count = sum(
            1 for ir in index_results
            if any(ir.get(k) == "indexed" for k in ("baidu", "toutiao", "sogou", "so360", "bing"))
        )
        summary = {
            "total_distributions": len(distributions),
            "indexed_count": indexed_count,
            "citation_count": len(citation_results),
            "avg_index_rate": indexed_count / len(distributions) if distributions else 0,
        }

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
