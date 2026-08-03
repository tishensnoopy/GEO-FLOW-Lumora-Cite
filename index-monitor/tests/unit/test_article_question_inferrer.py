"""ArticleQuestionInferrer 单元测试。

通过 TDD 编写：本文件先于实现存在，验证其失败后再实现服务。

外部依赖全部 mock：
- fetch_public_content（同步抓取，经 asyncio.to_thread 调用）
- ask_deepseek（异步 LLM 调用）
- load_ai_configs（DB 配置加载）

DB 操作走真实 PostgreSQL（db_session fixture），保证写入/查询逻辑被真实验证。
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.models.article_question_mapping import ArticleQuestionMapping
from app.models.client_question import ClientQuestion
from app.models.manual_distribution import ManualDistribution
from app.services.article_question_inferrer import ArticleQuestionInferrer
from app.services.deepseek_client import DeepSeekError

CLIENT_ID = "client_inferrer_a"


def _make_fetched(title: str, content: str) -> MagicMock:
    """构造 fetch_public_content 的返回值 mock（仅用 .title / .text）。"""
    fc = MagicMock()
    fc.title = title
    fc.text = content
    return fc


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(db_session):
    """每测试前清理相关表，保证测试间数据隔离。"""
    await db_session.execute(text("DELETE FROM monitor.article_question_mappings"))
    await db_session.execute(
        text("DELETE FROM monitor.client_questions WHERE client_id = :cid"),
        {"cid": CLIENT_ID},
    )
    await db_session.execute(
        text("DELETE FROM monitor.manual_distributions WHERE client_id = :cid"),
        {"cid": CLIENT_ID},
    )
    await db_session.commit()
    yield


async def _seed_distribution(db_session, *, url="https://example.com/article-1", title="原标题"):
    dist = ManualDistribution(
        client_id=CLIENT_ID,
        remote_url=url,
        status="synced",
        content_title=title,
    )
    db_session.add(dist)
    await db_session.commit()
    await db_session.refresh(dist)
    return dist


async def _seed_questions(db_session, count: int):
    qs = []
    for i in range(count):
        q = ClientQuestion(
            client_id=CLIENT_ID,
            question=f"问题 {i + 1}",
            sort_order=i + 1,
            status="active",
        )
        db_session.add(q)
        qs.append(q)
    await db_session.commit()
    for q in qs:
        await db_session.refresh(q)
    return qs


# ---------------------------------------------------------------------------
# infer_for_distribution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_infer_happy_path_writes_mappings(db_session):
    """正常流程：抓取内容 → DeepSeek 返回 2 个相关问题 → 写入 2 条关联。"""
    dist = await _seed_distribution(db_session)
    qs = await _seed_questions(db_session, 3)

    deepseek_resp = json.dumps([
        {"question_id": str(qs[0].id), "score": 0.9},
        {"question_id": str(qs[1].id), "score": 0.5},
    ])

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("文章标题", "文章正文内容")
        mock_ask.return_value = deepseek_resp
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert len(mappings) == 2
    returned_qids = {str(m.client_question_id) for m in mappings}
    assert returned_qids == {str(qs[0].id), str(qs[1].id)}
    # 评分被持久化
    score_by_qid = {str(m.client_question_id): m.relevance_score for m in mappings}
    assert score_by_qid[str(qs[0].id)] == pytest.approx(0.9)
    assert score_by_qid[str(qs[1].id)] == pytest.approx(0.5)

    # DB 中确实有 2 条关联
    result = await db_session.execute(
        select(ArticleQuestionMapping).where(
            ArticleQuestionMapping.distribution_id == dist.id
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 2

    # DeepSeek 被调用一次，prompt 含标题与问题列表
    mock_ask.assert_awaited_once()
    _args, kwargs = mock_ask.call_args
    prompt_arg = mock_ask.call_args.args[1] if len(mock_ask.call_args.args) > 1 else kwargs.get("prompt")
    assert "文章标题" in prompt_arg
    assert "问题 1" in prompt_arg


@pytest.mark.asyncio
async def test_infer_no_active_questions_returns_empty(db_session):
    """客户无 active 问题时返回空列表，且不调用 DeepSeek。"""
    dist = await _seed_distribution(db_session)
    # 不创建任何问题

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert mappings == []
    mock_ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_infer_deepseek_error_returns_empty(db_session):
    """DeepSeek 抛异常时降级返回空列表，不抛异常，不写入关联。"""
    dist = await _seed_distribution(db_session)
    await _seed_questions(db_session, 2)

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_ask.side_effect = DeepSeekError("API 宕机")
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert mappings == []
    result = await db_session.execute(
        select(ArticleQuestionMapping).where(
            ArticleQuestionMapping.distribution_id == dist.id
        )
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_infer_invalid_json_returns_empty(db_session):
    """DeepSeek 返回非 JSON 文本时降级返回空列表。"""
    dist = await _seed_distribution(db_session)
    await _seed_questions(db_session, 2)

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_ask.return_value = "这不是 JSON，抱歉"
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert mappings == []


@pytest.mark.asyncio
async def test_infer_clears_old_mappings_before_writing(db_session):
    """重新推断前清除该 distribution 的旧关联，避免残留。"""
    dist = await _seed_distribution(db_session)
    qs = await _seed_questions(db_session, 3)

    # 预置一条旧关联（指向 qs[2]，本次推断不会再选它）
    old = ArticleQuestionMapping(
        distribution_id=dist.id,
        client_question_id=qs[2].id,
        relevance_score=0.99,
    )
    db_session.add(old)
    await db_session.commit()

    deepseek_resp = json.dumps([
        {"question_id": str(qs[0].id), "score": 0.8},
    ])

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_ask.return_value = deepseek_resp
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert len(mappings) == 1
    assert str(mappings[0].client_question_id) == str(qs[0].id)
    # 旧关联（指向 qs[2]）已被清除
    result = await db_session.execute(
        select(ArticleQuestionMapping).where(
            ArticleQuestionMapping.distribution_id == dist.id
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert str(rows[0].client_question_id) == str(qs[0].id)


@pytest.mark.asyncio
async def test_infer_filters_low_score_and_limits_to_three(db_session):
    """评分 < 0.3 的问题被过滤，最多保留 3 个。"""
    dist = await _seed_distribution(db_session)
    qs = await _seed_questions(db_session, 5)

    # 5 个问题：2 个低分（过滤），3 个高分（保留，按 score 降序取前 3）
    deepseek_resp = json.dumps([
        {"question_id": str(qs[0].id), "score": 0.1},  # 过滤
        {"question_id": str(qs[1].id), "score": 0.95},
        {"question_id": str(qs[2].id), "score": 0.8},
        {"question_id": str(qs[3].id), "score": 0.2},  # 过滤
        {"question_id": str(qs[4].id), "score": 0.7},
    ])

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_ask.return_value = deepseek_resp
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert len(mappings) == 3
    kept_qids = {str(m.client_question_id) for m in mappings}
    assert kept_qids == {str(qs[1].id), str(qs[2].id), str(qs[4].id)}


@pytest.mark.asyncio
async def test_infer_too_many_high_score_limits_to_three(db_session):
    """4 个问题都高分时仍只返回 3 个（按 score 降序取前 3）。"""
    dist = await _seed_distribution(db_session)
    qs = await _seed_questions(db_session, 4)

    deepseek_resp = json.dumps([
        {"question_id": str(qs[0].id), "score": 0.4},
        {"question_id": str(qs[1].id), "score": 0.95},
        {"question_id": str(qs[2].id), "score": 0.8},
        {"question_id": str(qs[3].id), "score": 0.7},
    ])

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_ask.return_value = deepseek_resp
        mock_cfg.return_value = {"ai_deepseek_api_key": "sk-test"}

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert len(mappings) == 3
    # 取 score 最高的 3 个：qs[1]=0.95, qs[2]=0.8, qs[3]=0.7
    kept_qids = {str(m.client_question_id) for m in mappings}
    assert kept_qids == {str(qs[1].id), str(qs[2].id), str(qs[3].id)}


@pytest.mark.asyncio
async def test_infer_distribution_not_found_raises(db_session):
    """发稿记录不存在时抛 ValueError。"""
    await _seed_questions(db_session, 1)
    service = ArticleQuestionInferrer(db_session)
    with pytest.raises(ValueError, match="发稿记录"):
        await service.infer_for_distribution(str(uuid.uuid4()), CLIENT_ID)


@pytest.mark.asyncio
async def test_infer_no_api_key_returns_empty(db_session):
    """未配置 DeepSeek API key 时降级返回空列表，不抛异常。"""
    dist = await _seed_distribution(db_session)
    await _seed_questions(db_session, 2)

    with patch("app.services.article_question_inferrer.fetch_public_content") as mock_fetch, \
         patch("app.services.article_question_inferrer.ask_deepseek", new_callable=AsyncMock) as mock_ask, \
         patch("app.services.article_question_inferrer.load_ai_configs", new_callable=AsyncMock) as mock_cfg:
        mock_fetch.return_value = _make_fetched("标题", "正文")
        mock_cfg.return_value = {}  # 无 api key

        service = ArticleQuestionInferrer(db_session)
        mappings = await service.infer_for_distribution(str(dist.id), CLIENT_ID)

    assert mappings == []
    mock_ask.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_related_questions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_related_questions_returns_joined(db_session):
    """get_related_questions 返回该 distribution 关联的 ClientQuestion 列表。"""
    dist = await _seed_distribution(db_session)
    qs = await _seed_questions(db_session, 3)

    # 关联 qs[0] 和 qs[2]
    db_session.add(ArticleQuestionMapping(
        distribution_id=dist.id, client_question_id=qs[0].id, relevance_score=0.9,
    ))
    db_session.add(ArticleQuestionMapping(
        distribution_id=dist.id, client_question_id=qs[2].id, relevance_score=0.5,
    ))
    await db_session.commit()

    service = ArticleQuestionInferrer(db_session)
    related = await service.get_related_questions(str(dist.id))

    related_questions = {q.question for q in related}
    assert related_questions == {"问题 1", "问题 3"}


@pytest.mark.asyncio
async def test_get_related_questions_empty_when_no_mappings(db_session):
    """无关联时返回空列表。"""
    dist = await _seed_distribution(db_session)

    service = ArticleQuestionInferrer(db_session)
    related = await service.get_related_questions(str(dist.id))
    assert related == []
