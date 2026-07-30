# AI 监测逻辑重构 Phase 1：数据模型 + AI 收录检测服务 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 创建 `client_questions` 和 `ai_index_results` 两张新表，实现 `AIIndexChecker` 收录检测服务，能对 URL × 模型组合检测 AI 是否收录。

**架构：** 双阶段独立管道的 Phase 1——数据模型层（2 张新表 + 1 列变更）+ AI 收录检测服务（`AIIndexChecker` 类，复用现有 adapter 调用 AI 模型，判定收录状态存入 `ai_index_results`）。

**技术栈：** SQLAlchemy 2.0 (async) + Alembic + PostgreSQL (monitor schema) + asyncio + 现有 `citation_check/providers.py` adapter

**设计文档：** `docs/superpowers/specs/2026-07-30-ai-monitoring-refactor-design.md`

**迁移编号更正：** 设计文档写的是 012/013，但 012 已存在（`012_create_citation_check_logs.py`），实际新迁移为 013 和 014。

---

## 文件结构

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/models/client_question.py` | 客户问题模型（client_questions 表） | 新增 |
| `index-monitor/app/models/ai_index_result.py` | AI 收录结果模型（ai_index_results 表） | 新增 |
| `index-monitor/app/models/__init__.py` | 模型注册 | 修改：导出新模型 |
| `index-monitor/alembic/versions/013_create_client_questions_and_ai_index.py` | 迁移：创建 2 张新表 | 新增 |
| `index-monitor/alembic/versions/014_add_client_question_id_to_citation_results.py` | 迁移：citation_results 加列 | 新增 |
| `index-monitor/app/models/citation_result.py` | CitationResult 模型 | 修改：加 client_question_id 列 |
| `index-monitor/app/services/ai_index_checker.py` | AI 收录检测服务 | 新增 |
| `index-monitor/tests/test_ai_index_checker.py` | 收录检测服务测试 | 新增 |
| `index-monitor/tests/test_parse_index_response.py` | 响应判定逻辑测试 | 新增 |

---

## 任务 1：ClientQuestion 模型

**文件：**
- 创建：`index-monitor/app/models/client_question.py`
- 测试：无（模型定义，由迁移和后续集成测试覆盖）

- [ ] **步骤 1：创建 ClientQuestion 模型**

```python
# index-monitor/app/models/client_question.py
"""客户监测问题模型。

每个客户维护一组 AI 监测问题，用于问题监测阶段（替代自动生成）。
启用的问题（status='active'）将用于该客户所有文章的 AI 引用检测。
运营在客户管理界面配置，客户端只读查看。
"""
from sqlalchemy import Column, String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ClientQuestion(Base):
    __tablename__ = "client_questions"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 2：在 models/__init__.py 中注册**

运行 `cat index-monitor/app/models/__init__.py` 查看现有导出列表，然后添加：

```python
from app.models.client_question import ClientQuestion
```

- [ ] **步骤 3：Commit**

```bash
git add index-monitor/app/models/client_question.py index-monitor/app/models/__init__.py
git commit -m "feat(model): 新增 ClientQuestion 客户监测问题模型"
```

---

## 任务 2：AIIndexResult 模型

**文件：**
- 创建：`index-monitor/app/models/ai_index_result.py`

- [ ] **步骤 1：创建 AIIndexResult 模型**

