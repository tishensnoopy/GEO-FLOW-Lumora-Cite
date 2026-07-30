# index-monitor/tests/integration/test_citations_rate.py
"""GET /citations 命中率统计口径集成测试。

阶段 1 - ⑥a 收尾：
原实现 `exact_rate = exact / total`，分母 total 含 unverifiable 记录
（模型未返回联网来源、抓取失败等无法判定命中的记录），会稀释命中率。
正确口径：`exact_rate = exact / (exact + domain + none)`，
分母只计"可判定命中"的有效回答，unverifiable 不参与命中率计算。

本测试构造 1 条 exact + 1 条 domain + 1 条 none + 1 条 unverifiable 的数据，
验证 exact_rate = 1/3 ≈ 0.3333（而非错误的 1/4 = 0.25）。

鉴权说明：用 admin JWT（SSO_JWT_SECRET 签发，type='admin'）。
/citations 对 admin 返回全部 URL，exact_rate 聚合逻辑与 client 视图一致，
仅 WHERE 过滤范围不同，因此 admin 路径足以验证命中率口径修正。
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.config import settings
from app.models.citation_result import CitationResult
from app.models.index_result import IndexResult


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
    """构造 admin JWT 请求头（SSO_JWT_SECRET 签发，type='admin'）。

    verify_admin_jwt 要求 sub 可转为 int、name/role 非 None、type='admin'。
    """
    payload = {
        "sub": "1", "name": "命中率测试员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


async def _seed_citation(db, url: str, hit_type: str, model: str, question: str) -> None:
    """插入一条采信结果。model + question 组合保证唯一约束不冲突。"""
    db.add(CitationResult(
        url=url,
        model=model,
        question=question,
        answer=f"{hit_type} 回答",
        hit_type=hit_type,
        sources=[f"https://src.example.com/{hit_type}"] if hit_type != "none" else [],
    ))
    await db.commit()


async def _cleanup(db, url: str) -> None:
    """清理指定 URL 的测试数据，避免唯一约束冲突。"""
    await db.execute(delete(CitationResult).where(CitationResult.url == url))
    await db.execute(delete(IndexResult).where(IndexResult.url == url))
    await db.commit()


@pytest.mark.asyncio
async def test_exact_rate_excludes_unverifiable(client, db_session):
    """exact_rate 分母应排除 unverifiable，只用 exact+domain+none。

    数据构造：1 exact + 1 domain + 1 none + 1 unverifiable
    - 旧（错误）：exact_rate = 1/4 = 0.25
    - 新（正确）：exact_rate = 1/3 ≈ 0.3333
    """
    url = f"https://cite-rate.example.com/{uuid.uuid4()}"
    await _cleanup(db_session, url)

    # IndexResult 决定 URL 可见性（admin 视图下也需存在才会出现在 url_subquery）
    db_session.add(IndexResult(
        url=url,
        client_id="test_cite_rate_client",
        site_type="official",
        content_title="命中率口径测试文章",
    ))
    await db_session.commit()

    # 四种 hit_type 各一条
    await _seed_citation(db_session, url, "exact", "qwen", "exact 问题?")
    await _seed_citation(db_session, url, "domain", "doubao", "domain 问题?")
    await _seed_citation(db_session, url, "none", "ernie", "none 问题?")
    await _seed_citation(db_session, url, "unverifiable", "openai", "unverifiable 问题?")

    resp = await client.get("/api/v1/citations", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    row = next((r for r in rows if r["url"] == url), None)
    assert row is not None, f"未返回测试 URL 的采信统计: {rows}"

    # 统计字段校验
    assert row["exact"] == 1
    assert row["domain"] == 1
    assert row["none"] == 1
    assert row["unverifiable"] == 1
    assert row["total"] == 4

    # 关键断言：exact_rate = 1/(1+1+1) ≈ 0.3333，而非 1/4 = 0.25
    assert row["exact_rate"] == round(1 / 3, 4), (
        f"exact_rate 应排除 unverifiable（期望 {round(1/3, 4)}，实际 {row['exact_rate']}）"
    )
    # domain_rate 同理：1/3 ≈ 0.3333
    assert row["domain_rate"] == round(1 / 3, 4)


@pytest.mark.asyncio
async def test_exact_rate_all_unverifiable(client, db_session):
    """全部为 unverifiable 时，有效分母为 0，exact_rate 应回退为 0（不除零）。"""
    url = f"https://cite-rate-all.example.com/{uuid.uuid4()}"
    await _cleanup(db_session, url)

    db_session.add(IndexResult(
        url=url,
        client_id="test_cite_rate_client",
        site_type="official",
        content_title="全 unverifiable 测试",
    ))
    await db_session.commit()

    await _seed_citation(db_session, url, "unverifiable", "qwen", "u1 问题?")
    await _seed_citation(db_session, url, "unverifiable", "doubao", "u2 问题?")

    resp = await client.get("/api/v1/citations", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    row = next((r for r in resp.json() if r["url"] == url), None)
    assert row is not None

    assert row["exact"] == 0
    assert row["domain"] == 0
    assert row["none"] == 0
    assert row["unverifiable"] == 2
    # 有效分母 = 0，应回退为 0，不能抛 ZeroDivisionError
    assert row["exact_rate"] == 0
    assert row["domain_rate"] == 0
