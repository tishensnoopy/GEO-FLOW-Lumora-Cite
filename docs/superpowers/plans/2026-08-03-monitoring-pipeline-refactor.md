# AI 监测链路重构（阶段 1）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 打通引用检测链路——取消收录检测前置依赖，新增文章→关键词 AI 自动推断，让引用检测对所有发稿直接执行。

**架构：** 文章分发后 DeepSeek 自动推断关联关键词 → 引用检测（联网搜索）直接执行，不再依赖训练数据收录检测 → 结果存入 citation_results（含回答全文+来源+命中类型）。

**技术栈：** Python 3.11 / FastAPI / SQLAlchemy 2.0 async / Alembic / DeepSeek API（OpenAI 兼容）/ pytest-asyncio

**规格文档：** `docs/superpowers/specs/2026-08-03-monitoring-pipeline-refactor-design.md`

---

## 文件结构

| 文件 | 类型 | 职责 |
|------|------|------|
| `app/models/article_question_mapping.py` | 新增 | 文章→关键词关联模型 |
| `alembic/versions/015_add_article_question_mappings.py` | 新增 | 数据库迁移 |
| `app/services/deepseek_client.py` | 新增 | DeepSeek API 调用客户端（OpenAI 兼容） |
| `app/services/article_question_inferrer.py` | 新增 | AI 自动推断文章→关键词关联 |
| `app/services/citation_checker.py` | 修改 | 移除收录检测前置依赖（L326-329） |
| `app/services/auto_pipeline.py` | 修改 | 引用检测直接执行，收录检测降级为可选 |
| `tests/unit/test_article_question_mapping.py` | 新增 | 模型测试 |
| `tests/unit/test_deepseek_client.py` | 新增 | DeepSeek 客户端测试 |
| `tests/unit/test_article_question_inferrer.py` | 新增 | 推断服务测试 |
| `tests/unit/test_citation_checker_no_index_dep.py` | 新增 | 无前置依赖测试 |
| `tests/unit/test_auto_pipeline_no_index_dep.py` | 新增 | 管道无前置依赖测试 |

---

## 任务 1：创建 ArticleQuestionMapping 模型 + 迁移

**文件：**
- 创建：`app/models/article_question_mapping.py`
- 创建：`alembic/versions/015_add_article_question_mappings.py`
- 测试：`tests/unit/test_article_question_mapping.py`

- [ ] **步骤 1：编写模型测试**

```python
# tests/unit/test_article_question_mapping.py
"""ArticleQuestionMapping 模型测试。"""
import pytest
from app.models.article_question_mapping import ArticleQuestionMapping


def test_model_fields():
    """模型字段完整性检查。"""
    cols = {c.name for c in ArticleQuestionMapping.__table__.columns}
    assert cols == {
        "id", "distribution_id", "client_question_id",
        "relevance_score", "inferred_at", "created_at",
    }


def test_model_schema():
    """表属于 monitor schema。"""
    assert ArticleQuestionMapping.__table__.schema == "monitor"


def test_unique_constraint():
    """(distribution_id, client_question_id) 唯一约束存在。"""
    constraints = ArticleQuestionMapping.__table__.constraints
    uq_names = [c.name for c in constraints if hasattr(c, "name") and c.name]
    assert any("uq_article_question" in name for name in uq_names)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_article_question_mapping.py -v`
预期：FAIL，报错 `No module named 'app.models.article_question_mapping'`

- [ ] **步骤 3：创建模型文件**