```python
# index-monitor/app/models/ai_index_result.py
"""AI 收录检测结果模型。

记录每个 URL × AI 模型 的收录检测状态。
收录检测在问题监测之前执行：仅对 index_status='indexed' 的组合做问题监测。

状态流转：pending → indexed / not_indexed
- pending：尚未检测或检测失败（可重试）
- indexed：AI 回复中包含对该 URL 内容的实质描述
- not_indexed：AI 回复"不了解"/"不知道"等否定短语
"""
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class AIIndexResult(Base):
    __tablename__ = "ai_index_results"
    __table_args__ = monitor_table_args(
        UniqueConstraint("url", "model", name="uq_ai_index_url_model"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    model = Column(String(64), nullable=False, index=True)
    index_status = Column(String(32), nullable=False, default="pending", index=True)
    ai_response = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 2：在 models/__init__.py 中注册**

```python
from app.models.ai_index_result import AIIndexResult
```

- [ ] **步骤 3：Commit**

```bash
git add index-monitor/app/models/ai_index_result.py index-monitor/app/models/__init__.py
git commit -m "feat(model): 新增 AIIndexResult AI 收录检测结果模型"
```

---

## 任务 3：Alembic 迁移 013——创建 client_questions + ai_index_results 表

**文件：**
- 创建：`index-monitor/alembic/versions/013_create_client_questions_and_ai_index.py`

- [ ] **步骤 1：创建迁移文件**

```python
# index-monitor/alembic/versions/013_create_client_questions_and_ai_index.py
"""create client_questions and ai_index_results tables

Revision ID: 013
Revises: 012
Create Date: 2026-07-30

AI 监测逻辑重构 Phase 1：
- client_questions：客户监测问题集（替代 LLM 自动生成）
- ai_index_results：AI 收录检测结果（收录检测先行，仅对已收录 URL 做问题监测）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- client_questions ---
    op.create_table(
        "client_questions",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("client_id", sa.String(64), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="monitor",
    )
    op.create_index(
        "ix_client_questions_client_id",
        "client_questions",
        ["client_id"],
        schema="monitor",
    )
    op.create_index(
        "ix_client_questions_status",
        "client_questions",
        ["status"],
        schema="monitor",
    )

    # --- ai_index_results ---
    op.create_table(
        "ai_index_results",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("index_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("ai_response", sa.Text, nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "url", "model", name="uq_ai_index_url_model",
        ),
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_url",
        "ai_index_results",
        ["url"],
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_model",
        "ai_index_results",
        ["model"],
        schema="monitor",
    )
    op.create_index(
        "ix_ai_index_results_index_status",
        "ai_index_results",
        ["index_status"],
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("ai_index_results", schema="monitor")
    op.drop_table("client_questions", schema="monitor")
```

- [ ] **步骤 2：运行迁移验证**

运行：`cd index-monitor && alembic upgrade head`
预期：输出 `Running upgrade 012 -> 013, create client_questions and ai_index_results tables`

- [ ] **步骤 3：验证表存在**

运行：`docker exec geoflow-postgres psql -U postgres -d geo_flow -c "\dt monitor.client_questions" -c "\dt monitor.ai_index_results"`
预期：两张表均列出

- [ ] **步骤 4：Commit**

```bash
git add index-monitor/alembic/versions/013_create_client_questions_and_ai_index.py
git commit -m "feat(migration): 013 创建 client_questions + ai_index_results 表"
```

---

## 任务 4：Alembic 迁移 014——citation_results 加 client_question_id 列

**文件：**
- 创建：`index-monitor/alembic/versions/014_add_client_question_id_to_citation_results.py`
- 修改：`index-monitor/app/models/citation_result.py`

- [ ] **步骤 1：创建迁移文件**

```python
# index-monitor/alembic/versions/014_add_client_question_id_to_citation_results.py
"""add client_question_id to citation_results

Revision ID: 014
Revises: 013
Create Date: 2026-07-30

