# index-monitor/tests/unit/test_client_work_report.py
"""Phase 2 客户端 API 单元测试：work-report / rankings / visibility。

直接调用 ``app.api.client_routes`` 中的路由函数（绕过 HTTP 与 JWT 鉴权），
用 ``db_session`` fixture 连真实 PostgreSQL，验证：
1. work-report 返回 summary 统计 + items 关联问题与引用命中
2. rankings 按 active 问题分组返回 AI 回答全文
3. visibility 把引用率翻译成 0-100 平台得分与雷达图数据

数据隔离：所有测试用唯一 client_id="client_wr_test"，并在每个测试前
清理 4 张相关表的数据，避免相互污染。
"""
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.api.client_routes import (
    client_rankings,
    client_visibility,
    client_work_report,
)
from app.models.article_question_mapping import ArticleQuestionMapping
from app.models.citation_result import CitationResult
from app.models.client_question import ClientQuestion
from app.models.manual_distribution import ManualDistribution

TEST_CLIENT_ID = "client_wr_test"


@pytest_asyncio.fixture(autouse=True)
async def _clean_work_report_data(db_session):
    """每个测试前清理 TEST_CLIENT_ID 相关数据。

    清理顺序遵循外键依赖：先删 citation_results / mappings（引用方），
    再删 client_questions / manual_distributions（被引用方）。
    全部用子查询 IN (SELECT ...) 关联，避免 asyncpg 的数组参数类型推断问题。
    """
    # 1. 删 citation_results（按 url 关联客户发稿，或按 client_question_id 关联客户问题）
    await db_session.execute(
        text(
            "DELETE FROM monitor.citation_results WHERE url IN ("
            "  SELECT remote_url FROM monitor.manual_distributions "
            "  WHERE client_id = :cid"
            ")"
        ),
        {"cid": TEST_CLIENT_ID},
    )
    await db_session.execute(
        text(
            "DELETE FROM monitor.citation_results "
            "WHERE client_question_id IN ("
            "  SELECT id FROM monitor.client_questions WHERE client_id = :cid"
            ")"
        ),
        {"cid": TEST_CLIENT_ID},
    )

    # 2. 删 article_question_mappings（按 distribution_id 子查询关联）
    await db_session.execute(
        text(
            "DELETE FROM monitor.article_question_mappings WHERE distribution_id IN ("
            "  SELECT id FROM monitor.manual_distributions WHERE client_id = :cid"
            ")"
        ),
        {"cid": TEST_CLIENT_ID},
    )

    # 3. 删 client_questions
    await db_session.execute(
        text("DELETE FROM monitor.client_questions WHERE client_id = :cid"),
        {"cid": TEST_CLIENT_ID},
    )

    # 4. 删 manual_distributions
    await db_session.execute(
        text("DELETE FROM monitor.manual_distributions WHERE client_id = :cid"),
        {"cid": TEST_CLIENT_ID},
    )

    await db_session.commit()
    yield


@pytest.mark.asyncio
async def test_work_report_returns_summary_and_items(db_session):
    """work-report 返回 summary 统计 + items（含关联问题与引用命中）。"""
    # 1. 准备数据：1 篇发稿 + 1 个 active 问题 + 1 条关联映射 + 1 条引用命中
    dist = ManualDistribution(
        client_id=TEST_CLIENT_ID,
        remote_url="https://example.com/article-a",
        status="synced",
        content_title="企业数字化转型指南",
    )
    db_session.add(dist)
    await db_session.commit()
    await db_session.refresh(dist)

    question = ClientQuestion(
        client_id=TEST_CLIENT_ID,
        question="企业数字化转型方案",
        sort_order=1,
        status="active",
    )
    db_session.add(question)
    await db_session.commit()
    await db_session.refresh(question)

    mapping = ArticleQuestionMapping(
        distribution_id=dist.id,
        client_question_id=question.id,
        relevance_score=0.92,
    )
    db_session.add(mapping)

    citation = CitationResult(
        url="https://example.com/article-a",
        model="doubao",
        question="企业数字化转型方案",
        answer="回答全文...",
        hit_type="exact",
        sources=[{"url": "https://example.com/article-a", "title": "企业数字化转型指南"}],
        client_question_id=question.id,
    )
    db_session.add(citation)
    await db_session.commit()

    # 2. 调用路由函数
    result = await client_work_report(client_id=TEST_CLIENT_ID, db=db_session)

    # 3. 断言 summary
    assert result["summary"]["total_distributions"] == 1
    assert result["summary"]["total_questions"] == 1
    assert result["summary"]["total_cited"] == 1
    # citation_rate = 1/1 = 1.0
    assert result["summary"]["citation_rate"] == 1.0
    # this_month_distributions：created_at 由 server_default=now() 填充，应在当月
    assert result["summary"]["this_month_distributions"] == 1

    # 4. 断言 items
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["url"] == "https://example.com/article-a"
    assert item["title"] == "企业数字化转型指南"
    assert item["distributed_at"] is not None

    # 4.1 关联问题
    assert len(item["questions"]) == 1
    q = item["questions"][0]
    assert q["question"] == "企业数字化转型方案"
    assert q["relevance_score"] == 0.92

    # 4.2 引用命中
    assert len(item["citation_results"]) == 1
    c = item["citation_results"][0]
    assert c["model"] == "doubao"
    assert c["hit_type"] == "exact"
    assert c["question"] == "企业数字化转型方案"


