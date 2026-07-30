# index-monitor/tests/integration/test_data_management.py
"""QA 数据管理接口集成测试。

验证管理员对采信结果、收录结果、分发记录、审计日志的删除/编辑能力。
所有操作需 admin 鉴权 + 记录审计日志。
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select, update as sa_update

from app.core.config import settings
from app.models.admin_audit_log import AdminAuditLog
from app.models.citation_result import CitationResult
from app.models.client import Client
from app.models.index_result import IndexResult
from app.models.manual_distribution import ManualDistribution


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    """override get_db，避免跨事件循环复用模块级 engine。"""
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _admin_headers() -> dict:
    """构造 admin JWT 请求头。"""
    payload = {
        "sub": "1", "name": "数据管理测试员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _client_headers(client_id: str = "test_dm_client") -> dict:
    """构造普通客户 JWT（用于验证非 admin 被拒）。"""
    payload = {
        "sub": client_id, "name": "普通客户", "role": "client", "type": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# 避免在每个测试中重复 import


async def _seed_citation_result(db, url: str = None) -> CitationResult:
    """插入一条采信结果，返回其 id（UUID 字符串）。
    url 默认带随机 UUID，避免跨测试数据污染触发唯一约束。"""
    record = CitationResult(
        url=url or f"https://dm-test.example.com/{uuid.uuid4()}",
        model="qwen",
        question="测试问题?",
        answer="测试回答",
        hit_type="exact",
        sources=["https://src.example.com"],
    )
    db.add(record)
    await db.commit()
    return str(record.id)


async def _seed_index_result(db, url: str = None) -> IndexResult:
    """插入一条收录结果。url 默认带随机 UUID 避免唯一约束冲突。"""
    record = IndexResult(
        url=url or f"https://dm-test.example.com/i/{uuid.uuid4()}",
        client_id="test_dm_client",
        site_type="official",
        content_title="测试文章",
    )
    db.add(record)
    await db.commit()
    return str(record.id)


async def _seed_distribution(db, url: str = None) -> ManualDistribution:
    """插入一条手动分发记录。url 默认带随机 UUID 避免唯一约束冲突。"""
    record = ManualDistribution(
        client_id="test_dm_client",
        remote_url=url or f"https://dm-test.example.com/d/{uuid.uuid4()}",
        status="synced",
        note="测试备注",
    )
    db.add(record)
    await db.commit()
    return str(record.id)


# ---------- 采信结果删除 ----------

@pytest.mark.asyncio
async def test_delete_citation_result_success(client, db_session):
    """admin 可删除单条采信结果，并记录审计日志。"""
    rid = await _seed_citation_result(db_session)
    resp = await client.delete(f"/api/v1/admin/citation-results/{rid}", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True
    # 审计日志应记录
    logs = (await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "delete_citation_result")
    )).scalars().all()
    assert len(logs) >= 1


@pytest.mark.asyncio
async def test_delete_citation_result_not_found(client):
    """删除不存在的采信结果返回 404。"""
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/api/v1/admin/citation-results/{fake_id}", headers=_admin_headers())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_citation_result_rejects_non_admin(client, db_session):
    """非 admin 调用删除被拒（401/403）。"""
    rid = await _seed_citation_result(db_session)
    resp = await client.delete(f"/api/v1/admin/citation-results/{rid}", headers=_client_headers())
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_batch_delete_citation_results_by_url(client, db_session):
    """按 URL 批量删除采信结果（清除旧记录以便重新扫描）。"""
    url = f"https://dm-batch.example.com/{uuid.uuid4()}"
    # 同 URL 不同 question，避免触发 (url,model,question) 唯一约束
    db_session.add(CitationResult(url=url, model="qwen", question="问题一?", hit_type="exact"))
    db_session.add(CitationResult(url=url, model="qwen", question="问题二?", hit_type="none"))
    await db_session.commit()
    resp = await client.post(
        "/api/v1/admin/citation-results/batch-delete",
        json={"url": url},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2


# ---------- 收录结果删除 ----------

@pytest.mark.asyncio
async def test_delete_index_result_success(client, db_session):
    """admin 可删除单条收录结果。"""
    rid = await _seed_index_result(db_session)
    resp = await client.delete(f"/api/v1/admin/index-results/{rid}", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_batch_delete_index_results_by_url(client, db_session):
    """按 URL 批量删除收录结果。"""
    url = "https://dm-idx-batch.example.com"
    # IndexResult.url 有 unique 约束，同 URL 只能一条，改用 ids 批量删
    id1 = await _seed_index_result(db_session, url=url + "/1")
    id2 = await _seed_index_result(db_session, url=url + "/2")
    resp = await client.post(
        "/api/v1/admin/index-results/batch-delete",
        json={"ids": [id1, id2]},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2


# ---------- 分发记录编辑/删除 ----------

@pytest.mark.asyncio
async def test_update_distribution_note(client, db_session):
    """admin 可编辑分发记录的备注。"""
    did = await _seed_distribution(db_session)
    resp = await client.put(
        f"/api/v1/admin/distributions/{did}",
        json={"note": "已更新备注"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["changes"]["note"] == "已更新备注"


@pytest.mark.asyncio
async def test_update_distribution_invalid_status(client, db_session):
    """编辑分发记录传非法 status 返回 400。"""
    did = await _seed_distribution(db_session)
    resp = await client.put(
        f"/api/v1/admin/distributions/{did}",
        json={"status": "invalid_status"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_distribution_success(client, db_session):
    """admin 可删除分发记录。"""
    did = await _seed_distribution(db_session, url="https://dm-del.example.com")
    resp = await client.delete(f"/api/v1/admin/distributions/{did}", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ---------- 审计日志清理 ----------

@pytest.mark.asyncio
async def test_cleanup_audit_logs(client, db_session):
    """admin 可按日期清理旧审计日志。"""
    # 插入一条旧日志
    old_log = AdminAuditLog(
        admin_user_id=1,
        admin_name="旧操作员",
        action="old_action",
        target_type="test",
    )
    db_session.add(old_log)
    await db_session.commit()
    await db_session.execute(
        sa_update(AdminAuditLog)
        .where(AdminAuditLog.id == old_log.id)
        .values(created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/admin/audit-logs/cleanup",
        json={"before_date": "2025-01-01"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] >= 1


@pytest.mark.asyncio
async def test_batch_delete_requires_ids_or_url(client):
    """批量删除不传 ids 也不传 url 返回 400。"""
    resp = await client.post(
        "/api/v1/admin/citation-results/batch-delete",
        json={},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ---------- 分发记录批量删除 ----------
# 设计：仅删除 monitor.manual_distributions 表中的记录（即手动录入记录）。
# GEOFlow 同步记录位于 public.article_distributions（跨 schema 只读），
# 不在本表，即使前端误传其 id 也只会被跳过，确保不会误删同步数据。


@pytest.mark.asyncio
async def test_batch_delete_distributions_by_ids(client, db_session):
    """admin 按 ids 批量删除手动分发记录，返回删除数并记录审计日志。"""
    # 用 uuid 后缀避免跨测试数据残留触发 (client_id, remote_url) 唯一约束
    suffix = uuid.uuid4().hex
    id1 = await _seed_distribution(db_session, url=f"https://dm-dist-batch.example.com/{suffix}/1")
    id2 = await _seed_distribution(db_session, url=f"https://dm-dist-batch.example.com/{suffix}/2")
    resp = await client.post(
        "/api/v1/admin/distributions/batch-delete",
        json={"ids": [id1, id2]},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2
    # 审计日志应记录
    logs = (await db_session.execute(
        select(AdminAuditLog).where(AdminAuditLog.action == "batch_delete_distributions")
    )).scalars().all()
    assert len(logs) >= 1
    # 实际已从表中删除
    remaining = (await db_session.execute(
        select(ManualDistribution).where(ManualDistribution.id.in_([id1, id2]))
    )).scalars().all()
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_batch_delete_distributions_skips_nonexistent_ids(client, db_session):
    """传入不存在的 id（模拟 GEOFlow 同步记录 id 误传）应跳过，只删 manual 表中存在的记录。

    回归防御：前端按钮在含同步记录时禁用，但后端必须独立防御——GEOFlow 同步记录
    不在 manual_distributions 表，select where id in (...) 查不到即跳过，
    不会抛错也不会误删同步数据。
    """
    real_id = await _seed_distribution(db_session, url="https://dm-skip.example.com")
    fake_geoflow_id = str(uuid.uuid4())  # 不在 manual 表，模拟 geoflow 记录 id
    resp = await client.post(
        "/api/v1/admin/distributions/batch-delete",
        json={"ids": [real_id, fake_geoflow_id]},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    # 只删除了 1 条真实存在的记录
    assert resp.json()["deleted"] == 1


@pytest.mark.asyncio
async def test_batch_delete_distributions_rejects_non_admin(client, db_session):
    """非 admin 调用批量删除被拒（401/403）。"""
    did = await _seed_distribution(db_session)
    resp = await client.post(
        "/api/v1/admin/distributions/batch-delete",
        json={"ids": [did]},
        headers=_client_headers(),
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_batch_delete_distributions_requires_ids(client):
    """批量删除分发记录不传 ids 返回 400。"""
    resp = await client.post(
        "/api/v1/admin/distributions/batch-delete",
        json={},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ---------- 手动添加支持用户输入标题（反爬页 fallback） ----------
# 回归：lieju.com 等反爬页 article_fetcher 抓取标题返回 None，导致 content_title=None，
# 文章列表/分发记录都不显示标题。修复：支持用户手动输入标题，优先于抓取。


@pytest.mark.asyncio
async def test_create_manual_distribution_uses_user_supplied_title(client, db_session, monkeypatch):
    """手动添加时用户填写标题，应直接使用，不依赖抓取（反爬页标题 fallback）。"""
    # mock 抓取返回 (None, None) 模拟反爬页失败
    async def fake_fetch(url):
        return None, None
    monkeypatch.setattr(
        "app.services.article_fetcher.article_fetcher.fetch_title_and_snapshot",
        fake_fetch,
    )

    url = f"https://manual-title.example.com/{uuid.uuid4()}"
    resp = await client.post(
        "/api/v1/distributions",
        json={"remote_url": url, "client_id": "test_dm_client", "title": "用户自定义标题"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 201
    # ManualDistribution.content_title 应为用户填的标题（即使抓取失败）
    record = (await db_session.execute(
        select(ManualDistribution).where(ManualDistribution.remote_url == url)
    )).scalar_one_or_none()
    assert record is not None
    assert record.content_title == "用户自定义标题"


@pytest.mark.asyncio
async def test_create_manual_distribution_falls_back_to_fetch_when_no_title(client, db_session, monkeypatch):
    """用户未填标题时，回退到抓取（保持原行为不回归）。"""
    async def fake_fetch(url):
        return "抓取到的标题", "正文快照"
    monkeypatch.setattr(
        "app.services.article_fetcher.article_fetcher.fetch_title_and_snapshot",
        fake_fetch,
    )

    url = f"https://fetch-title.example.com/{uuid.uuid4()}"
    resp = await client.post(
        "/api/v1/distributions",
        json={"remote_url": url, "client_id": "test_dm_client"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 201
    record = (await db_session.execute(
        select(ManualDistribution).where(ManualDistribution.remote_url == url)
    )).scalar_one_or_none()
    assert record is not None
    assert record.content_title == "抓取到的标题"
