# 阶段 4：网页端校准 + 置信度标注 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 用阶段 3 的网页端模拟引擎对 API 引用检测结果进行采样校准，计算平台置信度，并在客户前端展示置信度标签。

**架构：** 采样 citation_results → 网页端模拟重新检测 → 对比 API vs 网页端 hit_type → 存入 citation_calibrations → 计算平台置信度 → 前端展示。

**技术栈：** Python 3.11 / FastAPI / SQLAlchemy 2.0 async / Alembic / Vue 3 + Element Plus / pytest-asyncio

**规格文档：** `docs/superpowers/specs/2026-08-03-stage4-calibration-design.md`

---

## 文件结构

| 文件 | 类型 | 职责 |
|------|------|------|
| `app/models/citation_calibration.py` | 新增 | 校准结果模型 |
| `alembic/versions/016_add_citation_calibrations.py` | 新增 | 数据库迁移 |
| `app/services/calibration_service.py` | 新增 | 校准服务（采样+对比+置信度） |
| `app/api/admin_routes.py` | 修改 | 新增校准触发/查询端点 |
| `app/api/client_routes.py` | 修改 | 新增客户置信度端点 + 增强 rankings/visibility |
| `dashboard/src/api/clientView.js` | 修改 | 新增 confidence API 调用 |
| `dashboard/src/views/client/ClientRankings.vue` | 修改 | 回答快照增加置信度标签 |
| `dashboard/src/views/client/ClientOverview.vue` | 修改 | 可见度增加置信度列 |
| `tests/unit/test_citation_calibration.py` | 新增 | 模型测试 |
| `tests/unit/test_calibration_service.py` | 新增 | 服务测试 |
| `tests/unit/test_calibration_api.py` | 新增 | API 端点测试 |

---

## 任务 1：创建 CitationCalibration 模型 + 迁移

**文件：**
- 创建：`app/models/citation_calibration.py`
- 创建：`alembic/versions/016_add_citation_calibrations.py`
- 测试：`tests/unit/test_citation_calibration.py`

- [ ] **步骤 1：编写模型测试**

```python
# tests/unit/test_citation_calibration.py
"""CitationCalibration 模型测试。"""
from app.models.citation_calibration import CitationCalibration


def test_model_fields():
    """模型字段完整性检查。"""
    cols = {c.name for c in CitationCalibration.__table__.columns}
    assert cols == {
        "id", "citation_result_id", "platform_id",
        "web_answer", "web_sources", "web_hit_type",
        "api_hit_type", "matches", "note",
        "calibrated_at", "created_at",
    }


def test_model_schema():
    """表属于 monitor schema。"""
    assert CitationCalibration.__table__.schema == "monitor"


def test_unique_constraint():
    """(citation_result_id, platform_id) 唯一约束存在。"""
    constraints = CitationCalibration.__table__.constraints
    uq_names = [c.name for c in constraints if hasattr(c, "name") and c.name]
    assert any("uq_calibration_result_platform" in name for name in uq_names)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_citation_calibration.py -v`
预期：FAIL，报错 `No module named 'app.models.citation_calibration'`

- [ ] **步骤 3：创建模型文件**