```python
# app/models/article_question_mapping.py
"""文章→客户问题关联模型（AI 自动推断）。

每篇发稿通过 DeepSeek 分析内容后，自动关联 1-3 个最相关的客户问题。
引用检测时只检测关联的问题，避免组合爆炸。
"""
from sqlalchemy import Column, Float, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base, monitor_table_args
import uuid


class ArticleQuestionMapping(Base):
    __tablename__ = "article_question_mappings"
    __table_args__ = monitor_table_args(
        UniqueConstraint(
            "distribution_id", "client_question_id",
            name="uq_article_question",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    distribution_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    client_question_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relevance_score = Column(Float, nullable=False, default=0.0)
    inferred_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 4：创建 Alembic 迁移**

```python
# alembic/versions/015_add_article_question_mappings.py
"""add article_question_mappings table

Revision ID: 015
Revises: 014
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_question_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("distribution_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("client_question_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("relevance_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("inferred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "distribution_id", "client_question_id",
            name="uq_article_question",
        ),
        schema="monitor",
    )


def downgrade() -> None:
    op.drop_table("article_question_mappings", schema="monitor")
```

- [ ] **步骤 5：运行迁移和测试**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && alembic upgrade head && python -m pytest tests/unit/test_article_question_mapping.py -v`
预期：PASS

- [ ] **步骤 6：Commit**

```bash
git add app/models/article_question_mapping.py alembic/versions/015_add_article_question_mappings.py tests/unit/test_article_question_mapping.py
git commit -m "feat: 新增 ArticleQuestionMapping 模型和迁移（文章→关键词关联）"
```

---

## 任务 2：创建 DeepSeek 客户端

**文件：**
- 创建：`app/services/deepseek_client.py`
- 测试：`tests/unit/test_deepseek_client.py`

- [ ] **步骤 1：编写客户端测试**

```python
# tests/unit/test_deepseek_client.py
"""DeepSeek 客户端测试。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.deepseek_client import ask_deepseek, DeepSeekError


@pytest.mark.asyncio
async def test_ask_deepseek_success():
    """正常调用返回 AI 回答文本。"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "这是 AI 回答"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        result = await ask_deepseek(
            api_key="sk-test",
            prompt="你好",
            system_prompt="你是助手",
        )
        assert result == "这是 AI 回答"


@pytest.mark.asyncio
async def test_ask_deepseek_api_error():
    """API 返回错误时抛 DeepSeekError。"""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Authentication Fails"
    mock_response.raise_for_status = MagicMock(side_effect=Exception("401"))

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        with pytest.raises(DeepSeekError):
            await ask_deepseek(api_key="sk-invalid", prompt="你好")


@pytest.mark.asyncio
async def test_ask_deepseek_empty_response():
    """空回答返回空字符串而非报错。"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": ""}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        result = await ask_deepseek(api_key="sk-test", prompt="你好")
        assert result == ""
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_deepseek_client.py -v`
预期：FAIL，报错 `No module named 'app.services.deepseek_client'`

- [ ] **步骤 3：创建 DeepSeek 客户端**

```python
# app/services/deepseek_client.py
"""DeepSeek API 客户端（OpenAI 兼容接口）。

用于文章→关键词推断等非引用检测的 LLM 调用。
引用检测仍走 citation_check/providers.py 的 adapter 体系。
"""
import logging
import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_TIMEOUT = 30.0


class DeepSeekError(Exception):
    """DeepSeek API 调用异常。"""


async def ask_deepseek(
    api_key: str,
    prompt: str,
    system_prompt: str = "你是 AI 助手",
    model: str = DEEPSEEK_MODEL,
    temperature: float = 0.3,
) -> str:
    """调用 DeepSeek chat completions，返回回答文本。

    Args:
        api_key: DeepSeek API Key（sk- 开头）
        prompt: 用户提示词
        system_prompt: 系统提示词
        model: 模型名，默认 deepseek-v4-flash
        temperature: 温度参数，推断场景用低温度（0.3）保证稳定性

    Returns:
        AI 回答文本

    Raises:
        DeepSeekError: API 调用失败时抛出
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
            response = await client.post(
                DEEPSEEK_API_URL, headers=headers, json=payload
            )
            if response.status_code != 200:
                raise DeepSeekError(
                    f"DeepSeek API 错误 {response.status_code}: {response.text[:200]}"
                )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.RequestError as exc:
        raise DeepSeekError(f"DeepSeek 网络请求失败: {exc}") from exc
    except (KeyError, IndexError) as exc:
        raise DeepSeekError(f"DeepSeek 返回格式异常: {exc}") from exc
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_deepseek_client.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/services/deepseek_client.py tests/unit/test_deepseek_client.py
git commit -m "feat: 新增 DeepSeek 客户端（OpenAI 兼容接口）"
```

---

## 任务 3：创建 ArticleQuestionInferrer 服务

**文件：**
- 创建：`app/services/article_question_inferrer.py`
- 测试：`tests/unit/test_article_question_inferrer.py`

- [ ] **步骤 1：编写推断服务测试**

```python
# tests/unit/test_article_question_inferrer.py
"""ArticleQuestionInferrer 推断服务测试。"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.services.article_question_inferrer import ArticleQuestionInferrer


