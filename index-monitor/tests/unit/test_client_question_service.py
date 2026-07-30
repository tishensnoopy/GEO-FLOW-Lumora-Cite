"""ClientQuestionService 单元测试。"""
import pytest
import pytest_asyncio
import uuid
from app.services.client_question_service import ClientQuestionService
from app.models.client_question import ClientQuestion
from app.models.client import Client


@pytest_asyncio.fixture(autouse=True)
async def _clean_client_questions(db_session):
    """每个测试前清理 monitor.client_questions 表，保证测试间数据隔离。

    db_session fixture 仅做事件循环隔离（每测试新建 engine），不做数据回滚；
    本文件所有测试共用 client_id="client_a"，若不清理会相互污染
    （如 test_create_question_auto_sort_order 的 max(sort_order) 受前置测试影响）。
    """
    from sqlalchemy import text
    await db_session.execute(text("DELETE FROM monitor.client_questions"))
    await db_session.commit()
    yield


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