```python
# app/models/citation_calibration.py
"""引用检测校准结果模型（阶段 4）。

存储网页端模拟对 API 引用检测结果的校准数据：
- 对 citation_results 中的每条记录，用网页端模拟重新检测
- 对比 API hit_type vs 网页端 hit_type
- 用于计算平台置信度
"""
from sqlalchemy import Column, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class CitationCalibration(Base):
    __tablename__ = "citation_calibrations"
    __table_args__ = monitor_table_args(
        UniqueConstraint(
            "citation_result_id", "platform_id",
            name="uq_calibration_result_platform",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    citation_result_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform_id = Column(String(64), nullable=False)
    web_answer = Column(Text)
    web_sources = Column(JSONB)
    web_hit_type = Column(String(32))
    api_hit_type = Column(String(32))
    matches = Column(Boolean, nullable=False)
    note = Column(Text)
    calibrated_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 4：创建 Alembic 迁移**

```python
# alembic/versions/016_add_citation_calibrations.py
"""add citation_calibrations table

Revision ID: 016_citation_calibrations
Revises: 015_article_question_mappings
Create Date: 2026-08-03

引用检测校准结果表（阶段 4）。
存储网页端模拟对 API 引用检测结果的校准数据。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "016_citation_calibrations"
down_revision: Union[str, None] = "015_article_question_mappings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "citation_calibrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("citation_result_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("platform_id", sa.String(64), nullable=False),
        sa.Column("web_answer", sa.Text),
        sa.Column("web_sources", JSONB),
        sa.Column("web_hit_type", sa.String(32)),
        sa.Column("api_hit_type", sa.String(32)),
        sa.Column("matches", sa.Boolean, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "citation_result_id", "platform_id",
            name="uq_calibration_result_platform",
        ),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("citation_calibrations", schema="monitor")
```

- [ ] **步骤 5：运行迁移和测试**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && alembic upgrade head && python -m pytest tests/unit/test_citation_calibration.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add app/models/citation_calibration.py alembic/versions/016_add_citation_calibrations.py tests/unit/test_citation_calibration.py
git commit -m "feat(stage4): 新增 CitationCalibration 模型和迁移（校准结果存储）"
```

---

## 任务 2：创建 CalibrationService 校准服务

**文件：**
- 创建：`app/services/calibration_service.py`
- 测试：`tests/unit/test_calibration_service.py`

- [ ] **步骤 1：编写服务测试**

```python
# tests/unit/test_calibration_service.py
"""CalibrationService 校准服务测试。"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.calibration_service import CalibrationService, compare_hits, get_confidence_level


def test_compare_hits_both_cited_exact():
    """API exact vs 网页 exact → 一致。"""
    assert compare_hits("exact", "exact") is True


def test_compare_hits_both_cited_mixed():
    """API exact vs 网页 domain → 一致（都算被引用）。"""
    assert compare_hits("exact", "domain") is True


def test_compare_hits_both_none():
    """API none vs 网页 none → 一致。"""
    assert compare_hits("none", "none") is True


def test_compare_hits_api_cited_web_none():
    """API cited vs 网页 none → 不一致。"""
    assert compare_hits("exact", "none") is False


def test_compare_hits_api_none_web_cited():
    """API none vs 网页 cited → 不一致。"""
    assert compare_hits("none", "domain") is False


def test_get_confidence_level_high():
    """≥80% → high。"""
    assert get_confidence_level(85) == "high"
    assert get_confidence_level(80) == "high"


def test_get_confidence_level_medium():
    """50-79% → medium。"""
    assert get_confidence_level(79) == "medium"
    assert get_confidence_level(50) == "medium"


def test_get_confidence_level_low():
    """<50% → low。"""
    assert get_confidence_level(49) == "low"
    assert get_confidence_level(0) == "low"


def test_get_confidence_level_uncalibrated():
    """-1 → uncalibrated。"""
    assert get_confidence_level(-1) == "uncalibrated"


@pytest.mark.asyncio
async def test_run_calibration_no_platforms(db_session, monkeypatch):
    """无可用网页端模拟平台时返回空结果。"""
    monkeypatch.setattr(
        "app.services.calibration_service.get_web_simulation_manager",
        lambda: MagicMock(available_platforms=lambda: []),
    )
    service = CalibrationService(db_session)
    result = await service.run_calibration()
    assert result == {}


@pytest.mark.asyncio
async def test_get_platform_confidence_no_data(db_session):
    """无校准数据时返回 uncalibrated。"""
    service = CalibrationService(db_session)
    result = await service.get_platform_confidence("yuanbao")
    assert result["level"] == "uncalibrated"
    assert result["confidence"] == -1
    assert result["total_calibrations"] == 0


@pytest.mark.asyncio
async def test_get_all_confidence_empty(db_session):
    """无校准数据时返回空列表。"""
    service = CalibrationService(db_session)
    result = await service.get_all_confidence()
    assert result == []
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_calibration_service.py -v`
预期：FAIL，报错 `No module named 'app.services.calibration_service'`

- [ ] **步骤 3：创建校准服务**

```python
# app/services/calibration_service.py
"""引用检测校准服务（阶段 4）。

采样 citation_results，用网页端模拟重新检测，对比 API vs 网页端结果，
计算平台置信度。
"""
import logging
import random
from uuid import UUID
from typing import Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_result import CitationResult
from app.models.citation_calibration import CitationCalibration
from app.services.web_simulation import get_web_simulation_manager

logger = logging.getLogger(__name__)