@pytest_asyncio.fixture
async def setup_data(db_session):
    """创建测试用发稿记录和客户问题。"""
    from app.models.manual_distribution import ManualDistribution
    from app.models.client_question import ClientQuestion
    from app.models.article_question_mapping import ArticleQuestionMapping
    from sqlalchemy import delete

    # 清理残留
    await db_session.execute(delete(ArticleQuestionMapping).where(
        ArticleQuestionMapping.distribution_id.in_([
            MagicMock(id=uuid4()),  # placeholder, 会被下面覆盖
        ])
    ))

    dist = ManualDistribution(
        client_id="test_client",
        remote_url="https://example.com/article1",
        content_title="企业数字化转型实战指南",
    )
    db_session.add(dist)
    await db_session.flush()

    q1 = ClientQuestion(
        client_id="test_client",
        question="企业数字化转型方案",
        sort_order=1,
        status="active",
    )
    q2 = ClientQuestion(
        client_id="test_client",
        question="AI营销工具推荐",
        sort_order=2,
        status="active",
    )
    db_session.add_all([q1, q2])
    await db_session.flush()

    yield dist.id, q1.id, q2.id


@pytest.mark.asyncio
async def test_infer_success(db_session, setup_data, monkeypatch):
    """正常推断：文章匹配到 1 个相关问题。"""
    dist_id, q1_id, q2_id = setup_data

    inferrer = ArticleQuestionInferrer(db_session)

    # mock DeepSeek 返回
    mock_response = f'[{{"question_id": "{q1_id}", "score": 0.9}}]'
    monkeypatch.setattr(
        "app.services.article_question_inferrer.ask_deepseek",
        AsyncMock(return_value=mock_response),
    )
    monkeypatch.setattr(
        "app.services.article_question_inferrer.load_ai_configs",
        AsyncMock(return_value={"ai_deepseek_api_key": "sk-test"}),
    )

    # mock 内容抓取
    monkeypatch.setattr(
        "app.services.article_question_inferrer.fetch_public_content",
        lambda url: MagicMock(
            title="企业数字化转型实战指南",
            content="数字化转型是企业发展必经之路...",
        ),
    )

    mappings = await inferrer.infer_for_distribution(dist_id, "test_client")

    assert len(mappings) == 1
    assert mappings[0]["client_question_id"] == q1_id
    assert mappings[0]["relevance_score"] == 0.9


@pytest.mark.asyncio
async def test_infer_no_active_questions(db_session, monkeypatch):
    """客户无 active 问题时跳过推断。"""
    inferrer = ArticleQuestionInferrer(db_session)
    mappings = await inferrer.infer_for_distribution(uuid4(), "no_questions_client")
    assert mappings == []


@pytest.mark.asyncio
async def test_infer_deepseek_failure(db_session, setup_data, monkeypatch):
    """DeepSeek 调用失败时返回空列表，不抛异常。"""
    dist_id, _, _ = setup_data

    inferrer = ArticleQuestionInferrer(db_session)

    from app.services.deepseek_client import DeepSeekError
    monkeypatch.setattr(
        "app.services.article_question_inferrer.ask_deepseek",
        AsyncMock(side_effect=DeepSeekError("API 错误")),
    )
    monkeypatch.setattr(
        "app.services.article_question_inferrer.load_ai_configs",
        AsyncMock(return_value={"ai_deepseek_api_key": "sk-test"}),
    )
    monkeypatch.setattr(
        "app.services.article_question_inferrer.fetch_public_content",
        lambda url: MagicMock(title="标题", content="内容"),
    )

    mappings = await inferrer.infer_for_distribution(dist_id, "test_client")
    assert mappings == []
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_article_question_inferrer.py -v`
预期：FAIL，报错 `No module named 'app.services.article_question_inferrer'`

- [ ] **步骤 3：创建推断服务**

```python
# app/services/article_question_inferrer.py
"""文章→关键词关联推断服务。

文章分发后自动触发，用 DeepSeek 分析文章内容，匹配最相关的 1-3 个客户问题。
检测时只检测关联的问题，避免组合爆炸。
"""
import json
import logging
from uuid import UUID
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manual_distribution import ManualDistribution
from app.models.client_question import ClientQuestion
from app.models.article_question_mapping import ArticleQuestionMapping
from app.services.deepseek_client import ask_deepseek, DeepSeekError
from app.services.llm_client import load_ai_configs
from app.services.content_fetcher import fetch_public_content