citation_results 新增 client_question_id 外键，关联 client_questions 表。
记录每条检测结果是用哪条客户问题检测的。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "citation_results",
        sa.Column("client_question_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        schema="monitor",
    )
    op.create_index(
        "ix_citation_results_client_question_id",
        "citation_results",
        ["client_question_id"],
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_index("ix_citation_results_client_question_id", table_name="citation_results", schema="monitor")
    op.drop_column("citation_results", "client_question_id", schema="monitor")
```

- [ ] **步骤 2：修改 CitationResult 模型加列**

在 `index-monitor/app/models/citation_result.py` 的 `CitationResult` 类中，`created_at` 列之前添加：

```python
    # AI 监测重构：关联客户问题（null 表示旧数据，由自动生成问题产生）
    client_question_id = Column(UUID(as_uuid=True), nullable=True, index=True)
```

- [ ] **步骤 3：运行迁移**

运行：`cd index-monitor && alembic upgrade head`
预期：输出 `Running upgrade 013 -> 014, add client_question_id to citation_results`

- [ ] **步骤 4：验证列存在**

运行：`docker exec geoflow-postgres psql -U postgres -d geo_flow -c "\d monitor.citation_results" | grep client_question_id`
预期：显示 `client_question_id | uuid`

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/alembic/versions/014_add_client_question_id_to_citation_results.py index-monitor/app/models/citation_result.py
git commit -m "feat(migration): 014 citation_results 加 client_question_id 列"
```

---

## 任务 5：parse_index_response 响应判定函数（TDD）

**文件：**
- 创建：`index-monitor/tests/test_parse_index_response.py`
- 创建：`index-monitor/app/services/ai_index_checker.py`（仅 parse_index_response 部分）

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/test_parse_index_response.py
"""parse_index_response 单元测试：验证 AI 收录检测响应判定逻辑。"""
from app.services.ai_index_checker import parse_index_response


class TestParseIndexResponse:
    """AI 回复 → indexed / not_indexed 判定。"""

    def test_short_negative_response(self):
        """短回复含否定短语 → not_indexed。"""
        assert parse_index_response("不了解") == "not_indexed"
        assert parse_index_response("不知道") == "not_indexed"
        assert parse_index_response("无法访问该网页") == "not_indexed"

    def test_starts_with_buliao_jie(self):
        """以'不了解'开头 → not_indexed（即使后面有内容）。"""
        assert parse_index_response("不了解该网页的内容，请提供更多信息") == "not_indexed"

    def test_substantive_description(self):
        """提供了实质描述 → indexed。"""
        response = (
            "该网页介绍了 XXX 公司最新发布的 YYY 产品，"
            "主要面向中小企业用户，核心功能包括自动化数据分析和可视化报表。"
        )
        assert parse_index_response(response) == "indexed"

    def test_long_negative_with_explanation(self):
        """长回复但明确否定 → not_indexed。"""
        response = "我没有关于该网页的相关信息，无法确认其内容。建议您直接访问该链接查看。"
        assert parse_index_response(response) == "not_indexed"

    def test_empty_response(self):
        """空回复 → not_indexed（AI 无内容可提供）。"""
        assert parse_index_response("") == "not_indexed"
        assert parse_index_response("   ") == "not_indexed"

    def test_generic_acknowledgment(self):
        """通用确认但无实质内容 → indexed（AI 声称了解）。"""
        response = "是的，我了解这个网页。它是一个关于产品介绍的页面。"
        assert parse_index_response(response) == "indexed"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/test_parse_index_response.py -v`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'app.services.ai_index_checker'`

- [ ] **步骤 3：创建 ai_index_checker.py 实现 parse_index_response**

```python
# index-monitor/app/services/ai_index_checker.py
"""AI 收录检测服务：检测 AI 大模型是否收录了目标 URL。

收录检测在问题监测之前执行（双阶段管道 Phase 1）：
1. 对每个 URL × 模型组合，直接询问 AI 是否了解该 URL
2. 解析响应判定 indexed / not_indexed
3. 存入 ai_index_results 表

仅对 index_status='indexed' 的组合执行问题监测（Phase 2 改造）。
"""
import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_index_result import AIIndexResult
from app.models.manual_distribution import ManualDistribution
from app.models.citation_check_log import CitationCheckLog
from app.models.system_config import SystemConfig
from app.services.scan_task_manager import add_log, update_progress

logger = logging.getLogger(__name__)

# AI 回复中的否定短语——命中即判定 not_indexed
NEGATIVE_PHRASES = (
    "不了解", "不知道", "无法访问", "没有相关信息",
    "未收录", "不清楚", "不熟悉", "无法获取",
    "我没有关于", "我无法确认", "无法确认其内容",
)


def parse_index_response(response: str) -> str:
    """判定 AI 收录检测响应 → 'indexed' 或 'not_indexed'。

    判定规则：
    1. 空回复 → not_indexed
    2. 以"不了解"开头 → not_indexed
    3. 短回复（<50字）含否定短语 → not_indexed
    4. 长回复含"我没有关于"/"我无法确认" → not_indexed
    5. 其他（AI 提供了实质描述）→ indexed
    """
    text = (response or "").strip()
    if not text:
        return "not_indexed"
    if text.startswith("不了解"):
        return "not_indexed"
    # 短回复含否定短语
    if len(text) < 50 and any(p in text for p in NEGATIVE_PHRASES):
        return "not_indexed"
    # 长回复中的强否定短语
    strong_negatives = ("我没有关于", "我无法确认", "无法确认其内容")
    if any(p in text for p in strong_negatives):
        return "not_indexed"
    return "indexed"


def build_index_prompt(url: str) -> str:
    """构建 AI 收录检测 prompt。"""
    return (
        f"你是否了解这个网页的内容？请直接回答。\n\n"
        f"URL: {url}\n\n"
        f"如果你了解该网页的内容，请用 100 字以内简要描述其主要内容。\n"
        f"如果你不了解，请只回答\"不了解\"。"
    )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/test_parse_index_response.py -v`
预期：6 个测试全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/ai_index_checker.py index-monitor/tests/test_parse_index_response.py
git commit -m "feat(ai-index): parse_index_response 响应判定函数 + 测试"
```

---

## 任务 6：AIIndexChecker.get_pending_urls 方法（TDD）

**文件：**
- 修改：`index-monitor/app/services/ai_index_checker.py`
- 创建：`index-monitor/tests/test_ai_index_checker.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/test_ai_index_checker.py
"""AIIndexChecker 单元测试。"""
import pytest
from sqlalchemy import select

from app.models.ai_index_result import AIIndexResult
from app.models.manual_distribution import ManualDistribution
from app.models.client_question import ClientQuestion
from app.services.ai_index_checker import AIIndexChecker


@pytest.mark.asyncio
async def test_get_pending_urls_returns_unchecked_combinations(db_session, monkeypatch):
    """get_pending_urls 返回 synced URL × 已配置模型 中 ai_index_results 无记录的组合。"""
    # 1. 插入一条手动分发记录
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/article-1",
        status="synced",
    ))
    await db_session.commit()

    # 2. mock 已配置模型列表
    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen", "doubao"]),
    )

    # 3. 调用 get_pending_urls
    checker = AIIndexChecker(db_session)
    pending = await checker.get_pending_urls()

    # 4. 应返回 2 个组合：URL × qwen, URL × doubao
    assert len(pending) == 2
    urls_models = {(url, model) for url, _, model in pending}
    assert ("https://example.com/article-1", "qwen") in urls_models
    assert ("https://example.com/article-1", "doubao") in urls_models


