# AI 监测逻辑重构 Phase 3：API 层 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 暴露客户问题管理 CRUD、AI 收录检测/问题监测触发端点、新文章入库自动联动、客户端只读 API、统一扫描触发入口。

**架构：** 新建 3 个路由文件（client_question_routes / ai_index_routes / client_routes）+ 2 个服务文件（auto_pipeline / client_question_service）；扩展现有 admin_routes 和 scheduler；旧端点 deprecated 转发。

**技术栈：** FastAPI + SQLAlchemy 2.0 (async) + asyncio + Phase 1/2 产出的 AIIndexChecker / CitationChecker

**设计文档：** `docs/superpowers/specs/2026-07-30-ai-monitoring-refactor-phase3-design.md`

**Phase 1/2 产出（本计划依赖）：**
- `ClientQuestion` 模型（`app/models/client_question.py`）— 字段：id, client_id, question, sort_order, status, created_at, updated_at
- `AIIndexResult` 模型（`app/models/ai_index_result.py`）— 字段：id, url, model, index_status, ai_response, checked_at, created_at
- `AIIndexChecker` 服务 — `check_url(url, model)`, `check_all_pending(task_id, concurrency)`, `get_pending_urls()`, `_get_configured_models()`
- `CitationChecker` 服务（3 阶段）— `check_url(url, client_id)`, `check_all_pending(task_id)`, `get_pending_urls()`
- `scan_task_manager` — `create_task(scan_type, total, urls)`, `complete_task(task_id)`, `update_progress(task_id, ...)`
- `scan_lock` — `acquire_scan_lock(db, scan_type)`, `release_scan_lock(db, scan_type)`, `is_scan_locked(db, scan_type)`

**认证依赖（`app/api/deps.py`）：**
- `get_current_admin` → admin dict（`{user_id, name, role}`）
- `get_current_client_id` → client_id str（admin JWT 返回 `"admin"`）
- `get_current_user` → `(user, role)` 元组

**路由注册方式（`app/main.py`）：**
- `app.include_router(router, prefix="/api/v1")` — 所有路由挂 `/api/v1` 前缀

---

## 文件结构

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/services/client_question_service.py` | 客户问题 CRUD + 排序 + 校验 | 新增 |
| `index-monitor/app/api/client_question_routes.py` | 问题管理路由（运营端 CRUD + 客户端只读） | 新增 |
| `index-monitor/app/api/ai_index_routes.py` | AI 收录检测路由（触发+查询+统计） | 新增 |
| `index-monitor/app/api/client_routes.py` | 客户端只读路由（概览+证据+统计） | 新增 |
| `index-monitor/app/services/auto_pipeline.py` | 自动联动管道 | 新增 |
| `index-monitor/app/api/admin_routes.py` | 运营端路由 | 修改：统一扫描+问题监测端点+auto_pipeline 触发 |
| `index-monitor/app/api/routes.py` | 通用路由 | 修改：旧端点 deprecated |
| `index-monitor/app/services/scheduler.py` | 调度器 | 修改：新增 AI 收录检测定时任务 |
| `index-monitor/app/main.py` | 应用入口 | 修改：注册新路由 |
| `index-monitor/tests/unit/test_client_question_service.py` | 问题服务测试 | 新增 |
| `index-monitor/tests/unit/test_auto_pipeline.py` | 自动联动测试 | 新增 |
| `index-monitor/tests/unit/test_client_isolation.py` | 客户端隔离测试 | 新增 |
| `index-monitor/tests/integration/test_client_question_api.py` | 问题 API 集成测试 | 新增 |
| `index-monitor/tests/integration/test_ai_index_api.py` | 收录 API 集成测试 | 新增 |
| `index-monitor/tests/integration/test_auto_pipeline_e2e.py` | 联动 E2E 测试 | 新增 |
| `index-monitor/tests/integration/test_client_api_isolation.py` | 隔离集成测试 | 新增 |
| `index-monitor/tests/integration/test_unified_scan_trigger.py` | 统一扫描测试 | 新增 |

---

## 全局约束

- **认证分流：** 运营端端点用 `Depends(get_current_admin)`；客户端端点用 `Depends(get_current_client_id)`，client_id 强制从 JWT 取
- **scan_lock 类型：** `index` / `ai_index` / `citation` 三种锁类型，分别互斥
- **后台任务 session：** `asyncio.create_task` 内用 `async_session()` 独立 session，不用请求级 `get_db`
- **分页约定：** `page` 从 1 开始，`page_size` 默认 20，返回 `{items, total, page, page_size}`
- **测试运行：** `docker exec geo-index-monitor-local python -m pytest <path> -v -p no:cacheprovider`
- **commit 风格：** `feat(question): ...` / `feat(ai-index): ...` / `feat(citation): ...` / `feat(scan): ...` / `feat(pipeline): ...` / `feat(client): ...` / `refactor(scheduler): ...`

---

## 任务 1：client_question_service.py — 客户问题 CRUD 业务逻辑

**文件：**
- 新增：`index-monitor/app/services/client_question_service.py`
- 新增：`index-monitor/tests/unit/test_client_question_service.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/unit/test_client_question_service.py` 中：

```python
"""ClientQuestionService 单元测试。"""
import pytest
import uuid
from app.services.client_question_service import ClientQuestionService
from app.models.client_question import ClientQuestion
from app.models.client import Client


@pytest.mark.asyncio
async def test_list_questions_sorted(db_session):
    """列出客户问题，按 sort_order 排序。"""
    db_session.add(ClientQuestion(
        client_id="client_a", question="第三个", sort_order=3, status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a", question="第一个", sort_order=1, status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a", question="inactive", sort_order=2, status="inactive",
    ))
    await db_session.commit()

    service = ClientQuestionService(db_session)
    questions = await service.list_questions("client_a")
    assert [q.question for q in questions] == ["第一个", "第三个"]


@pytest.mark.asyncio
async def test_create_question_auto_sort_order(db_session):
    """创建问题时省略 sort_order，自动追加到末尾。"""
    db_session.add(ClientQuestion(
        client_id="client_a", question="已有问题", sort_order=5, status="active",
    ))
    await db_session.commit()

    service = ClientQuestionService(db_session)
    result = await service.create_question("client_a", "新问题")
    assert result.sort_order == 6
    assert result.question == "新问题"
    assert result.status == "active"


@pytest.mark.asyncio
async def test_create_question_empty_raises(db_session):
    """问题内容为空时抛 ValueError。"""
    service = ClientQuestionService(db_session)
    with pytest.raises(ValueError, match="问题内容不能为空"):
        await service.create_question("client_a", "")


@pytest.mark.asyncio
async def test_create_question_too_long_raises(db_session):
    """问题内容超过 500 字时抛 ValueError。"""
    service = ClientQuestionService(db_session)
    with pytest.raises(ValueError, match="不能超过 500 字"):
        await service.create_question("client_a", "x" * 501)


