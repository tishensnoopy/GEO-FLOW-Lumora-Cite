"""客户问题管理 API 集成测试。

测试基础设施说明
================

复用 ``test_distribution_endpoint.py`` / ``test_export_endpoints.py`` 的既有模式：

- ``_override_app_db`` (autouse)：为每个测试 override ``get_db`` 依赖，使用当前
  事件循环的全新 engine。pytest-asyncio strict 模式为每个测试创建独立事件循环，
  复用模块级 ``app.core.database.engine`` 会触发 "Future attached to a different loop"。
- 使用 ``tests/conftest.py`` 中的 ``client`` fixture（httpx.AsyncClient + ASGITransport）
  替代简报中的 ``starlette.TestClient``，避免同步 TestClient 与异步 ``db_session``
  fixture 在 strict 模式下的事件循环冲突。
- 鉴权头 ``admin_auth_headers`` / ``client_auth_headers`` 来自
  ``tests/integration/conftest.py``，跨任务复用。
- ``_clean_client_questions`` (autouse, conftest.py) 清理 ``monitor.client_questions``
  表，保证测试间数据隔离。
"""
import pytest
import pytest_asyncio

from app.core.config import settings
from app.services.client_question_service import ClientQuestionService


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """为每个测试 override ``get_db`` 依赖，使用当前事件循环的全新 engine。

    pytest-asyncio strict 模式为每个测试创建独立事件循环。``app.core.database.engine``
    是模块级单例，其连接池里的 asyncpg 连接绑定到首次 import 时的事件循环，
    跨测试复用会触发 "Future attached to a different loop" /
    "another operation is in progress"。

    用 FastAPI ``app.dependency_overrides`` 把 ``get_db`` 替换为闭包，
    闭包内用本测试事件循环新建的 engine → session_factory → session。
    测试结束 dispose 这个临时 engine，不污染模块级 engine。
    """
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        async_sessionmaker,
        AsyncSession,
    )

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_admin_list_questions(db_session, admin_auth_headers, client):
    """admin 列出客户问题。"""
    service = ClientQuestionService(db_session)
    await service.create_question("DEMO001", "问题1")
    await service.create_question("DEMO001", "问题2")

    response = await client.get(
        "/api/v1/admin/clients/DEMO001/questions",
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["question"] == "问题1"


@pytest.mark.asyncio
async def test_admin_create_question(db_session, admin_auth_headers, client):
    """admin 添加问题。"""
    response = await client.post(
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
async def test_admin_update_question(db_session, admin_auth_headers, client):
    """admin 编辑问题。"""
    service = ClientQuestionService(db_session)
    q = await service.create_question("DEMO001", "原问题")

    response = await client.put(
        f"/api/v1/admin/clients/DEMO001/questions/{q.id}",
        json={"question": "新问题", "status": "inactive"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["question"] == "新问题"
    assert response.json()["status"] == "inactive"


@pytest.mark.asyncio
async def test_admin_delete_question(db_session, admin_auth_headers, client):
    """admin 删除问题。"""
    service = ClientQuestionService(db_session)
    q = await service.create_question("DEMO001", "待删除")

    response = await client.delete(
        f"/api/v1/admin/clients/DEMO001/questions/{q.id}",
        headers=admin_auth_headers,
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_admin_reorder_questions(db_session, admin_auth_headers, client):
    """admin 批量排序。"""
    service = ClientQuestionService(db_session)
    q1 = await service.create_question("DEMO001", "A")
    q2 = await service.create_question("DEMO001", "B")

    response = await client.put(
        "/api/v1/admin/clients/DEMO001/questions/reorder",
        json={"ordered_ids": [str(q2.id), str(q1.id)]},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["reordered"] == 2


@pytest.mark.asyncio
async def test_client_list_own_questions(db_session, client_auth_headers, client):
    """客户查看自己的问题（只读）。"""
    service = ClientQuestionService(db_session)
    await service.create_question("DEMO001", "客户问题1")
    await service.create_question("DEMO001", "客户问题2", sort_order=1)

    response = await client.get("/api/v1/questions", headers=client_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 按 sort_order 排序
    assert data[0]["question"] == "客户问题2"
    assert data[1]["question"] == "客户问题1"
