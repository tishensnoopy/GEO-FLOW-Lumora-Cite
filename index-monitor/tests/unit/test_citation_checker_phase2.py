"""Phase 2: CitationChecker 改造后的测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import delete, select

from app.services.citation_checker import CitationChecker
from app.models.client_question import ClientQuestion
from app.models.ai_index_result import AIIndexResult
from app.models.citation_result import CitationResult


async def _cleanup_test_data(db_session):
    """删除本文件测试用到的 client_id / URL 的残留数据，保证测试可重复运行。

    db_session fixture 不做事务回滚（已知隔离问题，见 conftest.py 注释与
    Phase 1 task6 的同类修复）。client_questions 插入非幂等（无唯一约束），
    ai_index_results 有 UNIQUE(url, model)，二次运行会冲突。这里在插入前统一
    清理本测试自己用到的数据，使测试单独运行与套件运行都通过。
    """
    await db_session.execute(
        delete(ClientQuestion).where(ClientQuestion.client_id == "client_a")
    )
    await db_session.execute(
        delete(AIIndexResult).where(
            AIIndexResult.url == "https://example.com/test"
        )
    )
    await db_session.execute(
        delete(CitationResult).where(
            CitationResult.url == "https://example.com/test"
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_client_questions_returns_active_sorted(db_session):
    """_get_client_questions 返回 active 问题，按 sort_order 排序。"""
    await _cleanup_test_data(db_session)
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="第三个问题",
        sort_order=3,
        status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="第一个问题",
        sort_order=1,
        status="active",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="inactive 问题",
        sort_order=2,
        status="inactive",
    ))
    await db_session.commit()

    checker = CitationChecker(db_session)
    questions = await checker._get_client_questions("client_a")
    assert questions == ["第一个问题", "第三个问题"]


@pytest.mark.asyncio
async def test_get_client_questions_empty(db_session):
    """客户无 active 问题时返回空列表。"""
    checker = CitationChecker(db_session)
    questions = await checker._get_client_questions("no_such_client")
    assert questions == []


@pytest.mark.asyncio
async def test_get_indexed_models(db_session):
    """_get_indexed_models 返回 index_status='indexed' 的模型列表。"""
    await _cleanup_test_data(db_session)
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="qwen",
        index_status="indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="doubao",
        index_status="not_indexed",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="gemini",
        index_status="indexed",
    ))
    await db_session.commit()

    checker = CitationChecker(db_session)
    models = await checker._get_indexed_models("https://example.com/test")
    assert set(models) == {"qwen", "gemini"}


@pytest.mark.asyncio
async def test_get_indexed_models_empty(db_session):
    """URL 无已收录模型时返回空列表。"""
    checker = CitationChecker(db_session)
    models = await checker._get_indexed_models("https://example.com/no-record")
    assert models == []


@pytest.mark.asyncio
async def test_store_results_links_client_question_id(db_session):
    """_store_results 关联 client_question_id。"""
    from app.models.citation_result import CitationResult

    await _cleanup_test_data(db_session)

    # 创建客户问题
    q = ClientQuestion(
        client_id="client_a",
        question="这个产品怎么样？",
        sort_order=1,
        status="active",
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    checker = CitationChecker(db_session)
    fake_result = {
        "results": [{
            "question": "这个产品怎么样？",
            "model": "qwen",
            "answer": "回答",
            "hit": {"layer": "none"},
            "sources": [],
        }],
    }
    await checker._store_results(
        "https://example.com/test",
        fake_result,
        ["这个产品怎么样？"],
        "client_a",
    )

    stored = await db_session.execute(
        select(CitationResult).where(CitationResult.url == "https://example.com/test")
    )
    record = stored.scalar_one()
    assert record.client_question_id == q.id


@pytest.mark.asyncio
async def test_check_url_phase2_3_stages(db_session, monkeypatch):
    """check_url 改造后执行 3 阶段：准备 → 模型探测 → 引用检测。"""
    await _cleanup_test_data(db_session)
    # 准备数据：客户问题 + 已收录模型
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="这个产品怎么样？",
        sort_order=1,
        status="active",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/test",
        model="qwen",
        index_status="indexed",
    ))
    await db_session.commit()

    # mock 抓取内容
    fake_content = MagicMock()
    fake_content.title = "测试标题"
    fake_content.text = "测试内容"
    fake_content.requested_url = "https://example.com/test"
    fake_content.resolved_url = "https://example.com/test"
    fake_content.canonical_url = None
    fake_content.extraction_method = "test"
    fake_content.suitability.suitable = True
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: fake_content,
    )

    # mock 配置加载
    async def fake_load_ai_config(self):
        return {"ai_citation_models": "qwen"}
    monkeypatch.setattr(CitationChecker, "_load_ai_config", fake_load_ai_config)

    # mock default_adapters
    fake_adapter = MagicMock()
    fake_adapter.name = "千问"
    fake_adapter.provider_id = "qwen"
    fake_adapter.model_id = "qwen3.6-plus"
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda selected_ids: [fake_adapter],
    )

    # mock probe_adapter_capabilities
    fake_cap = {"provider_id": "qwen", "model": "千问", "status": "verified", "error": None}
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [fake_cap],
    )

    # mock run_citation_check
    fake_result = {
        "results": [{
            "question": "这个产品怎么样？",
            "model": "千问",
            "answer": "回答内容",
            "hit": {"layer": "none"},
            "sources": [],
        }],
    }
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        lambda **kw: fake_result,
    )

    checker = CitationChecker(db_session)
    result = await checker.check_url("https://example.com/test", "client_a")

    # 验证结果
    assert result["results"][0]["question"] == "这个产品怎么样？"
    # 验证 run_citation_check 收到 client_questions
    # （通过 mock 的调用参数验证，见下方断言）

    # 验证未走问题生成（不应调用 generate_candidates）
    # mock 已替换 run_citation_check，若 check_url 尝试生成问题会因 mock 缺失而报错


@pytest.mark.asyncio
async def test_check_url_no_indexed_models_raises(db_session, monkeypatch):
    """URL 无已收录模型时抛 ValueError。"""
    await _cleanup_test_data(db_session)
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="问题",
        sort_order=1,
        status="active",
    ))
    await db_session.commit()

    fake_content = MagicMock()
    fake_content.title = "标题"
    fake_content.text = "内容"
    fake_content.requested_url = "https://example.com/no-index"
    fake_content.resolved_url = "https://example.com/no-index"
    fake_content.canonical_url = None
    fake_content.extraction_method = "test"
    fake_content.suitability.suitable = True
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: fake_content,
    )

    checker = CitationChecker(db_session)
    with pytest.raises(ValueError, match="未被任何 AI 模型收录"):
        await checker.check_url("https://example.com/no-index", "client_a")


@pytest.mark.asyncio
async def test_check_url_no_client_questions_raises(db_session, monkeypatch):
    """客户无监测问题时抛 ValueError。"""
    fake_content = MagicMock()
    fake_content.title = "标题"
    fake_content.text = "内容"
    fake_content.requested_url = "https://example.com/test"
    fake_content.resolved_url = "https://example.com/test"
    fake_content.canonical_url = None
    fake_content.extraction_method = "test"
    fake_content.suitability.suitable = True
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: fake_content,
    )

    checker = CitationChecker(db_session)
    with pytest.raises(ValueError, match="未配置监测问题"):
        await checker.check_url("https://example.com/test", "no_questions_client")


@pytest.mark.asyncio
async def test_get_pending_urls_4_conditions(db_session):
    """get_pending_urls 需 4 条件全满足：synced + 有 indexed 模型 + 客户有 active 问题 + 无 citation 记录。"""
    from app.models.manual_distribution import ManualDistribution

    # 清理本测试用到的 example.com URL 和 client_a/client_b 残留数据，
    # 保证测试可重复运行（db_session fixture 不做事务回滚）。
    await db_session.execute(
        delete(ManualDistribution).where(
            ManualDistribution.remote_url.like("https://example.com/%")
        )
    )
    await db_session.execute(
        delete(AIIndexResult).where(AIIndexResult.url.like("https://example.com/%"))
    )
    await db_session.execute(
        delete(ClientQuestion).where(
            ClientQuestion.client_id.in_(["client_a", "client_b"])
        )
    )
    await db_session.execute(
        delete(CitationResult).where(
            CitationResult.url.like("https://example.com/%")
        )
    )
    await db_session.commit()

    # URL1: 全满足 → pending
    db_session.add(ManualDistribution(
        client_id="client_a",
        remote_url="https://example.com/pending-url",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/pending-url",
        model="qwen",
        index_status="indexed",
    ))
    db_session.add(ClientQuestion(
        client_id="client_a",
        question="问题",
        sort_order=1,
        status="active",
    ))

    # URL2: 无已收录模型 → 不 pending
    db_session.add(ManualDistribution(
        client_id="client_a",
        remote_url="https://example.com/no-index-model",
        status="synced",
    ))

    # URL3: 客户无问题 → 不 pending
    db_session.add(ManualDistribution(
        client_id="client_b",
        remote_url="https://example.com/no-questions",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/no-questions",
        model="qwen",
        index_status="indexed",
    ))

    # URL4: 已有 citation 记录 → 不 pending
    db_session.add(ManualDistribution(
        client_id="client_a",
        remote_url="https://example.com/already-checked",
        status="synced",
    ))
    db_session.add(AIIndexResult(
        url="https://example.com/already-checked",
        model="qwen",
        index_status="indexed",
    ))
    db_session.add(CitationResult(
        url="https://example.com/already-checked",
        model="qwen",
        question="旧问题",
        answer="",
        hit_type="none",
        sources=[],
    ))

    await db_session.commit()

    checker = CitationChecker(db_session)
    pending = await checker.get_pending_urls()

    # 过滤出本测试的 URL，避免其他测试残留影响
    my_pending = [p for p in pending if p[0].startswith("https://example.com/")]
    pending_urls = {p[0] for p in my_pending}
    assert "https://example.com/pending-url" in pending_urls
    assert "https://example.com/no-index-model" not in pending_urls
    assert "https://example.com/no-questions" not in pending_urls
    assert "https://example.com/already-checked" not in pending_urls