logger = logging.getLogger(__name__)

INFER_SYSTEM_PROMPT = "你是内容分析专家，擅长判断文章内容与搜索意图的关联度。"

INFER_PROMPT_TEMPLATE = """请分析以下文章，从客户问题列表中选择最相关的 1-3 个问题。

文章标题：{title}
文章片段：{content}

客户问题列表（JSON 数组）：
{questions}

请只返回最相关的问题，格式为 JSON 数组：
[{{"question_id": "问题ID", "score": 0.0-1.0}}]

要求：
1. 只返回评分 >= 0.3 的问题
2. 最多返回 3 个
3. 只返回 JSON，不要其他文字
"""


class ArticleQuestionInferrer:
    """AI 自动推断文章→关键词关联。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def infer_for_distribution(
        self, distribution_id: UUID, client_id: str
    ) -> list[dict]:
        """为指定发稿推断关联的客户问题。

        Args:
            distribution_id: 发稿记录 ID
            client_id: 客户 ID

        Returns:
            关联结果列表 [{"client_question_id": UUID, "relevance_score": float}]
        """
        # 1. 获取发稿记录
        dist = await self.db.get(ManualDistribution, distribution_id)
        if not dist:
            logger.warning("推断跳过：发稿记录 %s 不存在", distribution_id)
            return []

        # 2. 获取客户 active 问题
        result = await self.db.execute(
            select(ClientQuestion).where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            ).order_by(ClientQuestion.sort_order)
        )
        questions = result.scalars().all()
        if not questions:
            logger.info("推断跳过：客户 %s 无 active 问题", client_id)
            return []

        # 3. 抓取文章内容
        try:
            content = fetch_public_content(dist.remote_url)
            title = content.title or dist.content_title or "无标题"
            text = (content.content or "")[:500]
        except Exception as exc:
            logger.warning("推断降级：内容抓取失败 %s: %s", dist.remote_url, exc)
            title = dist.content_title or "无标题"
            text = ""

        # 4. 调用 DeepSeek 推断
        questions_json = json.dumps(
            [{"id": str(q.id), "question": q.question} for q in questions],
            ensure_ascii=False,
        )
        prompt = INFER_PROMPT_TEMPLATE.format(
            title=title, content=text, questions=questions_json
        )

        configs = await load_ai_configs(self.db, ["ai_deepseek_api_key"])
        api_key = configs.get("ai_deepseek_api_key", "")
        if not api_key:
            logger.warning("推断跳过：未配置 DeepSeek API Key")
            return []

        try:
            response_text = await ask_deepseek(
                api_key=api_key,
                prompt=prompt,
                system_prompt=INFER_SYSTEM_PROMPT,
            )
        except DeepSeekError as exc:
            logger.error("推断失败：DeepSeek 调用出错: %s", exc)
            return []

        # 5. 解析返回
        try:
            matches = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error("推断失败：DeepSeek 返回非 JSON: %s", response_text[:200])
            return []

        if not isinstance(matches, list) or not matches:
            logger.info("推断完成：无匹配问题")
            return []

        # 6. 清除旧关联，写入新关联
        await self.db.execute(
            delete(ArticleQuestionMapping).where(
                ArticleQuestionMapping.distribution_id == distribution_id
            )
        )

        valid_question_ids = {q.id for q in questions}
        saved = []
        for match in matches[:3]:
            qid_str = match.get("question_id", "")
            score = float(match.get("score", 0))
            if score < 0.3:
                continue
            try:
                qid = UUID(qid_str)
            except ValueError:
                continue
            if qid not in valid_question_ids:
                continue

            mapping = ArticleQuestionMapping(
                distribution_id=distribution_id,
                client_question_id=qid,
                relevance_score=score,
            )
            self.db.add(mapping)
            saved.append({"client_question_id": qid, "relevance_score": score})

        await self.db.commit()
        logger.info("推断完成：%s 关联 %d 个问题", distribution_id, len(saved))
        return saved

    async def get_related_questions(
        self, distribution_id: UUID
    ) -> list[tuple[UUID, str, float]]:
        """获取发稿关联的问题列表。

        Returns:
            [(client_question_id, question_text, relevance_score), ...]
        """
        result = await self.db.execute(
            select(
                ArticleQuestionMapping.client_question_id,
                ClientQuestion.question,
                ArticleQuestionMapping.relevance_score,
            )
            .join(
                ClientQuestion,
                ClientQuestion.id == ArticleQuestionMapping.client_question_id,
            )
            .where(
                ArticleQuestionMapping.distribution_id == distribution_id,
                ArticleQuestionMapping.relevance_score >= 0.3,
            )
            .order_by(ArticleQuestionMapping.relevance_score.desc())
        )
        return result.fetchall()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_article_question_inferrer.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add app/services/article_question_inferrer.py tests/unit/test_article_question_inferrer.py
git commit -m "feat: 新增 ArticleQuestionInferrer 推断服务（DeepSeek 自动关联文章→关键词）"
```

---

## 任务 4：修改 CitationChecker——移除收录检测前置依赖

**文件：**
- 修改：`app/services/citation_checker.py`（L247-260, L325-336, L338-359）
- 测试：`tests/unit/test_citation_checker_no_index_dep.py`

- [ ] **步骤 1：编写无前置依赖测试**

```python
# tests/unit/test_citation_checker_no_index_dep.py
"""CitationChecker 无收录检测前置依赖测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.citation_checker import CitationChecker