CITED_HIT_TYPES = ("exact", "domain")
DEFAULT_SAMPLE_RATE = 0.1
MIN_SAMPLE_SIZE = 5


def compare_hits(api_hit: str, web_hit: str) -> bool:
    """对比 API 与网页端命中类型是否一致。

    一致定义：两者都判定为"被引用"（exact/domain）或都"未被引用"（none）。
    不区分 exact 和 domain——两者都算被引用。
    """
    api_cited = api_hit in CITED_HIT_TYPES
    web_cited = web_hit in CITED_HIT_TYPES
    return api_cited == web_cited


def get_confidence_level(confidence: int) -> str:
    """置信度分级。

    -1 → uncalibrated（无校准数据）
    ≥80 → high
    50-79 → medium
    <50 → low
    """
    if confidence < 0:
        return "uncalibrated"
    if confidence >= 80:
        return "high"
    if confidence >= 50:
        return "medium"
    return "low"


class CalibrationService:
    """引用检测校准服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_calibration(
        self, sample_rate: float = DEFAULT_SAMPLE_RATE
    ) -> dict:
        """执行一轮校准。

        1. 获取已注册的网页端模拟平台
        2. 对每个平台，从 citation_results 采样
        3. 用网页端模拟重新检测
        4. 对比并存入 citation_calibrations
        返回 {platform_id: {sampled, calibrated, matched, match_rate}}
        """
        manager = get_web_simulation_manager()
        platforms = manager.available_platforms()
        if not platforms:
            logger.info("校准跳过：无可用网页端模拟平台")
            return {}

        results: dict[str, dict] = {}
        for platform_id in platforms:
            stats = await self._calibrate_platform(platform_id, sample_rate)
            results[platform_id] = stats

        return results

    async def _calibrate_platform(
        self, platform_id: str, sample_rate: float
    ) -> dict:
        """对单个平台执行校准。"""
        # 1. 采样待校准的 citation_results
        samples = await self._sample_citation_results(platform_id, sample_rate)
        if not samples:
            logger.info("校准跳过 %s：无可校准数据", platform_id)
            return {"sampled": 0, "calibrated": 0, "matched": 0, "match_rate": 0}

        manager = get_web_simulation_manager()
        calibrated = 0
        matched = 0

        for cit in samples:
            # 2. 用网页端模拟重新检测
            target_urls = [cit.url] if cit.url else []
            try:
                sim_result = await manager.simulate(
                    platform_id, cit.question, target_urls, timeout=60,
                )
            except Exception as exc:
                logger.warning("校准 %s 模拟失败 %s: %s", platform_id, cit.id, exc)
                await self._save_calibration(
                    cit, platform_id, "", [], "none",
                    note=f"模拟异常: {exc}", matches=False,
                )
                calibrated += 1
                continue

            if not sim_result.success:
                await self._save_calibration(
                    cit, platform_id, sim_result.answer or "",
                    sim_result.sources, "none",
                    note=sim_result.error or "模拟失败",
                    matches=False,
                )
                calibrated += 1
                continue

            # 3. 判定网页端命中类型
            from app.services.citation_check.matching import classify_citation_hit
            source_urls = [s.get("url", "") for s in sim_result.sources if s.get("url")]
            web_hit = classify_citation_hit(target_urls, source_urls).layer

            # 4. 对比
            is_match = compare_hits(cit.hit_type, web_hit)
            await self._save_calibration(
                cit, platform_id, sim_result.answer,
                sim_result.sources, web_hit,
                note=None, matches=is_match,
            )
            calibrated += 1
            if is_match:
                matched += 1

        match_rate = (matched / calibrated * 100) if calibrated > 0 else 0
        return {
            "sampled": len(samples),
            "calibrated": calibrated,
            "matched": matched,
            "match_rate": round(match_rate, 1),
        }

    async def _sample_citation_results(
        self, platform_id: str, sample_rate: float
    ) -> list[CitationResult]:
        """采样待校准的 citation_results。

        1. 查所有 citation_results（排除已校准的）
        2. 按 sample_rate 随机采样，不低于 MIN_SAMPLE_SIZE
        """
        # 查已校准的 citation_result_id
        calibrated_result = await self.db.execute(
            select(CitationCalibration.citation_result_id).where(
                CitationCalibration.platform_id == platform_id
            )
        )
        calibrated_ids = {row[0] for row in calibrated_result.fetchall()}

        # 查所有 citation_results
        all_result = await self.db.execute(
            select(CitationResult).order_by(CitationResult.checked_at.desc())
        )
        all_citations = all_result.scalars().all()

        # 排除已校准的
        candidates = [c for c in all_citations if c.id not in calibrated_ids]
        if not candidates:
            return []

        # 采样
        sample_size = max(int(len(candidates) * sample_rate), MIN_SAMPLE_SIZE)
        sample_size = min(sample_size, len(candidates))
        return random.sample(candidates, sample_size)

    async def _save_calibration(
        self, cit: CitationResult, platform_id: str,
        web_answer: str, web_sources: list, web_hit_type: str,
        note: Optional[str], matches: bool,
    ) -> None:
        """保存校准结果。"""
        calibration = CitationCalibration(
            citation_result_id=cit.id,
            platform_id=platform_id,
            web_answer=web_answer,
            web_sources=web_sources,
            web_hit_type=web_hit_type,
            api_hit_type=cit.hit_type,
            matches=matches,
            note=note,
        )
        self.db.add(calibration)
        await self.db.commit()

    async def get_platform_confidence(self, model: str) -> dict:
        """获取某平台的置信度。

        model 参数对应 citation_results.model 字段。
        注意：校准平台的 platform_id（如 yuanbao）可能与 citation_results.model
        不同。此处按 citation_calibrations.platform_id 查询。
        """
        result = await self.db.execute(
            select(
                func.count(CitationCalibration.id).label("total"),
                func.count(CitationCalibration.id).filter(
                    CitationCalibration.matches.is_(True)
                ).label("matched"),
            ).where(CitationCalibration.platform_id == model)
        )
        row = result.one()
        total = row.total or 0
        matched = row.matched or 0

        if total == 0:
            return {
                "model": model,
                "confidence": -1,
                "level": "uncalibrated",
                "total_calibrations": 0,
                "matched": 0,
            }

        confidence = round(matched / total * 100)
        return {
            "model": model,
            "confidence": confidence,
            "level": get_confidence_level(confidence),
            "total_calibrations": total,
            "matched": matched,
        }

    async def get_all_confidence(self) -> list[dict]:
        """获取所有有校准数据的平台置信度列表。"""
        result = await self.db.execute(
            select(CitationCalibration.platform_id).distinct()
        )
        platforms = [row[0] for row in result.fetchall()]
        return [await self.get_platform_confidence(p) for p in platforms]

    async def get_result_confidence(
        self, citation_result_id: UUID, hit_type: str
    ) -> dict:
        """获取单条引用检测结果的置信度。

        基于该条所属平台的置信度 × 命中类型权重。
        """
        # 先查该条结果所属的 model
        cit_result = await self.db.execute(
            select(CitationResult.model).where(CitationResult.id == citation_result_id)
        )
        row = cit_result.first()
        if row is None:
            return {"confidence": -1, "level": "uncalibrated"}

        platform_conf = await self.get_platform_confidence(row[0])

        # 命中类型权重
        if hit_type == "exact":
            weight = 1.0
        elif hit_type == "domain":
            weight = 0.8
        else:
            return {"confidence": -1, "level": "uncalibrated"}

        if platform_conf["confidence"] < 0:
            return {"confidence": -1, "level": "uncalibrated"}

        adjusted = round(platform_conf["confidence"] * weight)
        return {
            "confidence": adjusted,
            "level": get_confidence_level(adjusted),
        }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_calibration_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/services/calibration_service.py tests/unit/test_calibration_service.py
git commit -m "feat(stage4): 新增 CalibrationService 校准服务（采样+对比+置信度计算）"
```

---

## 任务 3：新增管理端校准 API

**文件：**
- 修改：`app/api/admin_routes.py`（在文件末尾追加）
- 测试：`tests/unit/test_calibration_api.py`

- [ ] **步骤 1：编写 API 测试**

```python
# tests/unit/test_calibration_api.py
"""校准 API 端点测试。"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """Override get_db 依赖。"""
    from app.main import app
    from app.core.database import get_db

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool
    from app.core.config import settings as s

    url = (
        f"postgresql+asyncpg://{s.POSTGRES_USER}:{s.POSTGRES_PASSWORD}"
        f"@{s.POSTGRES_HOST}:{s.POSTGRES_PORT}/{s.POSTGRES_DB}"
    )
    engine = create_async_engine(url, poolclass=NullPool)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


def _admin_token():
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@pytest.mark.asyncio
async def test_trigger_calibration(client):
    """POST /admin/calibration/trigger 触发校准。"""
    token = _admin_token()
    with patch(
        "app.services.calibration_service.CalibrationService.run_calibration",
        AsyncMock(return_value={"yuanbao": {"sampled": 5, "calibrated": 5, "matched": 4, "match_rate": 80.0}}),
    ):
        resp = await client.post(
            "/api/v1/admin/calibration/trigger",
            headers={"Authorization": f"Bearer {token}"},
            params={"sample_rate": 0.1},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "yuanbao" in data
    assert data["yuanbao"]["sampled"] == 5


@pytest.mark.asyncio
async def test_get_calibration_results(client):
    """GET /admin/calibration/results 查看校准结果。"""
    token = _admin_token()
    with patch(
        "app.services.calibration_service.CalibrationService.get_all_confidence",
        AsyncMock(return_value=[{"model": "yuanbao", "confidence": 80, "level": "high", "total_calibrations": 10, "matched": 8}]),
    ):
        resp = await client.get(
            "/api/v1/admin/calibration/results",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "platforms" in data
    assert len(data["platforms"]) == 1
    assert data["platforms"][0]["level"] == "high"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_calibration_api.py -v`
预期：FAIL，404 或路由不存在

- [ ] **步骤 3：在 admin_routes.py 末尾追加校准端点**

在 `app/api/admin_routes.py` 文件末尾追加：

```python
# ============================================================================
# 阶段 4：引用检测校准 API
# ============================================================================

@router.post("/calibration/trigger")
async def trigger_calibration(
    sample_rate: float = 0.1,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """手动触发引用检测校准任务。

    采样 citation_results，用网页端模拟重新检测，对比 API vs 网页端结果。
    返回各平台的采样数、校准数、一致数、一致率。
    """
    from app.services.calibration_service import CalibrationService

    if not 0 < sample_rate <= 1.0:
        raise HTTPException(status_code=400, detail="sample_rate 必须在 (0, 1] 范围内")

    service = CalibrationService(db)
    result = await service.run_calibration(sample_rate=sample_rate)
    return result


@router.get("/calibration/results")
async def get_calibration_results(
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """查看校准结果概览（各平台置信度）。"""
    from app.services.calibration_service import CalibrationService

    service = CalibrationService(db)
    platforms = await service.get_all_confidence()
    return {"platforms": platforms}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_calibration_api.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/api/admin_routes.py tests/unit/test_calibration_api.py
git commit -m "feat(stage4): 新增管理端校准 API（触发校准+查看结果）"
```

---

## 任务 4：新增客户端置信度 API + 增强 rankings/visibility

**文件：**
- 修改：`app/api/client_routes.py`

- [ ] **步骤 1：在 client_routes.py 新增置信度端点**

在 `app/api/client_routes.py` 文件中 `client_visibility` 函数之后追加：

```python
@router.get("/client/confidence")
async def client_confidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """客户查看各平台置信度。

    返回各平台的置信度分数和分级，以及综合置信度。
    置信度基于网页端校准数据——校准数据越多，置信度越可靠。
    """
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    from app.services.calibration_service import CalibrationService

    service = CalibrationService(db)
    platforms = await service.get_all_confidence()

    # 综合置信度：有校准数据的平台的加权平均（按校准数量加权）
    calibrated_platforms = [p for p in platforms if p["total_calibrations"] > 0]
    if calibrated_platforms:
        total_weight = sum(p["total_calibrations"] for p in calibrated_platforms)
        weighted_sum = sum(p["confidence"] * p["total_calibrations"] for p in calibrated_platforms)
        overall_confidence = round(weighted_sum / total_weight) if total_weight > 0 else -1
    else:
        overall_confidence = -1

    return {
        "platforms": platforms,
        "overall_confidence": overall_confidence,
    }
```

- [ ] **步骤 2：增强 client_rankings——每条 result 增加 confidence 字段**

在 `client_rankings` 函数中，组装 results 时增加置信度查询。修改 results 列表推导：

找到 `client_rankings` 函数中的 results 组装部分（约 L427-437），替换为：

```python
    # 3. 批量获取置信度（按 model 分组，避免 N+1 查询）
    from app.services.calibration_service import CalibrationService
    cal_service = CalibrationService(db)
    all_confidence = await cal_service.get_all_confidence()
    confidence_by_model = {c["model"]: c for c in all_confidence}

    # 4. 组装
    return {
        "questions": [
            {
                "id": str(q.id),
                "question": q.question,
                "results": [
                    {
                        "model": c.model,
                        "hit_type": c.hit_type,
                        "answer": c.answer or "",
                        "sources": c.sources or [],
                        "checked_at": c.checked_at.isoformat() if c.checked_at else None,
                        "article_url": c.url,
                        "confidence": confidence_by_model.get(c.model, {}).get("confidence", -1),
                        "confidence_level": confidence_by_model.get(c.model, {}).get("level", "uncalibrated"),
                    }
                    for c in citations_by_qid.get(str(q.id), [])
                ],
            }
            for q in questions
        ]
    }
```

- [ ] **步骤 3：增强 client_visibility——每个 platform_score 增加 confidence 字段**

在 `client_visibility` 函数中，找到 platform_scores 组装部分（约 L488-498），替换为：

```python
    # 3. 批量获取置信度
    from app.services.calibration_service import CalibrationService
    cal_service = CalibrationService(db)
    all_confidence = await cal_service.get_all_confidence()
    confidence_by_model = {c["model"]: c for c in all_confidence}

    # 4. 计算每个平台得分
    platform_scores = []
    for model, s in stats.items():
        score = (s["cited"] / s["total"] * 100) if s["total"] > 0 else 0
        conf = confidence_by_model.get(model, {})
        platform_scores.append({
            "model": model,
            "score": round(score),
            "total": s["total"],
            "cited": s["cited"],
            "confidence": conf.get("confidence", -1),
            "confidence_level": conf.get("level", "uncalibrated"),
        })
    # 按 score 降序，让前端展示更稳定
    platform_scores.sort(key=lambda x: x["score"], reverse=True)
```

- [ ] **步骤 4：运行现有 client 测试确保不回归**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/test_client_work_report.py -v 2>/dev/null; python -m pytest tests/unit/ -k "client" -v --tb=short 2>&1 | tail -20`
预期：已有测试通过（新字段是追加，不破坏现有断言）

- [ ] **步骤 5：Commit**

```bash
git add app/api/client_routes.py
git commit -m "feat(stage4): 客户端置信度 API + 增强 rankings/visibility 返回置信度字段"
```

---

## 任务 5：前端展示置信度标签

**文件：**
- 修改：`dashboard/src/api/clientView.js`
- 修改：`dashboard/src/views/client/ClientRankings.vue`
- 修改：`dashboard/src/views/client/ClientOverview.vue`

- [ ] **步骤 1：在 clientView.js 新增 confidence API**

在 `dashboard/src/api/clientView.js` 的 `clientViewApi` 对象中追加：

```javascript
  // 阶段 4：置信度
  confidence: () => api.get('/client/confidence'),
```

完整文件应为：

```javascript
import api from './index'

export const clientViewApi = {
  overview: () => api.get('/ai-index/overview'),
  evidence: (params) => api.get('/citations/evidence', { params }),
  stats: () => api.get('/stats'),
  // Phase 2：客户工作报告（发稿量披露）
  workReport: () => api.get('/client/work-report'),
  // Phase 2：回答快照（各平台 AI 回答全文）
  rankings: () => api.get('/client/rankings'),
  // Phase 2：AI 可见度得分
  visibility: () => api.get('/client/visibility'),
  // 阶段 4：置信度
  confidence: () => api.get('/client/confidence'),
}
```

- [ ] **步骤 2：在 ClientRankings.vue 展示置信度标签**

在 `dashboard/src/views/client/ClientRankings.vue` 的回答卡片头部，增加置信度标签。找到 card-header 区域，在 hit_type 标签后追加置信度标签：

```vue
<div class="card-header">
  <div class="model-name">{{ result.model }}</div>
  <el-tag :type="getHitTypeTagType(result.hit_type)">{{ result.hit_type }}</el-tag>
  <!-- 阶段 4：置信度标签 -->
  <el-tag
    v-if="result.confidence_level && result.confidence_level !== 'uncalibrated'"
    :type="getConfidenceTagType(result.confidence_level)"
    size="small"
  >
    {{ getConfidenceLabel(result.confidence_level, result.confidence) }}
  </el-tag>
  <el-tag
    v-else-if="result.confidence_level === 'uncalibrated'"
    type="info"
    size="small"
  >
    未校准
  </el-tag>
  <div class="checked-at">{{ result.checked_at }}</div>
</div>
```

在 `<script setup>` 中追加置信度辅助函数：

```javascript
const getConfidenceTagType = (level) => {
  switch (level) {
    case 'high': return 'success'
    case 'medium': return 'warning'
    case 'low': return 'danger'
    default: return 'info'
  }
}

const getConfidenceLabel = (level, confidence) => {
  const levelText = { high: '高置信度', medium: '中置信度', low: '低置信度' }
  return `${levelText[level] || ''} ${confidence}%`
}
```

- [ ] **步骤 3：在 ClientOverview.vue 可见度卡片展示置信度**

在 `dashboard/src/views/client/ClientOverview.vue` 的 AI 可见度得分卡片中，platform_scores 列表项增加置信度标签。

找到平台得分列表区域，在每个平台得分旁追加置信度标签：

```vue
<div v-for="p in visibility.platform_scores" :key="p.model" class="platform-score-item">
  <span class="platform-name">{{ p.model }}</span>
  <span class="platform-score">{{ p.score }}分</span>
  <!-- 阶段 4：置信度标签 -->
  <el-tag
    v-if="p.confidence_level && p.confidence_level !== 'uncalibrated'"
    :type="getConfidenceTagType(p.confidence_level)"
    size="small"
  >
    {{ p.confidence }}%
  </el-tag>
  <el-tag v-else type="info" size="small">未校准</el-tag>
</div>
```

在 `<script setup>` 中追加：

```javascript
const getConfidenceTagType = (level) => {
  switch (level) {
    case 'high': return 'success'
    case 'medium': return 'warning'
    case 'low': return 'danger'
    default: return 'info'
  }
}
```

- [ ] **步骤 4：前端构建验证**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/dashboard" && npm run build 2>&1 | tail -10`
预期：构建成功，无语法错误

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/api/clientView.js dashboard/src/views/client/ClientRankings.vue dashboard/src/views/client/ClientOverview.vue
git commit -m "feat(stage4): 前端展示置信度标签（回答快照+可见度页面）"
```

---

## 任务 6：端到端集成验证

**文件：**
- 无新增文件，运行已有测试套件验证不回归

- [ ] **步骤 1：运行全量单元测试**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && python -m pytest tests/unit/ --tb=short -q 2>&1 | tail -10`
预期：所有测试通过（≥357 passed），无新增失败

- [ ] **步骤 2：验证迁移可正常执行**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && source venv/bin/activate && alembic current && alembic upgrade head && alembic current`
预期：迁移到 016_citation_calibrations，无报错

- [ ] **步骤 3：前端构建验证**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/dashboard" && npm run build 2>&1 | tail -10`
预期：构建成功

- [ ] **步骤 4：Commit 验证记录**

```bash
git add -A
git commit -m "test(stage4): 阶段 4 端到端验证通过——校准+置信度链路完整"
```

---

## 自检

### 规格覆盖度

| 规格章节 | 对应任务 | 覆盖 |
|---------|---------|------|
| 5.1 数据模型（CitationCalibration） | 任务 1 | ✅ |
| 5.2 校准服务（CalibrationService） | 任务 2 | ✅ |
| 5.3 采样策略 | 任务 2（_sample_citation_results） | ✅ |
| 5.4 对比逻辑 | 任务 2（compare_hits） | ✅ |
| 5.5 API 端点（管理端） | 任务 3 | ✅ |
| 5.5 API 端点（客户端） | 任务 4 | ✅ |
| 5.6 前端展示 | 任务 5 | ✅ |
| 5.7 错误处理 | 任务 2（各降级逻辑） | ✅ |

### 占位符扫描

- ✅ 无 "TODO"、"待定"、"后续实现"
- ✅ 所有代码块包含完整实现
- ✅ 所有测试包含实际断言

### 类型一致性

- `CitationCalibration` 模型字段在任务 1、2 中一致
- `compare_hits` 函数签名在任务 2 中定义，测试中调用一致
- `get_confidence_level` 函数签名在任务 2 中定义，API 中调用一致
- `CalibrationService.run_calibration` 返回结构在任务 2、3 中一致
- `get_platform_confidence` 返回结构在任务 2、4 中一致
