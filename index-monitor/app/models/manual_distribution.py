# index-monitor/app/models/manual_distribution.py
"""手动录入的 URL 分发记录。

运营 admin 可手动录入 URL（不依赖 GEOFlow 分发），用于监测非 GEOFlow 渠道
发布的文章。与 GEOFlow 的 public.article_distributions 互补：
- GEOFlow 分发 → 跨 schema 查询自动可见（source='geoflow'）
- 手动录入 → 写入 monitor.manual_distributions（source='manual'）

唯一约束 (client_id, remote_url)：同一客户的同一 URL 不能重复录入。
跨客户允许同一 URL（不同客户可能监测同一篇文章）。
"""
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
    # 修复：新增 content_title 字段，存储抓取到的文章标题
    # 原逻辑只更新已存在的 IndexResult，手动添加时 IndexResult 不存在，标题被丢弃
    content_title = Column(String(512), nullable=True)
    created_by_admin_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
