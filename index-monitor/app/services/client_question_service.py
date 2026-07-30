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
