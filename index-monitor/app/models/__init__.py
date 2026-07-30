# index-monitor/app/models/__init__.py
"""监测系统 ORM 模型包。

显式注册新模型便于：
1. 应用层 ``from app.models import ManualDistribution`` 统一入口；
2. alembic ``env.py`` 在 ``from app.models.base import Base`` 时触发本
   ``__init__`` 执行，使新模型注册到 ``Base.metadata``，为后续 autogenerate
   提供完整元数据。

注：历史模型（clients / article_distributions 等）目前在各自模块中独立
定义，未在此处集中注册——保持现状以避免本次任务扩大改动范围。
"""
from app.models.manual_distribution import ManualDistribution  # noqa: F401
from app.models.admin_audit_log import AdminAuditLog  # noqa: F401
from app.models.export_task import ExportTask  # noqa: F401
from app.models.archived_distribution import ArchivedDistribution  # noqa: F401
from app.models.client_question import ClientQuestion  # noqa: F401