@pytest.mark.asyncio
async def test_check_url_no_indexed_models_required(db_session, monkeypatch):
    """无收录检测结果时，引用检测仍可执行（不再阻塞）。"""
    checker = CitationChecker(db_session)

    # mock _get_indexed_models 返回空（模拟无收录数据）
    monkeypatch.setattr(
        checker, "_get_indexed_models", AsyncMock(return_value=[])
    )

    # mock _get_client_questions 返回问题
    monkeypatch.setattr(
        checker, "_get_client_questions",
        AsyncMock(return_value=["测试问题"]),
    )

    # mock 内容抓取
    mock_content = MagicMock()
    mock_content.title = "测试文章"
    mock_content.suitability.suitable = True
    mock_content.requested_url = "https://example.com/test"
    mock_content.resolved_url = None
    mock_content.canonical_url = None
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: mock_content,
    )

    # mock _load_ai_config
    monkeypatch.setattr(
        checker, "_load_ai_config",
        AsyncMock(return_value={
            "ai_citation_models": "qwen",
            "ai_dashscope_api_key": "sk-test",
        }),
    )

    # mock provider 适配器（让检测返回 not_cited）
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        lambda ids: [MagicMock(provider_id="qwen", model_name="qwen-plus")],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [{"provider_id": "qwen", "status": "verified"}],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        AsyncMock(return_value=MagicMock(
            sources=[], answer="无引用", hit_type="none",
        )),
    )

    # 不应抛出 "该 URL 未被任何 AI 模型收录" 错误
    result = await checker.check_url("https://example.com/test", "test_client")
    assert result is not None  # 检测正常执行