@pytest.mark.asyncio
async def test_rankings_returns_answers(db_session):
    """rankings 按 active 问题分组返回 AI 回答全文与来源。"""
    # 1. 准备数据：2 个 active 问题，每个问题 1 条 citation_result
    q1 = ClientQuestion(
        client_id=TEST_CLIENT_ID,
        question="企业数字化转型方案",
        sort_order=1,
        status="active",
    )
    q2 = ClientQuestion(
        client_id=TEST_CLIENT_ID,
        question="SaaS 选型建议",
        sort_order=2,
        status="active",
    )
    # inactive 问题不应出现在 rankings 中
    q3 = ClientQuestion(
        client_id=TEST_CLIENT_ID,
        question="已停用问题",
        sort_order=3,
        status="inactive",
    )
    db_session.add_all([q1, q2, q3])
    await db_session.commit()
    await db_session.refresh(q1)
    await db_session.refresh(q2)
    await db_session.refresh(q3)

    cit1 = CitationResult(
        url="https://example.com/article-a",
        model="doubao",
        question="企业数字化转型方案",
        answer="豆包的回答全文：数字化转型需要...",
        hit_type="exact",
        sources=[{"url": "https://example.com/article-a", "title": "指南"}],
        client_question_id=q1.id,
    )
    cit2 = CitationResult(
        url="https://example.com/article-b",
        model="qwen",
        question="SaaS 选型建议",
        answer="千问的回答全文：SaaS 选型应考虑...",
        hit_type="domain",
        sources=[{"url": "https://example.com/article-b"}],
        client_question_id=q2.id,
    )
    db_session.add_all([cit1, cit2])
    await db_session.commit()

    # 2. 调用
    result = await client_rankings(client_id=TEST_CLIENT_ID, db=db_session)

    # 3. 断言：仅 2 个 active 问题，按 sort_order 排序
    questions = result["questions"]
    assert len(questions) == 2
    assert questions[0]["question"] == "企业数字化转型方案"
    assert questions[1]["question"] == "SaaS 选型建议"

    # 3.1 第一个问题的回答快照
    r1 = questions[0]["results"]
    assert len(r1) == 1
    assert r1[0]["model"] == "doubao"
    assert r1[0]["hit_type"] == "exact"
    assert "数字化转型" in r1[0]["answer"]
    assert r1[0]["article_url"] == "https://example.com/article-a"
    assert r1[0]["checked_at"] is not None

    # 3.2 第二个问题的回答快照
    r2 = questions[1]["results"]
    assert len(r2) == 1
    assert r2[0]["model"] == "qwen"
    assert r2[0]["hit_type"] == "domain"
    assert "SaaS" in r2[0]["answer"]


@pytest.mark.asyncio
async def test_visibility_returns_scores(db_session):
    """visibility 把引用率翻译成 0-100 平台得分与雷达图数据。

    构造场景：
    - doubao: 10 次检测，8 次命中 → score=80
    - qwen: 10 次检测，7 次命中 → score=70
    - overall = (8+7)/(10+10) * 100 = 75
    """
    # 1. 准备 1 篇发稿（让 _get_client_urls 能拿到 url）
    dist = ManualDistribution(
        client_id=TEST_CLIENT_ID,
        remote_url="https://example.com/visibility-article",
        status="synced",
        content_title="可见度测试文章",
    )
    db_session.add(dist)
    await db_session.commit()

    url = "https://example.com/visibility-article"
    citations = []
    # doubao: 8 exact + 2 none → cited=8, total=10
    for i in range(8):
        citations.append(CitationResult(
            url=url,
            model="doubao",
            question=f"问题-doubao-{i}",
            answer="回答",
            hit_type="exact",
        ))
    for i in range(2):
        citations.append(CitationResult(
            url=url,
            model="doubao",
            question=f"问题-doubao-none-{i}",
            answer="回答",
            hit_type="none",
        ))
    # qwen: 7 domain + 3 none → cited=7, total=10
    for i in range(7):
        citations.append(CitationResult(
            url=url,
            model="qwen",
            question=f"问题-qwen-{i}",
            answer="回答",
            hit_type="domain",
        ))
    for i in range(3):
        citations.append(CitationResult(
            url=url,
            model="qwen",
            question=f"问题-qwen-none-{i}",
            answer="回答",
            hit_type="none",
        ))
    db_session.add_all(citations)
    await db_session.commit()

    # 2. 调用
    result = await client_visibility(client_id=TEST_CLIENT_ID, db=db_session)

    # 3. 断言综合得分
    assert result["overall_score"] == 75  # (8+7)/(10+10)*100

    # 4. 断言平台得分
    platform_scores = {p["model"]: p for p in result["platform_scores"]}
    assert "doubao" in platform_scores
    assert "qwen" in platform_scores
    assert platform_scores["doubao"]["score"] == 80
    assert platform_scores["doubao"]["total"] == 10
    assert platform_scores["doubao"]["cited"] == 8
    assert platform_scores["qwen"]["score"] == 70
    assert platform_scores["qwen"]["total"] == 10
    assert platform_scores["qwen"]["cited"] == 7

    # 5. 断言雷达图数据
    radar = result["radar_data"]
    assert set(radar["labels"]) == {"豆包", "千问"}
    assert len(radar["values"]) == 2
    # labels 与 platform_scores 顺序一致
    label_to_value = dict(zip(radar["labels"], radar["values"]))
    assert label_to_value["豆包"] == 80
    assert label_to_value["千问"] == 70


@pytest.mark.asyncio
async def test_work_report_admin_forbidden(db_session):
    """admin token 调用 work-report 应被 403 拒绝。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await client_work_report(client_id="admin", db=db_session)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_visibility_empty_client_returns_zeros(db_session):
    """无发稿客户调用 visibility 返回全 0 空结构。"""
    result = await client_visibility(client_id=TEST_CLIENT_ID, db=db_session)
    assert result["overall_score"] == 0
    assert result["platform_scores"] == []
    assert result["radar_data"] == {"labels": [], "values": []}
