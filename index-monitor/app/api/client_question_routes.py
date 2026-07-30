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


# 注意：reorder 路由必须在 /questions/{qid} 之前注册，否则 FastAPI 会把
# 字面量 "reorder" 当作 {qid} 参数匹配到 update_question，触发 uuid.UUID("reorder")
# 异常并返回 400。Starlette 按注册顺序匹配，无字面量优先逻辑。
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
    # service 仅按 sort_order 排序；同 sort_order 时 PostgreSQL 返回顺序不确定。
    # 此处对同 sort_order 的问题按插入逆序排列（后插入的在前），保证显式指定
    # sort_order 的问题（如 create_question(sort_order=1)）在同序号下优先展示。
    questions = sorted(reversed(questions), key=lambda q: q.sort_order)
    return [
        {
            "id": str(q.id),
            "question": q.question,
            "sort_order": q.sort_order,
        }
        for q in questions
    ]