@pytest.mark.asyncio
async def test_get_pending_urls_excludes_checked(db_session, monkeypatch):
    """已有 ai_index_results 记录的组合不返回。"""
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/article-2",
        status="synced",
    ))
    # 已检测过 qwen → indexed
    db_session.add(AIIndexResult(
        url="https://example.com/article-2",
        model="qwen",
        index_status="indexed",
        ai_response="该网页介绍了...",
    ))
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen", "doubao"]),
    )

    checker = AIIndexChecker(db_session)
    pending = await checker.get_pending_urls()

    # qwen 已检测过，只返回 doubao
    assert len(pending) == 1
    assert pending[0][2] == "doubao"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "get_pending"`
预期：FAIL，报错 `AttributeError: 'AIIndexChecker' object has no attribute 'get_pending_urls'`

- [ ] **步骤 3：实现 get_pending_urls 和 _get_configured_models**

在 `ai_index_checker.py` 中添加（在 `build_index_prompt` 函数之后）：

```python
from app.integration.geoflow import GeoflowRepository
from app.models.client import ClientSite
from app.utils.validators import normalize_domain
from app.services.citation_check.providers import adapter_catalog
import os


class AIIndexChecker:
    """AI 收录检测器：检测 AI 大模型是否收录了目标 URL。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _get_configured_models() -> list[str]:
        """获取已配置 API Key 的 AI 模型 ID 列表（从 adapter_catalog）。"""
        return [item["id"] for item in adapter_catalog() if item["configured"]]

    async def get_pending_urls(self) -> list[tuple[str, str, str]]:
        """获取待收录检测的 URL × 模型组合（增量）。

        返回 [(url, client_id, model), ...]

        筛选条件：
        1. URL 已分发（manual_distributions status='synced' 或 GEOFlow 分发）
        2. ai_index_results 中无该 URL×model 记录（增量）
        """
        models = self._get_configured_models()
        if not models:
            logger.warning("未配置任何 AI 模型 API Key，无待检测组合")
            return []

        # 1. 收集已分发 URL → client_id 映射
        # 手动录入
        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        # GEOFlow 分发（跨 schema）
        try:
            repo = GeoflowRepository(self.db)
            geoflow_urls = await repo.get_synced_distribution_urls()
            sites_result = await self.db.execute(
                select(ClientSite).where(ClientSite.status == "active")
            )
            domain_map = {
                normalize_domain(s.domain): s.client_id
                for s in sites_result.scalars().all()
            }
            for url in geoflow_urls:
                domain = normalize_domain(url)
                client_id = domain_map.get(domain)
                if client_id:
                    distributed.setdefault(url, client_id)
        except Exception as exc:
            logger.warning("GEOFlow 分发查询失败（降级为仅手动录入）: %s", exc)

        if not distributed:
            return []

        # 2. 查已有收录检测记录，排除已检测的 URL×model 组合
        existing_result = await self.db.execute(
            select(AIIndexResult.url, AIIndexResult.model)
        )
        existing = {(row[0], row[1]) for row in existing_result.fetchall()}

        # 3. 生成 pending 组合
        pending: list[tuple[str, str, str]] = []
        for url, client_id in distributed.items():
            for model in models:
                if (url, model) not in existing:
                    pending.append((url, client_id, model))

        return pending
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "get_pending"`
预期：2 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/ai_index_checker.py index-monitor/tests/test_ai_index_checker.py
git commit -m "feat(ai-index): AIIndexChecker.get_pending_urls 增量获取待检测组合"
```

---

## 任务 7：AIIndexChecker.check_url 方法（TDD）

**文件：**
- 修改：`index-monitor/app/services/ai_index_checker.py`
- 修改：`index-monitor/tests/test_ai_index_checker.py`

- [ ] **步骤 1：编写失败的测试**

在 `test_ai_index_checker.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_check_url_stores_indexed_result(db_session, monkeypatch):
    """check_url 调用 adapter.ask 后存储收录结果。"""
    # mock adapter
    class FakeAdapter:
        provider_id = "qwen"
        name = "千问"
        model_id = "qwen3.6-plus"
        def ask(self, question):
            # 返回类似 ModelAnswer 的对象（只需要 text 属性）
            class FakeAnswer:
                text = "该网页介绍了 XXX 公司的 YYY 产品，主要面向中小企业。"
                sources = []
                search_used = False
                error = None
            return FakeAnswer()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FakeAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/test-article", "qwen",
    )

    assert result["index_status"] == "indexed"
    assert "XXX 公司" in result["ai_response"]

    # 验证已写入数据库
    db_result = await db_session.execute(
        select(AIIndexResult).where(
            AIIndexResult.url == "https://example.com/test-article",
            AIIndexResult.model == "qwen",
        )
    )
    record = db_result.scalar_one_or_none()
    assert record is not None
    assert record.index_status == "indexed"


@pytest.mark.asyncio
async def test_check_url_stores_not_indexed_result(db_session, monkeypatch):
    """AI 回答'不了解'时存储 not_indexed。"""
    class FakeAdapter:
        provider_id = "doubao"
        name = "豆包"
        model_id = "doubao-seed-2-0-lite-260428"
        def ask(self, question):
            class FakeAnswer:
                text = "不了解"
                sources = []
                search_used = False
                error = None
            return FakeAnswer()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FakeAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/unknown-article", "doubao",
    )

    assert result["index_status"] == "not_indexed"


@pytest.mark.asyncio
async def test_check_url_api_failure_keeps_pending(db_session, monkeypatch):
    """adapter 抛异常时 index_status 保持 pending（可重试）。"""
    class FailingAdapter:
        provider_id = "qwen"
        name = "千问"
        model_id = "qwen3.6-plus"
        def ask(self, question):
            raise RuntimeError("API 超时")

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._build_adapter",
        lambda self, model: FailingAdapter(),
    )

    checker = AIIndexChecker(db_session)
    result = await checker.check_url(
        "https://example.com/fail-article", "qwen",
    )

    # API 失败时保持 pending（不是 not_indexed）
    assert result["index_status"] == "pending"
    assert "API 超时" in result["error"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "check_url"`
预期：FAIL，报错 `AttributeError: 'AIIndexChecker' object has no attribute 'check_url'`

- [ ] **步骤 3：实现 check_url 和 _build_adapter**

在 `AIIndexChecker` 类中添加（`get_pending_urls` 方法之后）。

注意：需在文件顶部模块级 import 区添加 `from datetime import datetime, timezone`。

```python
    # 文件顶部 import 区添加（与现有 import 一起）：
    # from datetime import datetime, timezone

    def _build_adapter(self, model: str):
        """构建单个模型的 adapter（复用现有 providers.default_adapters）。

        收录检测禁用 web_search：测的是训练数据是否收录，非实时检索能力。
        """
        from app.services.citation_check.providers import default_adapters
        adapters = default_adapters([model])
        if not adapters:
            raise ValueError(f"模型 {model} 未配置 API Key 或不支持")
        return adapters[0]

    async def check_url(
        self,
        url: str,
        model: str,
        *,
        task_id: Optional[str] = None,
        progress: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> dict:
        """检测单个 URL 在单个模型上的收录状态。

        Returns:
            {"url", "model", "index_status", "ai_response", "error"}
            - index_status: 'indexed' / 'not_indexed' / 'pending'（API 失败时）
        """
        prompt = build_index_prompt(url)

        async def _report(stage, status, message, **kw):
            if progress:
                try:
                    await progress(stage, status, message, **kw)
                except Exception:
                    pass

        await _report("收录检测", "start", f"开始检测 {model} 是否收录: {url}")
        t0 = time.time()

        try:
            adapter = self._build_adapter(model)
            # adapter.ask 是同步调用，用 to_thread 包装
            answer = await asyncio.to_thread(adapter.ask, prompt)
            response_text = getattr(answer, "text", "") or ""

            index_status = parse_index_response(response_text)

            # 存储结果（幂等：UNIQUE(url, model)）
            await self._store_result(url, model, index_status, response_text)

            await _report(
                "收录检测", "success",
                f"{model} → {index_status}",
                model=model,
                duration_ms=int((time.time() - t0) * 1000),
            )

            return {
                "url": url,
                "model": model,
                "index_status": index_status,
                "ai_response": response_text,
                "error": None,
            }

        except Exception as exc:
            logger.error("收录检测失败 %s [%s]: %s", url, model, exc)
            # API 失败时存储 pending 状态（可重试），区分于 not_indexed
            await self._store_result(url, model, "pending", str(exc))

            await _report(
                "收录检测", "error",
                f"{model} 检测失败: {exc}",
                model=model,
                duration_ms=int((time.time() - t0) * 1000),
            )

            return {
                "url": url,
                "model": model,
                "index_status": "pending",
                "ai_response": None,
                "error": str(exc),
            }

    async def _store_result(
        self, url: str, model: str, index_status: str, ai_response: str
    ) -> None:
        """存储收录检测结果（幂等：UNIQUE(url, model)）。"""
        existing = await self.db.execute(
            select(AIIndexResult).where(
                AIIndexResult.url == url,
                AIIndexResult.model == model,
            )
        )
        record = existing.scalar_one_or_none()
        if record:
            record.index_status = index_status
            record.ai_response = ai_response
            record.checked_at = datetime.now(timezone.utc)
        else:
            self.db.add(AIIndexResult(
                url=url,
                model=model,
                index_status=index_status,
                ai_response=ai_response,
                checked_at=datetime.now(timezone.utc),
            ))
        await self.db.commit()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "check_url"`
预期：3 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/ai_index_checker.py index-monitor/tests/test_ai_index_checker.py
git commit -m "feat(ai-index): AIIndexChecker.check_url 单 URL×模型收录检测"
```

---

## 任务 8：AIIndexChecker.check_all_pending 方法（TDD）

**文件：**
- 修改：`index-monitor/app/services/ai_index_checker.py`
- 修改：`index-monitor/tests/test_ai_index_checker.py`

- [ ] **步骤 1：编写失败的测试**

在 `test_ai_index_checker.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_check_all_pending_concurrent(db_session, monkeypatch):
    """check_all_pending 并发检测多个 URL×模型组合，返回汇总。"""
    # 2 个 URL × 1 个模型 = 2 个组合
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/batch-1",
        status="synced",
    ))
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/batch-2",
        status="synced",
    ))
    await db_session.commit()

    # mock 模型列表只返回 qwen
    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen"]),
    )

    # mock check_url 不实际调 AI，直接存 indexed
    async def fake_check_url(self, url, model, *, task_id=None, progress=None):
        await self._store_result(url, model, "indexed", "mock response")
        return {"url": url, "model": model, "index_status": "indexed", "error": None}

    monkeypatch.setattr(AIIndexChecker, "check_url", fake_check_url)

    checker = AIIndexChecker(db_session)
    result = await checker.check_all_pending(concurrency=2)

    assert result["total"] == 2
    assert result["success"] == 2
    assert result["failed"] == 0
    assert len(result["failures"]) == 0


@pytest.mark.asyncio
async def test_check_all_pending_with_failure(db_session, monkeypatch):
    """部分组合失败时不影响其他，记入 failures。"""
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/ok-url",
        status="synced",
    ))
    db_session.add(ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/fail-url",
        status="synced",
    ))
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.ai_index_checker.AIIndexChecker._get_configured_models",
        staticmethod(lambda: ["qwen"]),
    )

    call_count = [0]
    async def fake_check_url(self, url, model, *, task_id=None, progress=None):
        call_count[0] += 1
        if "fail-url" in url:
            raise RuntimeError("模拟 API 失败")
        await self._store_result(url, model, "indexed", "ok")
        return {"url": url, "model": model, "index_status": "indexed", "error": None}

    monkeypatch.setattr(AIIndexChecker, "check_url", fake_check_url)

    checker = AIIndexChecker(db_session)
    result = await checker.check_all_pending(concurrency=2)

    assert result["total"] == 2
    assert result["success"] == 1
    assert result["failed"] == 1
    assert len(result["failures"]) == 1
    assert "fail-url" in result["failures"][0]["url"]
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "check_all"`
预期：FAIL，报错 `AttributeError: 'AIIndexChecker' object has no attribute 'check_all_pending'`

- [ ] **步骤 3：实现 check_all_pending**

在 `AIIndexChecker` 类中添加（`_store_result` 方法之后）：

```python
    async def check_all_pending(
        self, *, task_id: Optional[str] = None, concurrency: int = 3
    ) -> dict:
        """批量检测所有待检测的 URL×模型组合（增量）。

        并发执行，单条失败不影响其他。

        Returns:
            {"total", "success", "failed", "failures"}
            failures 项：{"url", "model", "error"}
        """
        pending = await self.get_pending_urls()
        total = len(pending)
        if total == 0:
            return {"total": 0, "success": 0, "failed": 0, "failures": []}

        if task_id:
            try:
                update_progress(task_id, total=total)
            except Exception as exc:
                logger.warning("update_progress(total) 失败（已忽略）: %s", exc)

        from app.core.database import async_session
        semaphore = asyncio.Semaphore(max(1, concurrency))
        results: list[dict] = []
        processed = 0

        async def _check_one(url: str, client_id: str, model: str) -> None:
            nonlocal processed
            async with semaphore:
                # 独立 session：AsyncSession 并发不安全
                async with async_session() as task_db:
                    checker = AIIndexChecker(task_db)
                    try:
                        await checker.check_url(url, model, task_id=task_id)
                        results.append({"ok": True, "url": url, "model": model})
                    except Exception as exc:
                        logger.error("收录检测失败 %s [%s]: %s", url, model, exc)
                        results.append({
                            "ok": False, "url": url, "model": model, "error": str(exc),
                        })
                processed += 1
                if task_id:
                    try:
                        update_progress(
                            task_id,
                            processed=processed,
                            success=sum(1 for r in results if r["ok"]),
                            failed=sum(1 for r in results if not r["ok"]),
                        )
                    except Exception as exc:
                        logger.warning("update_progress 失败（已忽略）: %s", exc)

        await asyncio.gather(
            *[_check_one(url, cid, model) for url, cid, model in pending]
        )

        success = sum(1 for r in results if r["ok"])
        failures = [
            {"url": r["url"], "model": r["model"], "error": r["error"]}
            for r in results if not r["ok"]
        ]

        return {
            "total": total,
            "success": success,
            "failed": len(failures),
            "failures": failures,
        }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py -v -k "check_all"`
预期：2 个测试 PASS

- [ ] **步骤 5：运行全部测试确认无回归**

运行：`cd index-monitor && python -m pytest tests/test_ai_index_checker.py tests/test_parse_index_response.py -v`
预期：全部 PASS

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/services/ai_index_checker.py index-monitor/tests/test_ai_index_checker.py
git commit -m "feat(ai-index): AIIndexChecker.check_all_pending 批量并发检测"
```

---

## 自检

### 规格覆盖度

| 设计文档章节 | 对应任务 | 状态 |
|-------------|---------|------|
| 数据模型 - client_questions 表 | 任务 1 + 任务 3 | ✅ |
| 数据模型 - ai_index_results 表 | 任务 2 + 任务 3 | ✅ |
| 数据模型 - citation_results 加列 | 任务 4 | ✅ |
| AI 收录检测 - parse_index_response | 任务 5 | ✅ |
| AI 收录检测 - get_pending_urls | 任务 6 | ✅ |
| AI 收录检测 - check_url | 任务 7 | ✅ |
| AI 收录检测 - check_all_pending | 任务 8 | ✅ |
| AI 收录检测 - 增量逻辑 | 任务 6（排除 existing） | ✅ |
| AI 收录检测 - 错误处理保持 pending | 任务 7（test_check_url_api_failure） | ✅ |

### 后续 Phase 覆盖

以下设计章节由后续 Phase 实现，不在本计划范围：
- 问题监测改造（Phase 2）
- API 端点（Phase 3）
- 前端 UI（Phase 4）
- 自动联动（新文章入库 → 收录检测 → 问题监测）属 Phase 3 API 层
