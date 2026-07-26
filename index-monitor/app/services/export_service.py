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
        """组装导出数据。

        C10 修复：把 ``task.date_from`` / ``task.date_to`` 透传给
        ``list_distributions``，使导出报告的数据范围与用户在导出对话框中
        选择的日期范围一致（原实现未传递，导出报告始终包含全量数据）。
        """
        query_service = DistributionQueryService(self.db)

        # 查分发记录（C10：透传 task 的日期范围）
        distributions = await query_service.list_distributions(
            client_id=task.client_id,
            date_from=task.date_from,
            date_to=task.date_to,
        )

        # 查收录检测结果
        urls = [d["remote_url"] for d in distributions if d.get("remote_url")]
        index_results = []
        # 构建 url → 收录状态 的映射，用于合并到 distributions
        index_map = {}
        if urls:
            ir_result = await self.db.execute(
                select(IndexResult).where(IndexResult.url.in_(urls))
            )
            for ir in ir_result.scalars().all():
                status = {
                    "url": ir.url,
                    "baidu": ir.baidu_status,
                    "toutiao": ir.toutiao_status,
                    "sogou": ir.sogou_status,
                    "so360": ir.so360_status,
                    "bing": ir.bing_status,
                    "baidu_status": ir.baidu_status,
                    "toutiao_status": ir.toutiao_status,
                    "sogou_status": ir.sogou_status,
                    "so360_status": ir.so360_status,
                    "bing_status": ir.bing_status,
                    "content_title": ir.content_title,
                    "content_snapshot": ir.content_snapshot,
                    "checked_at": ir.updated_at.isoformat() if ir.updated_at else None,
                }
                index_results.append(status)
                index_map[ir.url] = status

        # 将收录状态、标题和快照合并到 distributions（供 PDF 模板直接访问 dist.baidu_status 等）
        for dist in distributions:
            url = dist.get("remote_url")
            if url and url in index_map:
                ir = index_map[url]
                dist["baidu_status"] = ir["baidu_status"]
                dist["toutiao_status"] = ir["toutiao_status"]
                dist["sogou_status"] = ir["sogou_status"]
                dist["so360_status"] = ir["so360_status"]
                dist["bing_status"] = ir["bing_status"]
                dist["content_title"] = ir["content_title"] or dist.get("content_title")
                # 合并文章快照（PDF 报告展示用）
                dist["content_snapshot"] = ir["content_snapshot"] or dist.get("content_snapshot", "")
            else:
                # 默认值
                dist.setdefault("baidu_status", "pending")
                dist.setdefault("toutiao_status", "pending")
                dist.setdefault("sogou_status", "pending")
                dist.setdefault("so360_status", "pending")
                dist.setdefault("bing_status", "pending")
                dist.setdefault("content_title", dist.get("content_title", ""))
                dist.setdefault("content_snapshot", dist.get("content_snapshot", ""))

        # 查采信检测结果（含 AI 回答原文，供 PDF 报告翔实展示）
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
                    "answer": cr.answer,
                    "hit_type": cr.hit_type,
                    "sources": cr.sources,
                    "checked_at": cr.checked_at.isoformat() if cr.checked_at else None,
                }
                for cr in cr_result.scalars().all()
            ]

        # 统计汇总
        indexed_count = sum(
            1 for ir in index_results
            if any(ir.get(k) == "indexed" for k in ("baidu", "toutiao", "sogou", "so360", "bing"))
        )
        # 修复 AI 采信数：只统计 hit_type != "none" 的记录（真正被采信的）
        # 原逻辑用 len(citation_results) 包含所有检测记录（含未命中），导致虚高
        cited_count = sum(1 for cr in citation_results if cr.get("hit_type") != "none")
        summary = {
            "total_distributions": len(distributions),
            "indexed_count": indexed_count,
            "citation_count": cited_count,
            "avg_index_rate": indexed_count / len(distributions) if distributions else 0,
        }

        return {
            "client_name": task.client_id or "全部客户",
            "date_from": task.date_from.isoformat() if task.date_from else "",
            "date_to": task.date_to.isoformat() if task.date_to else "",
            "distributions": distributions,
            "index_results": index_results,
            "citation_results": citation_results,
            "citation_details": citation_results,  # PDF 模板用 citation_details 字段
            "summary": summary,
            "stats": summary,  # PDF 模板用 stats 字段
            "charts": task.charts or {},  # 从 task.charts 读取（M4 补全，替换写死的 {}）
        }