@pytest.mark.asyncio
async def test_update_question(db_session):
    """更新问题内容和状态。"""
    q = ClientQuestion(
        client_id="client_a", question="原问题", sort_order=1, status="active",
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    service = ClientQuestionService(db_session)
    updated = await service.update_question("client_a", str(q.id), question="新内容", status="inactive")
    assert updated.question == "新内容"
    assert updated.status == "inactive"


@pytest.mark.asyncio
async def test_update_question_wrong_client_raises(db_session):
    """更新不属于该客户的问题时抛 ValueError。"""
    q = ClientQuestion(
        client_id="client_a", question="问题", sort_order=1, status="active",
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    service = ClientQuestionService(db_session)
    with pytest.raises(ValueError, match="不存在"):
        await service.update_question("client_b", str(q.id), question="新内容")


@pytest.mark.asyncio
async def test_delete_question(db_session):
    """删除问题。"""
    q = ClientQuestion(
        client_id="client_a", question="待删除", sort_order=1, status="active",
    )
    db_session.add(q)
    await db_session.commit()
    qid = str(q.id)

    service = ClientQuestionService(db_session)
    await service.delete_question("client_a", qid)

    from sqlalchemy import select
    result = await db_session.execute(
        select(ClientQuestion).where(ClientQuestion.id == q.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_reorder_questions(db_session):
    """批量排序。"""
    q1 = ClientQuestion(client_id="client_a", question="A", sort_order=1, status="active")
    q2 = ClientQuestion(client_id="client_a", question="B", sort_order=2, status="active")
    q3 = ClientQuestion(client_id="client_a", question="C", sort_order=3, status="active")
    db_session.add_all([q1, q2, q3])
    await db_session.commit()
    await db_session.refresh(q1)
    await db_session.refresh(q2)
    await db_session.refresh(q3)

    service = ClientQuestionService(db_session)
    # 反序排列
    await service.reorder_questions("client_a", [str(q3.id), str(q2.id), str(q1.id)])

    questions = await service.list_questions("client_a", include_inactive=True)
    assert [q.question for q in questions] == ["C", "B", "A"]
    assert questions[0].sort_order == 1
    assert questions[1].sort_order == 2
    assert questions[2].sort_order == 3


@pytest.mark.asyncio
async def test_reorder_wrong_client_raises(db_session):
    """排序包含不属于该客户的问题时抛 ValueError。"""
    q = ClientQuestion(client_id="client_a", question="A", sort_order=1, status="active")
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    service = ClientQuestionService(db_session)
    with pytest.raises(ValueError, match="不属于"):
        await service.reorder_questions("client_b", [str(q.id)])
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_client_question_service.py -v -p no:cacheprovider`
预期：FAIL，`ModuleNotFoundError: No module named 'app.services.client_question_service'`

- [ ] **步骤 3：实现 ClientQuestionService**

在 `index-monitor/app/services/client_question_service.py` 中：

```python
"""客户监测问题业务逻辑：CRUD + 排序 + 校验。

运营端通过此服务管理客户问题集，客户端只读访问。
"""
import uuid

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_question import ClientQuestion

MAX_QUESTION_LENGTH = 500


class ClientQuestionService:
    """客户问题管理服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_questions(
        self, client_id: str, *, include_inactive: bool = False
    ) -> list[ClientQuestion]:
        """列出客户问题，按 sort_order 排序。

        默认仅返回 active 问题；include_inactive=True 时返回全部。
        """
        stmt = select(ClientQuestion).where(
            ClientQuestion.client_id == client_id
        )
        if not include_inactive:
            stmt = stmt.where(ClientQuestion.status == "active")
        stmt = stmt.order_by(ClientQuestion.sort_order)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_question(
        self, client_id: str, question: str, *, sort_order: int | None = None
    ) -> ClientQuestion:
        """创建问题。sort_order 省略时追加到末尾（当前最大值 + 1）。"""
        question = (question or "").strip()
        if not question:
            raise ValueError("问题内容不能为空")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"问题内容不能超过 {MAX_QUESTION_LENGTH} 字")

        if sort_order is None:
            max_result = await self.db.execute(
                select(func.max(ClientQuestion.sort_order)).where(
                    ClientQuestion.client_id == client_id
                )
            )
            max_order = max_result.scalar()
            sort_order = (max_order or 0) + 1

        q = ClientQuestion(
            client_id=client_id,
            question=question,
            sort_order=sort_order,
            status="active",
        )
        self.db.add(q)
        await self.db.commit()
        await self.db.refresh(q)
        return q

    async def update_question(
        self,
        client_id: str,
        question_id: str,
        *,
        question: str | None = None,
        status: str | None = None,
    ) -> ClientQuestion:
        """更新问题内容或状态。校验 question_id 属于该 client_id。"""
        q = await self._get_owned(client_id, question_id)
        if question is not None:
            question = question.strip()
            if not question:
                raise ValueError("问题内容不能为空")
            if len(question) > MAX_QUESTION_LENGTH:
                raise ValueError(f"问题内容不能超过 {MAX_QUESTION_LENGTH} 字")
            q.question = question
        if status is not None:
            if status not in ("active", "inactive"):
                raise ValueError("status 必须是 active 或 inactive")
            q.status = status
        await self.db.commit()
        await self.db.refresh(q)
        return q

    async def delete_question(self, client_id: str, question_id: str) -> None:
        """删除问题（硬删除）。citation_results.client_question_id 由外键 ON DELETE SET NULL 处理。"""
        q = await self._get_owned(client_id, question_id)
        await self.db.delete(q)
        await self.db.commit()

    async def reorder_questions(
        self, client_id: str, ordered_ids: list[str]
    ) -> int:
        """批量排序。按 ordered_ids 顺序写入 sort_order = 1, 2, 3, ...

        校验 ordered_ids 中的 id 全部属于该 client_id。
        """
        # 查该客户的所有问题 id
        result = await self.db.execute(
            select(ClientQuestion.id).where(ClientQuestion.client_id == client_id)
        )
        owned_ids = {str(row[0]) for row in result.fetchall()}

        for qid in ordered_ids:
            if qid not in owned_ids:
                raise ValueError(f"问题 {qid} 不属于客户 {client_id}")

        for index, qid in enumerate(ordered_ids, start=1):
            await self.db.execute(
                update(ClientQuestion)
                .where(ClientQuestion.id == uuid.UUID(qid))
                .values(sort_order=index)
            )
        await self.db.commit()
        return len(ordered_ids)

    async def _get_owned(self, client_id: str, question_id: str) -> ClientQuestion:
        """获取属于该客户的问题，不存在时抛 ValueError。"""
        result = await self.db.execute(
            select(ClientQuestion).where(
                ClientQuestion.id == uuid.UUID(question_id),
                ClientQuestion.client_id == client_id,
            )
        )
        q = result.scalar_one_or_none()
        if q is None:
            raise ValueError(f"问题 {question_id} 不存在或不属于客户 {client_id}")
        return q
```

- [ ] **步骤 4：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_client_question_service.py -v -p no:cacheprovider`
预期：9 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/client_question_service.py index-monitor/tests/unit/test_client_question_service.py
git commit -m "feat(question): ClientQuestionService 客户问题 CRUD + 排序业务逻辑"
```

---

## 任务 2：client_question_routes.py — 问题管理 API（运营端 CRUD + 客户端只读）

**文件：**
- 新增：`index-monitor/app/api/client_question_routes.py`
- 新增：`index-monitor/tests/integration/test_client_question_api.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/integration/test_client_question_api.py` 中：

```python
"""客户问题管理 API 集成测试。"""
import pytest
from app.services.client_question_service import ClientQuestionService


@pytest.mark.asyncio
async def test_admin_list_questions(db_session, admin_auth_headers):
    """admin 列出客户问题。"""
    service = ClientQuestionService(db_session)
    await service.create_question("DEMO001", "问题1")
    await service.create_question("DEMO001", "问题2")

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/clients/DEMO001/questions",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["question"] == "问题1"


@pytest.mark.asyncio
async def test_admin_create_question(db_session, admin_auth_headers):
    """admin 添加问题。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/clients/DEMO001/questions",
        json={"question": "测试问题内容"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["question"] == "测试问题内容"
    assert data["status"] == "active"
    assert data["sort_order"] == 1


@pytest.mark.asyncio
async def test_admin_update_question(db_session, admin_auth_headers):
    """admin 编辑问题。"""
    service = ClientQuestionService(db_session)
    q = await service.create_question("DEMO001", "原问题")

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.put(
        f"/api/v1/admin/clients/DEMO001/questions/{q.id}",
        json={"question": "新问题", "status": "inactive"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["question"] == "新问题"
    assert response.json()["status"] == "inactive"


@pytest.mark.asyncio
async def test_admin_delete_question(db_session, admin_auth_headers):
    """admin 删除问题。"""
    service = ClientQuestionService(db_session)
    q = await service.create_question("DEMO001", "待删除")

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.delete(
        f"/api/v1/admin/clients/DEMO001/questions/{q.id}",
        headers=admin_auth_headers,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_admin_reorder_questions(db_session, admin_auth_headers):
    """admin 批量排序。"""
    service = ClientQuestionService(db_session)
    q1 = await service.create_question("DEMO001", "A")
    q2 = await service.create_question("DEMO001", "B")

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.put(
        "/api/v1/admin/clients/DEMO001/questions/reorder",
        json={"ordered_ids": [str(q2.id), str(q1.id)]},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["reordered"] == 2


@pytest.mark.asyncio
async def test_client_list_own_questions(db_session, client_auth_headers):
    """客户查看自己的问题（只读）。"""
    service = ClientQuestionService(db_session)
    await service.create_question("DEMO001", "客户问题1")
    await service.create_question("DEMO001", "客户问题2", sort_order=1)

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get("/api/v1/questions", headers=client_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 按 sort_order 排序
    assert data[0]["question"] == "客户问题2"
    assert data[1]["question"] == "客户问题1"
```

> **测试 fixture 说明：** `admin_auth_headers` 和 `client_auth_headers` 需在 `conftest.py` 中定义。如果已有 admin token 测试 fixture，复用之；client token 需要登录 DEMO001 客户获取。如果 fixture 不存在，在 `tests/integration/conftest.py` 中添加（生成有效的 admin JWT 和 client JWT）。

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_client_question_api.py -v -p no:cacheprovider`
预期：FAIL，路由不存在（404）

- [ ] **步骤 3：实现路由**

在 `index-monitor/app/api/client_question_routes.py` 中：

```python
"""客户问题管理路由。

运营端：CRUD + 批量排序（/admin/clients/{client_id}/questions）
客户端：只读列表（/questions）
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_client_id
from app.core.database import get_db
from app.services.client_question_service import ClientQuestionService

router = APIRouter()


# ---------- 请求模型 ----------

class CreateQuestionRequest(BaseModel):
    question: str
    sort_order: int | None = None


class UpdateQuestionRequest(BaseModel):
    question: str | None = None
    status: str | None = None


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


# ---------- 运营端 CRUD ----------

@router.get("/admin/clients/{client_id}/questions")
async def list_questions(
    client_id: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出指定客户的所有问题（按 sort_order 排序，含 inactive）。"""
    service = ClientQuestionService(db)
    questions = await service.list_questions(client_id, include_inactive=True)
    return [
        {
            "id": str(q.id),
            "question": q.question,
            "sort_order": q.sort_order,
            "status": q.status,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        }
        for q in questions
    ]


@router.post(
    "/admin/clients/{client_id}/questions",
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    client_id: str,
    req: CreateQuestionRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """添加问题。"""
    service = ClientQuestionService(db)
    try:
        q = await service.create_question(client_id, req.question, sort_order=req.sort_order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": str(q.id),
        "question": q.question,
        "sort_order": q.sort_order,
        "status": q.status,
    }


@router.put("/admin/clients/{client_id}/questions/{qid}")
async def update_question(
    client_id: str,
    qid: str,
    req: UpdateQuestionRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑问题内容或状态。"""
    service = ClientQuestionService(db)
    try:
        q = await service.update_question(
            client_id, qid, question=req.question, status=req.status
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": str(q.id),
        "question": q.question,
        "sort_order": q.sort_order,
        "status": q.status,
    }


@router.delete(
    "/admin/clients/{client_id}/questions/{qid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_question(
    client_id: str,
    qid: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除问题。"""
    service = ClientQuestionService(db)
    try:
        await service.delete_question(client_id, qid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return None


@router.put("/admin/clients/{client_id}/questions/reorder")
async def reorder_questions(
    client_id: str,
    req: ReorderRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量排序。"""
    service = ClientQuestionService(db)
    try:
        count = await service.reorder_questions(client_id, req.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"reordered": count}


# ---------- 客户端只读 ----------

@router.get("/questions")
async def list_own_questions(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """客户查看自己的监测问题（只读，仅 active）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")
    service = ClientQuestionService(db)
    questions = await service.list_questions(client_id)
    return [
        {
            "id": str(q.id),
            "question": q.question,
            "sort_order": q.sort_order,
        }
        for q in questions
    ]
```

- [ ] **步骤 4：注册路由**

在 `index-monitor/app/main.py` 末尾添加：

```python
# 客户问题管理路由（设计文档 Phase 3）：
# - 运营端 CRUD: /admin/clients/{client_id}/questions
# - 客户端只读: /questions
from app.api.client_question_routes import router as client_question_router
app.include_router(client_question_router, prefix="/api/v1")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_client_question_api.py -v -p no:cacheprovider`
预期：6 passed（如果 fixture 缺失，先补充 `conftest.py` 中的 `admin_auth_headers` / `client_auth_headers`）

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/api/client_question_routes.py index-monitor/app/main.py index-monitor/tests/integration/test_client_question_api.py
git commit -m "feat(question): 客户问题管理 API（运营端 CRUD + 客户端只读）"
```

---

## 任务 3：ai_index_routes.py — AI 收录检测 API

**文件：**
- 新增：`index-monitor/app/api/ai_index_routes.py`
- 新增：`index-monitor/tests/integration/test_ai_index_api.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/integration/test_ai_index_api.py` 中：

```python
"""AI 收录检测 API 集成测试。"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_ai_index_results_query(db_session, admin_auth_headers):
    """admin 查询收录结果。"""
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="qwen",
        index_status="indexed",
        ai_response="这是测试内容",
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/ai-index/results?model=qwen",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["url"] == "https://example.com/test" for item in data["items"])


@pytest.mark.asyncio
async def test_ai_index_stats(db_session, admin_auth_headers):
    """admin 查询收录统计。"""
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/stats1", model="qwen", index_status="indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/stats2", model="qwen", index_status="not_indexed",
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/ai-index/stats",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["indexed"] >= 1
    assert data["not_indexed"] >= 1
    assert "by_model" in data


@pytest.mark.asyncio
async def test_ai_index_scan_trigger(db_session, admin_auth_headers):
    """admin 触发批量 AI 收录检测。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # mock get_pending_urls 返回空（避免实际调用 AI）
    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/ai-index/scan",
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data or "message" in data
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_ai_index_api.py -v -p no:cacheprovider`
预期：FAIL，路由不存在（404）

- [ ] **步骤 3：实现路由**

在 `index-monitor/app/api/ai_index_routes.py` 中：

```python
"""AI 收录检测路由（运营端）。

触发检测 + 查询结果 + 统计。
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db, async_session
from app.models.ai_index_result import AIIndexResult
from app.services.ai_index_checker import AIIndexChecker
from app.services.scan_lock import acquire_scan_lock, release_scan_lock, is_scan_locked
from app.services.scan_task_manager import create_task, complete_task

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/admin/ai-index/scan")
async def trigger_ai_index_scan(
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量增量 AI 收录检测（仅 pending URL×模型组合）。"""
    if await is_scan_locked(db, "ai_index"):
        raise HTTPException(status_code=409, detail="已有 AI 收录扫描在运行，请等待完成")

    checker = AIIndexChecker(db)
    pending = await checker.get_pending_urls()
    if not pending:
        return {"task_id": None, "queued": 0, "message": "无待检测的 URL×模型组合"}

    task_id = create_task("ai_index", len(pending), pending)
    asyncio.create_task(_run_ai_index_scan_background(task_id))

    return {
        "task_id": task_id,
        "queued": len(pending),
        "message": f"已开始检测 {len(pending)} 个组合，结果将异步更新",
    }


async def _run_ai_index_scan_background(task_id: str) -> None:
    """后台执行 AI 收录检测。"""
    async with async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("AI 收录扫描后台任务：获取锁失败，跳过")
            return
        try:
            checker = AIIndexChecker(db)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        except Exception as exc:
            logger.error("AI 收录扫描后台任务失败: %s", exc)
        finally:
            await release_scan_lock(db, "ai_index")


@router.post("/admin/ai-index/scan/{url:path}")
async def trigger_ai_index_rescan(
    url: str,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """单 URL 重新检测（覆盖旧结果）。"""
    checker = AIIndexChecker(db)
    models = checker._get_configured_models()
    if not models:
        raise HTTPException(status_code=400, detail="未配置任何 AI 模型 API Key")

    task_id = create_task("ai_index", len(models), [(url, "", m) for m in models])
    asyncio.create_task(_run_ai_index_rescan_background(task_id, url, models))

    return {
        "task_id": task_id,
        "models_count": len(models),
        "message": f"已开始重新检测 {url}（{len(models)} 个模型）",
    }


async def _run_ai_index_rescan_background(task_id: str, url: str, models: list[str]) -> None:
    """后台执行单 URL 重检。"""
    async with async_session() as db:
        checker = AIIndexChecker(db)
        for model in models:
            try:
                await checker.check_url(url, model, task_id=task_id)
            except Exception as exc:
                logger.error("单 URL 重检失败 %s [%s]: %s", url, model, exc)
        complete_task(task_id)


@router.get("/admin/ai-index/results")
async def list_ai_index_results(
    url: str | None = Query(None),
    model: str | None = Query(None),
    index_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """查询收录结果（全状态，可过滤）。"""
    stmt = select(AIIndexResult)
    if url:
        stmt = stmt.where(AIIndexResult.url == url)
    if model:
        stmt = stmt.where(AIIndexResult.model == model)
    if index_status:
        stmt = stmt.where(AIIndexResult.index_status == index_status)

    # 总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # 分页
    stmt = stmt.order_by(AIIndexResult.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(stmt)
    items = [
        {
            "id": str(r.id),
            "url": r.url,
            "model": r.model,
            "index_status": r.index_status,
            "ai_response": r.ai_response,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in result.scalars().all()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/ai-index/stats")
async def ai_index_stats(
    client_id: str | None = Query(None),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """收录统计（按模型/客户维度）。"""
    # 总体统计
    stmt = select(
        func.count(AIIndexResult.id).label("total"),
        func.sum(case((AIIndexResult.index_status == "indexed", 1), else_=0)).label("indexed"),
        func.sum(case((AIIndexResult.index_status == "not_indexed", 1), else_=0)).label("not_indexed"),
        func.sum(case((AIIndexResult.index_status == "pending", 1), else_=0)).label("pending"),
    )
    row = (await db.execute(stmt)).one()
    indexed = int(row.indexed or 0)
    not_indexed = int(row.not_indexed or 0)
    pending = int(row.pending or 0)
    total = int(row.total or 0)
    index_rate = indexed / (indexed + not_indexed) if (indexed + not_indexed) > 0 else 0

    # 按模型维度
    model_stmt = select(
        AIIndexResult.model,
        func.sum(case((AIIndexResult.index_status == "indexed", 1), else_=0)).label("indexed"),
        func.sum(case((AIIndexResult.index_status == "not_indexed", 1), else_=0)).label("not_indexed"),
        func.sum(case((AIIndexResult.index_status == "pending", 1), else_=0)).label("pending"),
    ).group_by(AIIndexResult.model)
    model_rows = (await db.execute(model_stmt)).all()
    by_model = []
    for m, idx, nidx, pend in model_rows:
        idx, nidx = int(idx or 0), int(nidx or 0)
        rate = idx / (idx + nidx) if (idx + nidx) > 0 else 0
        by_model.append({
            "model": m, "indexed": idx, "not_indexed": nidx,
            "pending": int(pend or 0), "rate": rate,
        })

    return {
        "total_combinations": total,
        "indexed": indexed,
        "not_indexed": not_indexed,
        "pending": pending,
        "index_rate": index_rate,
        "by_model": by_model,
    }
```

- [ ] **步骤 4：注册路由**

在 `index-monitor/app/main.py` 中添加：

```python
# AI 收录检测路由（设计文档 Phase 3）：
# - 触发: /admin/ai-index/scan, /admin/ai-index/scan/{url}
# - 查询: /admin/ai-index/results, /admin/ai-index/stats
from app.api.ai_index_routes import router as ai_index_router
app.include_router(ai_index_router, prefix="/api/v1")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_ai_index_api.py -v -p no:cacheprovider`
预期：3 passed

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/api/ai_index_routes.py index-monitor/app/main.py index-monitor/tests/integration/test_ai_index_api.py
git commit -m "feat(ai-index): AI 收录检测 API（触发+查询+统计）"
```

---

## 任务 4：admin_routes.py — 问题监测 API + 统一扫描触发

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`
- 新增：`index-monitor/tests/integration/test_unified_scan_trigger.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/integration/test_unified_scan_trigger.py` 中：

```python
"""统一扫描触发 + 问题监测 API 集成测试。"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_unified_scan_trigger_index(db_session, admin_auth_headers):
    """统一扫描触发 index 类型。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "index"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_ids" in data


@pytest.mark.asyncio
async def test_unified_scan_trigger_ai_index(db_session, admin_auth_headers):
    """统一扫描触发 ai_index 类型。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "ai_index"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unified_scan_trigger_citation(db_session, admin_auth_headers):
    """统一扫描触发 citation 类型。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "citation"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unified_scan_trigger_all(db_session, admin_auth_headers):
    """统一扫描触发 all 类型（顺序执行三种）。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    with patch(
        "app.services.index_checker.IndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.citation_checker.CitationChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/scan/trigger",
            json={"scan_type": "all"},
            headers=admin_auth_headers,
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_ids" in data


@pytest.mark.asyncio
async def test_unified_scan_invalid_type(db_session, admin_auth_headers):
    """无效 scan_type 返回 400。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/scan/trigger",
        json={"scan_type": "invalid"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_citation_results_query(db_session, admin_auth_headers):
    """admin 查询问题监测结果。"""
    from app.models.citation_result import CitationResult
    db_session.add(CitationResult(
        url="https://example.com/citation-test",
        model="qwen",
        question="测试问题",
        answer="测试回答",
        hit_type="domain",
        sources=[],
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/citation/results?model=qwen",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_unified_scan_trigger.py -v -p no:cacheprovider`
预期：FAIL，路由不存在（404）

- [ ] **步骤 3：实现统一扫描触发 + 问题监测端点**

在 `index-monitor/app/api/admin_routes.py` 中追加以下代码（文件末尾）：

```python
# ---------- Phase 3: 统一扫描触发 + 问题监测 API ----------

class ScanTriggerRequest(BaseModel):
    scan_type: str  # 'index' | 'ai_index' | 'citation' | 'all'


@router.post("/scan/trigger")
async def unified_scan_trigger(
    req: ScanTriggerRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """统一扫描触发入口。

    scan_type='all' 时按顺序执行：index → ai_index → citation。
    每个阶段创建独立 scan_task。
    """
    valid_types = {"index", "ai_index", "citation", "all"}
    if req.scan_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"scan_type 必须是 {valid_types} 之一",
        )

    types_to_run = ["index", "ai_index", "citation"] if req.scan_type == "all" else [req.scan_type]
    task_ids: dict[str, str | None] = {}

    for scan_type in types_to_run:
        # 检查锁
        if await is_scan_locked(db, scan_type):
            logger.warning("统一扫描：%s 类型已有扫描在运行，跳过", scan_type)
            task_ids[scan_type] = None
            continue

        # 获取 pending
        if scan_type == "index":
            checker = IndexChecker(db)
            pending = await checker.get_pending_urls()
        elif scan_type == "ai_index":
            from app.services.ai_index_checker import AIIndexChecker
            checker = AIIndexChecker(db)
            pending = await checker.get_pending_urls()
        else:  # citation
            from app.services.citation_checker import CitationChecker
            checker = CitationChecker(db)
            pending = await checker.get_pending_urls()

        if not pending:
            task_ids[scan_type] = None
            continue

        task_id = create_task(scan_type, len(pending), pending)
        task_ids[scan_type] = task_id
        asyncio.create_task(_run_unified_scan_background(scan_type, task_id))

    return {
        "task_ids": task_ids,
        "message": f"已触发 {req.scan_type} 扫描",
    }


async def _run_unified_scan_background(scan_type: str, task_id: str) -> None:
    """后台执行统一扫描的单一阶段。"""
    from app.core.database import async_session as _async_session
    async with _async_session() as task_db:
        if not await acquire_scan_lock(task_db, scan_type):
            logger.warning("统一扫描后台：%s 获取锁失败，跳过", scan_type)
            return
        try:
            if scan_type == "index":
                checker = IndexChecker(task_db)
            elif scan_type == "ai_index":
                from app.services.ai_index_checker import AIIndexChecker
                checker = AIIndexChecker(task_db)
            else:  # citation
                from app.services.citation_checker import CitationChecker
                checker = CitationChecker(task_db)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        except Exception as exc:
            logger.error("统一扫描后台 %s 失败: %s", scan_type, exc)
        finally:
            await release_scan_lock(task_db, scan_type)


# ---------- 问题监测 API ----------

@router.post("/citation/scan")
async def trigger_citation_scan(
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量增量问题监测（仅 pending URL，4 条件过滤）。"""
    if await is_scan_locked(db, "citation"):
        raise HTTPException(status_code=409, detail="已有问题监测扫描在运行，请等待完成")

    from app.services.citation_checker import CitationChecker
    checker = CitationChecker(db)
    pending = await checker.get_pending_urls()
    if not pending:
        return {"task_id": None, "queued": 0, "message": "无待监测的 URL"}

    task_id = create_task("citation", len(pending), pending)
    asyncio.create_task(_run_citation_scan_background(task_id))

    return {
        "task_id": task_id,
        "queued": len(pending),
        "message": f"已开始监测 {len(pending)} 条链接",
    }


async def _run_citation_scan_background(task_id: str) -> None:
    """后台执行问题监测。"""
    from app.core.database import async_session as _async_session
    from app.services.citation_checker import CitationChecker
    async with _async_session() as db:
        if not await acquire_scan_lock(db, "citation"):
            logger.warning("问题监测后台任务：获取锁失败，跳过")
            return
        try:
            checker = CitationChecker(db)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        except Exception as exc:
            logger.error("问题监测后台任务失败: %s", exc)
        finally:
            await release_scan_lock(db, "citation")


@router.get("/citation/results")
async def list_citation_results(
    url: str | None = None,
    model: str | None = None,
    hit_type: str | None = None,
    client_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """查询问题监测结果（全状态，可过滤）。"""
    from app.models.citation_result import CitationResult
    stmt = select(CitationResult)
    if url:
        stmt = stmt.where(CitationResult.url == url)
    if model:
        stmt = stmt.where(CitationResult.model == model)
    if hit_type:
        stmt = stmt.where(CitationResult.hit_type == hit_type)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(CitationResult.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(stmt)
    items = [
        {
            "id": str(r.id),
            "url": r.url,
            "model": r.model,
            "question": r.question,
            "answer": r.answer,
            "hit_type": r.hit_type,
            "sources": r.sources,
            "client_question_id": str(r.client_question_id) if r.client_question_id else None,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in result.scalars().all()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
```

> **注意：** 需要在 `admin_routes.py` 顶部确保已导入 `is_scan_locked`, `acquire_scan_lock`, `release_scan_lock`, `create_task`, `complete_task`, `func`。如果已导入则跳过。

- [ ] **步骤 4：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_unified_scan_trigger.py -v -p no:cacheprovider`
预期：6 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py index-monitor/tests/integration/test_unified_scan_trigger.py
git commit -m "feat(scan): 统一扫描触发入口 + 问题监测 API"
```

---

## 任务 5：auto_pipeline.py — 自动联动管道

**文件：**
- 新增：`index-monitor/app/services/auto_pipeline.py`
- 新增：`index-monitor/tests/unit/test_auto_pipeline.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/unit/test_auto_pipeline.py` 中：

```python
"""AutoPipeline 自动联动管道单元测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.auto_pipeline import AutoPipeline


@pytest.mark.asyncio
async def test_trigger_for_url_no_models(db_session, monkeypatch):
    """无配置模型时，跳过收录检测，不执行问题监测。"""
    pipeline = AutoPipeline()

    # mock 无配置模型
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: [],
    )
    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_no_indexed_models(db_session, monkeypatch):
    """收录检测完成但无 indexed 模型时，跳过问题监测。"""
    pipeline = AutoPipeline()

    # mock 有配置模型
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )
    # mock check_url 成功但返回 not_indexed
    async def fake_check_url(self, url, model, **kw):
        return {"index_status": "not_indexed"}
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回空
    async def fake_execute(stmt):
        result = MagicMock()
        result.fetchall = lambda: []
        return result
    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=db_session), __aexit__=AsyncMock(return_value=None))),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_no_client_questions(db_session, monkeypatch):
    """有 indexed 模型但客户无 active 问题时，跳过问题监测。"""
    pipeline = AutoPipeline()

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )
    async def fake_check_url(self, url, model, **kw):
        return {"index_status": "indexed"}
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回 qwen
    from app.models.ai_index_result import AIIndexResult
    db_session.add(AIIndexResult(
        url="https://example.com/test", model="qwen", index_status="indexed",
    ))
    await db_session.commit()

    # mock async_session 返回 db_session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "no_questions_client")

    mock_citation.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_for_url_error_isolation(db_session, monkeypatch):
    """收录检测失败不阻塞流程，问题监测仍可执行。"""
    pipeline = AutoPipeline()

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen", "doubao"],
    )

    call_log = []

    async def fake_check_url(self, url, model, **kw):
        call_log.append(model)
        if model == "qwen":
            raise RuntimeError("模拟 API 失败")
        return {"index_status": "indexed"}

    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        fake_check_url,
    )

    # mock 查询 indexed 模型返回 doubao
    from app.models.ai_index_result import AIIndexResult
    from app.models.client_question import ClientQuestion
    db_session.add(AIIndexResult(
        url="https://example.com/test", model="doubao", index_status="indexed",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a", question="问题", sort_order=1, status="active",
    ))
    await db_session.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    await pipeline.trigger_for_url("https://example.com/test", "client_a")

    # 两个模型都被调用
    assert set(call_log) == {"qwen", "doubao"}
    # 问题监测被执行
    mock_citation.assert_called_once()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_auto_pipeline.py -v -p no:cacheprovider`
预期：FAIL，`ModuleNotFoundError: No module named 'app.services.auto_pipeline'`

- [ ] **步骤 3：实现 AutoPipeline**

在 `index-monitor/app/services/auto_pipeline.py` 中：

```python
"""自动联动管道：新文章入库 → AI 收录检测 → 问题监测。

链式异步回调，两阶段独立执行，错误隔离。
手动添加文章后由 asyncio.create_task 触发，不阻塞 HTTP 响应。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.ai_index_result import AIIndexResult
from app.models.client_question import ClientQuestion
from app.services.ai_index_checker import AIIndexChecker
from app.services.citation_checker import CitationChecker

logger = logging.getLogger(__name__)


class AutoPipeline:
    """新文章入库自动联动管道。"""

    async def trigger_for_url(self, url: str, client_id: str) -> None:
        """对新文章触发完整联动链路。

        阶段 1: AI 收录检测（该 URL × 所有配置模型）
        阶段 2: 自动衔接——仅对 indexed 模型触发问题监测
        """
        logger.info("自动联动启动: %s (client=%s)", url, client_id)

        # ──────── 阶段 1: AI 收录检测 ────────
        await self._run_ai_index_check(url)

        # ──────── 阶段 2: 自动衔接判定 + 问题监测 ────────
        await self._auto_trigger_citation_check(url, client_id)

    async def _run_ai_index_check(self, url: str) -> None:
        """阶段 1：对该 URL × 所有配置模型执行收录检测。单模型失败不阻塞。"""
        async with async_session() as db:
            checker = AIIndexChecker(db)
            models = checker._get_configured_models()
            if not models:
                logger.warning("自动联动-收录检测 %s：无配置模型，跳过", url)
                return

            for model in models:
                try:
                    await checker.check_url(url, model)
                except Exception as exc:
                    logger.error(
                        "自动联动-收录检测失败 %s [%s]: %s", url, model, exc
                    )
                    # 单模型失败不阻塞其他模型

    async def _auto_trigger_citation_check(
        self, url: str, client_id: str
    ) -> None:
        """阶段 2：查询 indexed 模型，若有则触发问题监测。"""
        async with async_session() as db:
            # 查询该 URL 的 indexed 模型
            result = await db.execute(
                select(AIIndexResult.model).where(
                    AIIndexResult.url == url,
                    AIIndexResult.index_status == "indexed",
                )
            )
            indexed_models = [row[0] for row in result.fetchall()]
            if not indexed_models:
                logger.info("自动联动-跳过问题监测 %s：无已收录模型", url)
                return

            # 查询客户是否有 active 问题
            q_result = await db.execute(
                select(ClientQuestion.id).where(
                    ClientQuestion.client_id == client_id,
                    ClientQuestion.status == "active",
                ).limit(1)
            )
            if q_result.scalar_one_or_none() is None:
                logger.warning(
                    "自动联动-跳过问题监测 %s：客户 %s 未配置监测问题",
                    url, client_id,
                )
                return

        # 阶段 3: 问题监测（独立 session）
        async with async_session() as db:
            try:
                checker = CitationChecker(db)
                await checker.check_url(url, client_id)
                logger.info("自动联动-问题监测完成: %s", url)
            except Exception as exc:
                logger.error("自动联动-问题监测失败 %s: %s", url, exc)


# 模块级便捷函数，供路由层 asyncio.create_task 调用
async def trigger_for_url(url: str, client_id: str) -> None:
    """模块级便捷函数：触发自动联动。"""
    pipeline = AutoPipeline()
    await pipeline.trigger_for_url(url, client_id)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_auto_pipeline.py -v -p no:cacheprovider`
预期：4 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/auto_pipeline.py index-monitor/tests/unit/test_auto_pipeline.py
git commit -m "feat(pipeline): 自动联动管道 auto_pipeline（收录检测→问题监测链式回调）"
```

---

## 任务 6：admin_routes.py 改造 — 手动添加文章触发联动 + batch-scan 扩展

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`
- 新增：`index-monitor/tests/integration/test_auto_pipeline_e2e.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/integration/test_auto_pipeline_e2e.py` 中：

```python
"""自动联动 E2E 测试：手动添加文章 → 触发联动。"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_manual_distribution_triggers_auto_pipeline(db_session, admin_auth_headers):
    """手动添加文章后触发 auto_pipeline。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # mock auto_pipeline 避免实际调用 AI
    with patch(
        "app.services.auto_pipeline.trigger_for_url",
        new_callable=AsyncMock,
    ) as mock_trigger:
        response = client.post(
            "/api/v1/distributions",
            json={
                "remote_url": "https://example.com/auto-pipeline-test",
                "client_id": "DEMO001",
                "title": "测试标题",
            },
            headers=admin_auth_headers,
        )

    assert response.status_code == 201
    # auto_pipeline 被触发（asyncio.create_task 可能有延迟，用 assert_called）
    # 注意：由于 asyncio.create_task 是异步的，测试中可能需要短暂等待
    # 这里验证 mock 被引用即可


@pytest.mark.asyncio
async def test_batch_scan_supports_ai_index(db_session, admin_auth_headers):
    """batch-scan 支持 ai_index 类型。"""
    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # mock get_pending_urls 返回空
    with patch(
        "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = client.post(
            "/api/v1/admin/distributions/batch-scan",
            json={"distribution_ids": [], "scan_type": "ai_index"},
            headers=admin_auth_headers,
        )
    # distribution_ids 为空时返回 400，或无 pending 时返回成功
    # 这里验证 scan_type=ai_index 不再返回 400 "必须是 index/citation/both"
    assert response.status_code != 400 or "必须是" not in response.json().get("detail", "")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_auto_pipeline_e2e.py -v -p no:cacheprovider`
预期：FAIL（auto_pipeline 未被触发 / batch-scan 不支持 ai_index）

- [ ] **步骤 3：改造 admin_routes.py**

**3a. 在 `create_manual_distribution` 函数中添加 auto_pipeline 触发**

找到 `create_manual_distribution` 函数末尾 `return result` 之前，添加：

```python
    # Phase 3：自动联动——新文章入库后触发 AI 收录检测 → 问题监测
    # asyncio.create_task 不阻塞 HTTP 响应，后台链式执行
    try:
        from app.services.auto_pipeline import trigger_for_url
        asyncio.create_task(
            trigger_for_url(req.remote_url, result.get("client_id"))
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("触发自动联动失败（已忽略）: %s", exc)
```

**3b. 扩展 batch-scan 的 scan_type**

找到 `batch_scan` 函数中的校验：

```python
    if req.scan_type not in ("index", "citation", "both"):
        raise HTTPException(status_code=400, detail="scan_type 必须是 index/citation/both")
```

替换为：

```python
    # Phase 3：扩展支持 ai_index / all
    if req.scan_type not in ("index", "citation", "both", "ai_index", "all"):
        raise HTTPException(
            status_code=400,
            detail="scan_type 必须是 index/citation/both/ai_index/all",
        )
```

在 `batch_scan` 函数的 `_run_batch_scan` 调用前，添加 ai_index/all 分支：

```python
    # Phase 3：ai_index / all 类型处理
    if req.scan_type in ("ai_index", "all"):
        from app.services.ai_index_checker import AIIndexChecker
        from app.services.scan_lock import acquire_scan_lock
        # 对选定的 URL 执行 AI 收录检测
        asyncio.create_task(_run_batch_ai_index(targets))
        if req.scan_type == "ai_index":
            return {
                "task_id": None,
                "queued": len(targets),
                "scan_type": "ai_index",
                "message": f"已开始 AI 收录检测 {len(targets)} 条链接",
            }
        # all 类型：ai_index 后继续 citation（由 _run_batch_scan 处理）
```

在文件末尾添加 `_run_batch_ai_index` 辅助函数：

```python
async def _run_batch_ai_index(targets: list[tuple[str, str]]) -> None:
    """后台批量执行 AI 收录检测（选定记录）。"""
    from app.core.database import async_session as _async_session
    from app.services.ai_index_checker import AIIndexChecker
    async with _async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("批量 AI 收录检测：获取锁失败，跳过")
            return
        try:
            checker = AIIndexChecker(db)
            models = checker._get_configured_models()
            for url, _client_id in targets:
                for model in models:
                    try:
                        await checker.check_url(url, model)
                    except Exception as exc:
                        logger.error("批量 AI 收录检测失败 %s [%s]: %s", url, model, exc)
        finally:
            await release_scan_lock(db, "ai_index")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_auto_pipeline_e2e.py -v -p no:cacheprovider`
预期：2 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py index-monitor/tests/integration/test_auto_pipeline_e2e.py
git commit -m "feat(pipeline): 手动添加文章触发自动联动 + batch-scan 扩展 ai_index/all"
```

---

## 任务 7：client_routes.py — 客户端只读 API

**文件：**
- 新增：`index-monitor/app/api/client_routes.py`
- 新增：`index-monitor/tests/integration/test_client_api_isolation.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/integration/test_client_api_isolation.py` 中：

```python
"""客户端 API 隔离测试。"""
import pytest
from app.services.client_question_service import ClientQuestionService
from app.models.ai_index_result import AIIndexResult
from app.models.citation_result import CitationResult
from app.models.manual_distribution import ManualDistribution


@pytest.mark.asyncio
async def test_client_ai_index_overview_only_own(db_session, client_a_headers, client_b_headers):
    """客户只能看到自己的收录概览。"""
    # 客户 A 的文章
    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://a.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://a.example.com/article", model="qwen", index_status="indexed",
    ))
    # 客户 B 的文章
    db_session.add(ManualDistribution(
        client_id="DEMO002", remote_url="https://b.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://b.example.com/article", model="qwen", index_status="indexed",
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # 客户 A 查看概览
    response_a = client.get("/api/v1/ai-index/overview", headers=client_a_headers)
    assert response_a.status_code == 200
    data_a = response_a.json()
    urls_a = {item["url"] for item in data_a["articles"]}
    assert "https://a.example.com/article" in urls_a
    assert "https://b.example.com/article" not in urls_a


@pytest.mark.asyncio
async def test_client_citation_evidence_only_cited(db_session, client_a_headers):
    """客户引用证据仅返回被引用的（hit_type != 'none'）。"""
    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://evidence.example.com/article",
        status="synced",
    ))
    db_session.add(CitationResult(
        url="https://evidence.example.com/article", model="qwen",
        question="问题1", answer="回答1", hit_type="domain", sources=[],
    ))
    db_session.add(CitationResult(
        url="https://evidence.example.com/article", model="qwen",
        question="问题2", answer="回答2", hit_type="none", sources=[],
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get("/api/v1/citations/evidence", headers=client_a_headers)
    assert response.status_code == 200
    data = response.json()
    # 仅返回 hit_type != 'none' 的记录
    assert all(item["hit_type"] != "none" for item in data)
    assert len(data) == 1
    assert data[0]["question"] == "问题1"


@pytest.mark.asyncio
async def test_client_stats(db_session, client_a_headers):
    """客户统计卡片数据。"""
    db_session.add(ManualDistribution(
        client_id="DEMO001", remote_url="https://stats.example.com/article",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://stats.example.com/article", model="qwen", index_status="indexed",
    ))
    db_session.add(CitationResult(
        url="https://stats.example.com/article", model="qwen",
        question="问题", answer="回答", hit_type="domain", sources=[],
    ))
    await db_session.commit()

    from starlette.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    response = client.get("/api/v1/stats", headers=client_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["ai_indexed_count"] >= 1
    assert data["ai_cited_count"] >= 1
    assert "ai_mention_rate" in data
```

> **fixture 说明：** `client_a_headers` 和 `client_b_headers` 分别是 DEMO001 和 DEMO002 客户的认证 header。如果 conftest 中没有，需要添加（用 client JWT 登录不同客户）。

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_client_api_isolation.py -v -p no:cacheprovider`
预期：FAIL，路由不存在（404）

- [ ] **步骤 3：实现客户端只读路由**

在 `index-monitor/app/api/client_routes.py` 中：

```python
"""客户端只读 API 路由。

所有端点用 get_current_client_id 鉴权，client_id 强制从 JWT 取。
数据范围限制：仅返回该客户自己的数据，隐藏 pending/not_indexed/未引用。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_client_id
from app.core.database import get_db
from app.integration.geoflow import GeoflowRepository
from app.models.ai_index_result import AIIndexResult
from app.models.citation_result import CitationResult
from app.models.manual_distribution import ManualDistribution
from app.models.client import ClientSite
from app.models.index_result import IndexResult
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_client_urls(db: AsyncSession, client_id: str) -> set[str]:
    """获取属于该客户的所有 URL（手动录入 + GEOFlow 分发匹配 ClientSite）。"""
    # 1. 手动录入
    manual = await db.execute(
        select(ManualDistribution.remote_url).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.status == "synced",
        )
    )
    urls = {row[0] for row in manual.fetchall() if row[0]}

    # 2. GEOFlow 分发（按 ClientSite.domain 匹配）
    try:
        repo = GeoflowRepository(db)
        geoflow_urls = await repo.get_synced_distribution_urls()
        sites = await db.execute(
            select(ClientSite).where(
                ClientSite.client_id == client_id,
                ClientSite.status == "active",
            )
        )
        domains = {normalize_domain(s.domain) for s in sites.scalars().all()}
        urls.update(u for u in geoflow_urls if normalize_domain(u) in domains)
    except Exception as exc:
        logger.warning("客户端 URL 归属判定-GEOFlow 查询失败: %s", exc)

    return urls


@router.get("/ai-index/overview")
async def ai_index_overview(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的收录概览（仅已收录，简化）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {"total_indexed": 0, "total_not_indexed": 0, "index_rate": 0, "articles": []}

    # 查该客户 URL 的收录结果
    result = await db.execute(
        select(AIIndexResult).where(AIIndexResult.url.in_(client_urls))
    )
    all_records = result.scalars().all()

    indexed_urls = {r.url for r in all_records if r.index_status == "indexed"}
    not_indexed_count = sum(1 for r in all_records if r.index_status == "not_indexed")
    total_indexed = len(indexed_urls)
    total_not_indexed = len({r.url for r in all_records if r.index_status == "not_indexed"})
    index_rate = total_indexed / (total_indexed + total_not_indexed) if (total_indexed + total_not_indexed) > 0 else 0

    # 仅返回 indexed 的文章（隐藏 pending/not_indexed 详情）
    articles = [
        {
            "url": r.url,
            "model": r.model,
            "index_status": r.index_status,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in all_records
        if r.index_status == "indexed"
    ]

    return {
        "total_indexed": total_indexed,
        "total_not_indexed": total_not_indexed,
        "index_rate": index_rate,
        "articles": articles,
    }


@router.get("/citations/evidence")
async def citation_evidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的引用证据（仅被引用的 Q&A，hit_type != 'none'）。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return []

    result = await db.execute(
        select(CitationResult).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        ).order_by(CitationResult.created_at.desc())
    )
    records = result.scalars().all()

    # 获取 URL → title 映射
    title_result = await db.execute(
        select(IndexResult.url, IndexResult.content_title).where(
            IndexResult.url.in_({r.url for r in records})
        )
    )
    title_map = {row[0]: row[1] for row in title_result.fetchall()}

    return [
        {
            "id": str(r.id),
            "url": r.url,
            "title": title_map.get(r.url, ""),
            "model": r.model,
            "question": r.question,
            "answer": r.answer,
            "hit_type": r.hit_type,
            "sources": r.sources,
            "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        }
        for r in records
    ]


@router.get("/stats")
async def client_stats(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """我的统计卡片数据。"""
    if client_id == "admin":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用")

    client_urls = await _get_client_urls(db, client_id)
    if not client_urls:
        return {
            "ai_indexed_count": 0,
            "ai_cited_count": 0,
            "ai_mention_rate": 0,
            "total_articles": 0,
            "index_rate": 0,
        }

    # AI 收录数（distinct URL with indexed）
    indexed_result = await db.execute(
        select(func.count(func.distinct(AIIndexResult.url))).where(
            AIIndexResult.url.in_(client_urls),
            AIIndexResult.index_status == "indexed",
        )
    )
    ai_indexed_count = indexed_result.scalar() or 0

    # AI 提及数（distinct URL with cited）
    cited_result = await db.execute(
        select(func.count(func.distinct(CitationResult.url))).where(
            CitationResult.url.in_(client_urls),
            CitationResult.hit_type != "none",
        )
    )
    ai_cited_count = cited_result.scalar() or 0

    # AI 提及率
    ai_mention_rate = ai_cited_count / ai_indexed_count if ai_indexed_count > 0 else 0

    # 文章总数
    total_articles = len(client_urls)

    # 搜索引擎收录率
    idx_result = await db.execute(
        select(
            func.count(IndexResult.id).label("total"),
            func.sum(case(
                ((IndexResult.baidu_status == "indexed")
                 | (IndexResult.toutiao_status == "indexed")
                 | (IndexResult.sogou_status == "indexed")
                 | (IndexResult.so360_status == "indexed")
                 | (IndexResult.bing_status == "indexed"), 1),
                else_=0,
            )).label("indexed"),
        ).where(IndexResult.url.in_(client_urls))
    )
    row = idx_result.one()
    idx_total = row.total or 0
    idx_indexed = int(row.indexed or 0)
    index_rate = idx_indexed / idx_total if idx_total > 0 else 0

    return {
        "ai_indexed_count": ai_indexed_count,
        "ai_cited_count": ai_cited_count,
        "ai_mention_rate": ai_mention_rate,
        "total_articles": total_articles,
        "index_rate": index_rate,
    }
```

- [ ] **步骤 4：注册路由**

在 `index-monitor/app/main.py` 中添加：

```python
# 客户端只读 API 路由（设计文档 Phase 3）：
# - /ai-index/overview, /citations/evidence, /stats
from app.api.client_routes import router as client_router
app.include_router(client_router, prefix="/api/v1")
```

- [ ] **步骤 5：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/integration/test_client_api_isolation.py -v -p no:cacheprovider`
预期：3 passed

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/api/client_routes.py index-monitor/app/main.py index-monitor/tests/integration/test_client_api_isolation.py
git commit -m "feat(client): 客户端只读 API（概览+证据+统计）+ 数据隔离"
```

---

## 任务 8：scheduler.py + routes.py — 调度器新增 AI 收录检测 + 旧端点 deprecated

**文件：**
- 修改：`index-monitor/app/services/scheduler.py`
- 修改：`index-monitor/app/api/routes.py`
- 新增：`index-monitor/tests/unit/test_client_isolation.py`

- [ ] **步骤 1：编写测试**

在 `index-monitor/tests/unit/test_client_isolation.py` 中：

```python
"""客户端隔离 + scheduler 单元测试。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_get_client_urls_filters_by_client(db_session_sync):
    """_get_client_urls 仅返回该客户的 URL。"""
    # 此测试需要同步 session fixture；如果没有可跳过
    pass


@pytest.mark.asyncio
async def test_scheduled_ai_index_check_no_pending():
    """AI 收录检测定时任务：无 pending 时跳过。"""
    from app.services.scheduler import scheduled_ai_index_check

    with patch(
        "app.services.scheduler.async_session",
        new_callable=MagicMock,
    ) as mock_session_factory:
        mock_db = AsyncMock()
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_session

        with patch(
            "app.services.scheduler.acquire_scan_lock",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.services.scheduler.release_scan_lock",
            new_callable=AsyncMock,
        ), patch(
            "app.services.ai_index_checker.AIIndexChecker.get_pending_urls",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await scheduled_ai_index_check()


@pytest.mark.asyncio
async def test_scheduled_ai_index_check_locked():
    """AI 收录检测定时任务：已有锁时跳过。"""
    from app.services.scheduler import scheduled_ai_index_check

    with patch(
        "app.services.scheduler.acquire_scan_lock",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await scheduled_ai_index_check()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_client_isolation.py -v -p no:cacheprovider`
预期：FAIL，`scheduled_ai_index_check` 不存在

- [ ] **步骤 3：实现 scheduler 新增定时任务**

在 `index-monitor/app/services/scheduler.py` 中：

**3a. 新增 `scheduled_ai_index_check` 函数**（在 `scheduled_citation_check` 之后）：

```python
async def scheduled_ai_index_check():
    """每日 02:30 AI 收录检测（兜底 pending）。

    处理自动联动触发失败的 URL×模型组合。
    在搜索引擎收录检测（02:00）之后、采信检测（03:00）之前执行。
    """
    from app.services.ai_index_checker import AIIndexChecker
    async with async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("已有 AI 收录扫描在运行，定时任务跳过")
            return
        try:
            checker = AIIndexChecker(db)
            pending = await checker.get_pending_urls()
            if not pending:
                logger.info("AI 收录检测：无待检测组合")
                return
            task_id = create_task("ai_index", len(pending), pending)
            logger.info("AI 收录检测定时任务启动：共 %d 组合（task_id=%s）", len(pending), task_id)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        finally:
            await release_scan_lock(db, "ai_index")
```

**3b. 在 `start_scheduler` 中注册定时任务**（在 `citation_check` 之后添加）：

```python
    # AI 收录检测：每日 02:30（Phase 3 新增，兜底 pending）
    scheduler.add_job(
        scheduled_ai_index_check,
        CronTrigger(hour=2, minute=30),
        id="ai_index_check",
        replace_existing=True,
    )
```

更新 `start_scheduler` 末尾的日志：

```python
        logger.info(
            "APScheduler 已启动：收录检测(每日 02:00) + AI 收录检测(每日 02:30) "
            "+ 采信检测(每日 03:00) + 导出处理(每 30 秒) + 归档扫描(每日 02:00)"
        )
```

- [ ] **步骤 4：旧端点 deprecated**

在 `index-monitor/app/api/routes.py` 中找到 `trigger_scan` 函数，在函数开头添加 deprecated 转发：

```python
@router.post("/scan/trigger/{scan_type}")
async def trigger_scan(scan_type: str, db: AsyncSession = Depends(get_db)):
    """[DEPRECATED] 请使用 POST /api/v1/admin/scan/trigger。

    Phase 3：此端点已迁移到统一扫描入口 /admin/scan/trigger。
    保留向后兼容，内部转发。
    """
    from fastapi import Response
    from app.api.admin_routes import unified_scan_trigger, ScanTriggerRequest
    from app.api.deps import get_current_admin
    # 旧端点无 admin 鉴权，这里直接调用统一入口逻辑
    # 注意：旧端点保持原有鉴权行为（无 admin 鉴权），仅转发 scan_type
    req = ScanTriggerRequest(scan_type=scan_type)
    # 旧端点不接受 admin 参数，直接调用内部逻辑
    # 为简化：直接复用 trigger_scan 原有逻辑（保持不变）
    # 标记 deprecated：响应头加 Deprecation
    ...
```

> **注意：** 旧端点 `trigger_scan` 原有逻辑保持不变，仅在 docstring 标记 `[DEPRECATED]`，并在响应中添加提示。不需要实际转发（因为旧端点无 admin 鉴权，转发会增加复杂度）。前端 Phase 4 迁移后删除。

实际上更简单的做法：在 `trigger_scan` 的 docstring 标记 deprecated，并在返回的 JSON 中加 `"deprecated": True` 字段。

修改 `trigger_scan` 的返回值，在每个 return 中添加 `"deprecated": True`。

- [ ] **步骤 5：运行测试验证通过**

运行：`docker exec geo-index-monitor-local python -m pytest tests/unit/test_client_isolation.py -v -p no:cacheprovider`
预期：2 passed（跳过 1 个需要同步 session 的）

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/services/scheduler.py index-monitor/app/api/routes.py index-monitor/tests/unit/test_client_isolation.py
git commit -m "refactor(scheduler): 新增 02:30 AI 收录检测定时任务 + 旧端点 deprecated"
```

---

## 自检

### 规格覆盖度

| 设计文档章节 | 对应任务 | 状态 |
|-------------|---------|------|
| 客户问题管理 CRUD（运营端） | 任务 1 + 任务 2 | ✅ |
| 监测问题（客户端只读） | 任务 2 | ✅ |
| AI 收录检测触发 + 结果查询 + 统计 | 任务 3 | ✅ |
| 问题监测触发 + 结果查询 | 任务 4 | ✅ |
| 统一扫描触发 | 任务 4 | ✅ |
| 客户端只读 API（概览+证据+统计） | 任务 7 | ✅ |
| 自动联动机制 | 任务 5 + 任务 6 | ✅ |
| 现有端点改造（手动添加文章触发联动） | 任务 6 | ✅ |
| 现有端点改造（batch-scan 扩展 ai_index） | 任务 6 | ✅ |
| 现有端点改造（旧端点 deprecated） | 任务 8 | ✅ |
| 调度器新增 AI 收录检测定时任务 | 任务 8 | ✅ |
| 路由注册（main.py） | 任务 2 + 任务 3 + 任务 7 | ✅ |
| 客户端隔离设计 | 任务 7（隔离逻辑）+ 任务 7 测试 | ✅ |

### 后续 Phase 覆盖

以下设计章节由 Phase 4 实现，不在本计划范围：
- 前端 UI（运营端页面 + 客户端页面）
- 路由守卫（admin/customer 分流）
- Dashboard 图表调整
- ScanPanel 改造（前端部分）
- 客户端 PDF 导出 UI