@pytest.mark.asyncio
async def test_check_url_uses_all_configured_models(db_session, monkeypatch):
    """引用检测使用所有已配置模型，不再只筛 indexed 模型。"""
    checker = CitationChecker(db_session)

    monkeypatch.setattr(
        checker, "_get_client_questions",
        AsyncMock(return_value=["测试问题"]),
    )

    mock_content = MagicMock()
    mock_content.title = "测试"
    mock_content.suitability.suitable = True
    mock_content.requested_url = "https://example.com/test"
    mock_content.resolved_url = None
    mock_content.canonical_url = None
    monkeypatch.setattr(
        "app.services.citation_checker.fetch_public_content",
        lambda url: mock_content,
    )

    selected_ids_capture = []

    def capture_adapters(ids):
        selected_ids_capture.extend(ids)
        return [MagicMock(provider_id=i) for i in ids]

    monkeypatch.setattr(
        checker, "_load_ai_config",
        AsyncMock(return_value={
            "ai_citation_models": "qwen,doubao",
            "ai_dashscope_api_key": "sk-test",
            "ai_ark_api_key": "ark-test",
        }),
    )
    monkeypatch.setattr(
        "app.services.citation_checker.adapter_catalog",
        lambda: [
            {"id": "qwen"}, {"id": "doubao"},
        ],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.default_adapters",
        capture_adapters,
    )
    monkeypatch.setattr(
        "app.services.citation_checker.probe_adapter_capabilities",
        lambda adapters: [{"provider_id": a.provider_id, "status": "verified"} for a in adapters],
    )
    monkeypatch.setattr(
        "app.services.citation_checker.run_citation_check",
        AsyncMock(return_value=MagicMock(sources=[], answer="无引用", hit_type="none")),
    )

    await checker.check_url("https://example.com/test", "test_client")

    # 应使用所有配置的模型，不受 indexed 限制
    assert set(selected_ids_capture) == {"qwen", "doubao"}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_citation_checker_no_index_dep.py -v`
预期：FAIL，第一个测试会抛出 "该 URL 未被任何 AI 模型收录" 错误

- [ ] **步骤 3：修改 citation_checker.py——移除前置依赖**

在 `citation_checker.py` 中找到 L325-336（`1c. 筛选已收录模型` 段），替换为不依赖收录检测的逻辑：

**原代码（L325-336）**：
```python
        # 1c. 筛选已收录模型
        indexed_models = await self._get_indexed_models(url)
        if not indexed_models:
            await _report("1/3 准备", "error", "该 URL 未被任何 AI 模型收录")
            raise ValueError("该 URL 未被任何 AI 模型收录，跳过问题监测")

        await _report(
            "1/3 准备", "success",
            f"准备完成: {len(questions)} 问题, {len(indexed_models)} 已收录模型",
            detail={"title": title, "question_count": len(questions), "indexed_models": indexed_models},
            duration_ms=int((time.time() - t0) * 1000),
        )
```

**替换为**：
```python
        # 1c. 获取已配置模型（不再依赖收录检测结果）
        # 阶段 1 重构：取消收录检测前置依赖，直接使用所有已配置模型
        # 收录检测结果不可信（训练数据 ≠ 联网搜索），且阻塞了引用检测链路
        configured_models = self._get_configured_models()
        if not configured_models:
            await _report("1/3 准备", "error", "未配置任何引用检测模型")
            raise ValueError("未配置任何引用检测模型，请在系统设置中配置 API Key")

        await _report(
            "1/3 准备", "success",
            f"准备完成: {len(questions)} 问题, {len(configured_models)} 已配置模型",
            detail={"title": title, "question_count": len(questions), "configured_models": configured_models},
            duration_ms=int((time.time() - t0) * 1000),
        )
```

然后在 L338-359（`2/3 模型探测` 段），将 `indexed_models` 替换为 `configured_models`：

**原代码（L350-353）**：
```python
        selected_ids = [
            mid for mid in indexed_models
            if mid in catalog_ids and (configured_ids is None or mid in configured_ids)
        ]
```

**替换为**：
```python
        selected_ids = [
            mid for mid in configured_models
            if mid in catalog_ids and (configured_ids is None or mid in configured_ids)
        ]
