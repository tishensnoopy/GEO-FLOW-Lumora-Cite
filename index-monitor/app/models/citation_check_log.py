# index-monitor/app/models/citation_check_log.py
"""CitationCheckLog 模型：采信检测过程日志（阶段 1 - ④a）。

用途
====
持久化单 URL 采信检测的 5 阶段执行日志，供 ScanPanel 终端面板
按 task_id 拉取实时进度，解决"采信检测黑盒"问题（用户问题 3）。

字段说明
========
- id：UUID 主键
- task_id：批量扫描任务 ID（可空）。手动触发扫描时由 scan_task_manager 签发；
  定时任务无 task_id（NULL）。前端按 task_id 过滤本任务的日志。
- url：被检测的 URL。同一 task_id 下可能有多条 URL 的日志。
- stage：阶段标识，对应 check_url 的 5 步：
  "1/5 抓取" / "2/5 目的推断" / "3/5 问题生成" / "4/5 模型探测" / "5/5 引用检测"
- status：阶段状态，"start" / "success" / "error" / "info"
- model：模型名（可空）。仅 stage 4/5 涉及具体模型时填写。
- detail：JSONB，阶段详情（如 probe 结果、失败原因、命中统计）
- duration_ms：阶段耗时（毫秒）
- created_at：记录时间，建索引便于按时间范围清理

索引
====
- task_id / url / created_at 单列索引
- (task_id, created_at) 组合索引：ScanPanel 按 task_id 拉取时序日志的主查询路径

清理
====
scheduler 每日清理 30 天前记录（阶段 3-② 实现），避免日志膨胀。
"""
from sqlalchemy import Column, String, DateTime, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class CitationCheckLog(Base):
    __tablename__ = "citation_check_logs"
    # 组合索引 (task_id, created_at)：ScanPanel 按 task_id 拉取时序日志的主路径
    __table_args__ = monitor_table_args(
        Index("ix_citation_check_logs_task_id_created_at", "task_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # task_id 可空：定时任务无 task_id
    task_id = Column(String(64), nullable=True, index=True)
    url = Column(String(512), nullable=False, index=True)
    stage = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    # model 可空：非模型阶段（抓取/目的推断/问题生成）无 model
    model = Column(String(64), nullable=True)
    detail = Column(JSONB)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