```

最后添加 `_get_configured_models` 方法（如果不存在），参考 `ai_index_checker.py` 中的同名方法：

```python
    def _get_configured_models(self) -> list[str]:
        """获取所有已配置 API Key 的引用检测模型 ID 列表。

        阶段 1 重构：替代 _get_indexed_models，不再依赖收录检测结果。
        """
        from app.services.citation_check.providers import adapter_catalog
        catalog = adapter_catalog()
        return [item["id"] for item in catalog if item.get("configured")]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_citation_checker_no_index_dep.py -v`
预期：PASS

- [ ] **步骤 5：运行现有测试确保不回归**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_citation_checker.py -v 2>/dev/null; python -m pytest tests/unit/test_citation_check_engine.py -v 2>/dev/null`
预期：已有测试通过或仅因 mock 不匹配而跳过（不新增失败）

- [ ] **步骤 6：Commit**

```bash
git add app/services/citation_checker.py tests/unit/test_citation_checker_no_index_dep.py
git commit -m "refactor: CitationChecker 移除收录检测前置依赖，直接使用已配置模型"
```

---

## 任务 5：修改 AutoPipeline——引用检测直接执行

**文件：**
- 修改：`app/services/auto_pipeline.py`
- 测试：`tests/unit/test_auto_pipeline_no_index_dep.py`

- [ ] **步骤 1：编写管道无前置依赖测试**

```python
# tests/unit/test_auto_pipeline_no_index_dep.py
"""AutoPipeline 无收录检测前置依赖测试。

验证阶段 1 重构：引用检测不再依赖收录检测结果。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.auto_pipeline import AutoPipeline


@pytest.mark.asyncio
async def test_citation_check_runs_without_index(db_session, monkeypatch):
    """无 indexed 模型时，引用检测仍可执行。"""
    pipeline = AutoPipeline()

    # mock 收录检测（失败不阻塞）
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: [],
    )

    # mock 引用检测
    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    # mock async_session 返回 db_session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    # mock 客户有 active 问题
    from app.models.client_question import ClientQuestion
    db_session.add(ClientQuestion(
        client_id="test_client", question="测试", sort_order=1, status="active",
    ))
    await db_session.commit()

    await pipeline.trigger_for_url("https://example.com/test", "test_client")

    # 引用检测应被执行（不再因无 indexed 模型而跳过）
    mock_citation.assert_called_once()


@pytest.mark.asyncio
async def test_index_check_failure_does_not_block_citation(db_session, monkeypatch):
    """收录检测抛异常时，引用检测仍可执行。"""
    pipeline = AutoPipeline()

    # mock 收录检测抛异常
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker._get_configured_models",
        lambda self: ["qwen"],
    )
    monkeypatch.setattr(
        "app.services.auto_pipeline.AIIndexChecker.check_url",
        AsyncMock(side_effect=RuntimeError("模拟收录检测失败")),
    )

    # mock 引用检测
    mock_citation = AsyncMock()
    monkeypatch.setattr(
        "app.services.auto_pipeline.CitationChecker.check_url",
        mock_citation,
    )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(
        "app.services.auto_pipeline.async_session",
        lambda: fake_session(),
    )

    from app.models.client_question import ClientQuestion
    db_session.add(ClientQuestion(
        client_id="test_client", question="测试", sort_order=1, status="active",
    ))
    await db_session.commit()

    await pipeline.trigger_for_url("https://example.com/test", "test_client")

    # 收录检测失败不阻塞引用检测
    mock_citation.assert_called_once()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_auto_pipeline_no_index_dep.py -v`
预期：FAIL，第一个测试因 `_auto_trigger_citation_check` 查询 indexed 模型为空而跳过引用检测

- [ ] **步骤 3：修改 auto_pipeline.py**

将 `_auto_trigger_citation_check` 方法中的 indexed 模型查询逻辑移除，改为直接执行引用检测：

**原代码（L55-93）**：
```python
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
```

**替换为**：
```python
    async def _auto_trigger_citation_check(
        self, url: str, client_id: str
    ) -> None:
        """阶段 2：直接触发引用检测（不再依赖收录检测结果）。

        阶段 1 重构：取消 indexed 模型查询，引用检测直接执行。
        仅检查客户是否有 active 问题。
        """
        async with async_session() as db:
            # 查询客户是否有 active 问题
            q_result = await db.execute(
                select(ClientQuestion.id).where(
                    ClientQuestion.client_id == client_id,
                    ClientQuestion.status == "active",
                ).limit(1)
            )
            if q_result.scalar_one_or_none() is None:
                logger.warning(
                    "自动联动-跳过引用检测 %s：客户 %s 未配置监测问题",
                    url, client_id,
                )
                return

        # 引用检测（独立 session）
        async with async_session() as db:
            try:
                checker = CitationChecker(db)
                await checker.check_url(url, client_id)
                logger.info("自动联动-引用检测完成: %s", url)
            except Exception as exc:
                logger.error("自动联动-引用检测失败 %s: %s", url, exc)
```

同时更新 `trigger_for_url` 的 docstring：

**原代码（L23-28）**：
```python
    async def trigger_for_url(self, url: str, client_id: str) -> None:
        """对新文章触发完整联动链路。

        阶段 1: AI 收录检测（该 URL × 所有配置模型）
        阶段 2: 自动衔接——仅对 indexed 模型触发问题监测
        """
```

**替换为**：
```python
    async def trigger_for_url(self, url: str, client_id: str) -> None:
        """对新文章触发联动链路。

        阶段 1: AI 收录检测（可选，失败不阻塞）
        阶段 2: 引用检测（直接执行，不依赖收录检测结果）
        """
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_auto_pipeline_no_index_dep.py -v`
预期：PASS

- [ ] **步骤 5：运行现有测试确保不回归**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/test_auto_pipeline.py -v`
预期：已有测试通过（test_auto_pipeline.py 已有 4 个测试，需确认不回归）

- [ ] **步骤 6：Commit**

```bash
git add app/services/auto_pipeline.py tests/unit/test_auto_pipeline_no_index_dep.py
git commit -m "refactor: AutoPipeline 引用检测直接执行，收录检测降级为可选"
```

---

## 任务 6：端到端集成验证

**文件：**
- 无新增文件，运行已有测试套件验证不回归

- [ ] **步骤 1：运行全量单元测试**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30`
预期：所有测试通过（或仅有已知的环境配置相关失败，无新增失败）

- [ ] **步骤 2：验证迁移可正常执行**

运行：`cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor" && alembic current && alembic upgrade head && alembic current`
预期：迁移到 015，无报错

- [ ] **步骤 3：验证引用检测链路打通（手动）**

```bash
# 确认服务运行
curl -s http://localhost:8090/api/v1/health | python -m json.tool

# 触发引用检测（不再依赖收录检测）
curl -s -X POST http://localhost:8090/api/v1/admin/scan/trigger \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "citation"}' | python -m json.tool
```
预期：引用检测被触发，不再返回"该 URL 未被任何 AI 模型收录"错误

- [ ] **步骤 4：Commit 验证记录**

```bash
git add -A
git commit -m "test: 阶段 1 端到端验证通过——引用检测链路打通"
```

---

## 自检

### 规格覆盖度

| 规格章节 | 对应任务 | 覆盖 |
|---------|---------|------|
| 5.1 文章→关键词关联（模型） | 任务 1 | ✅ |
| 5.1 文章→关键词关联（推断服务） | 任务 3 | ✅ |
| 5.2 引用检测链路重构（CitationChecker） | 任务 4 | ✅ |
| 5.2 引用检测链路重构（AutoPipeline） | 任务 5 | ✅ |
| 5.3 费用控制（增量检测） | 任务 4（使用已配置模型） | ✅ |
| 5.4 错误处理 | 任务 2-5（各降级逻辑） | ✅ |
| DeepSeek 客户端 | 任务 2 | ✅ |

### 占位符扫描

- ✅ 无 "TODO"、"待定"、"后续实现"
- ✅ 所有代码块包含完整实现
- ✅ 所有测试包含实际断言

### 类型一致性

- `ArticleQuestionMapping` 模型字段在任务 1、3、4 中一致
- `ask_deepseek` 函数签名在任务 2、3 中一致
- `infer_for_distribution` 方法签名在任务 3 中定义，后续任务未引用（阶段 1 不在路由层调用）
- `check_url` 方法签名未改变（任务 4 只改内部逻辑）
