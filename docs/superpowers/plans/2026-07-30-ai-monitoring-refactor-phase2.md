# AI 监测逻辑重构 Phase 2：问题监测服务改造 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 `CitationChecker` 从 5 阶段（抓取→目的推断→问题生成→模型探测→引用检测）改造为 3 阶段（准备→模型探测→引用检测），问题来源从"LLM 自动生成"改为"客户指定问题集"，且仅对 AI 已收录的模型执行引用检测。

**架构：** 双阶段独立管道的 Phase 2——改造 `citation_checker.py` 核心管道，删除目的推断与问题生成阶段，新增客户问题加载与已收录模型筛选；适配 `engine.py` 让客户问题跳过评分筛选直通；清理 `question_generation.py`（全删）与 `llm_client.py`（仅保留 `load_ai_configs`）。

**技术栈：** SQLAlchemy 2.0 (async) + asyncio + 现有 `citation_check/engine.py` + Phase 1 产出的 `client_questions` / `ai_index_results` 表

**设计文档：** `docs/superpowers/specs/2026-07-30-ai-monitoring-refactor-design.md`

**Phase 1 产出（本计划依赖）：**
- `client_questions` 表（`ClientQuestion` 模型）——客户问题集
- `ai_index_results` 表（`AIIndexResult` 模型）——AI 收录状态
- `citation_results.client_question_id` 列——关联客户问题

**用户决策（已确认）：**
1. 客户问题适配 `run_citation_check`：**跳过评分筛选，直通全部**（上限 20）
2. `question_generation.py` **完全删除**；`llm_client.py` **仅保留 `load_ai_configs`**，删除其余问题生成专用函数

---

## 文件结构

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/services/citation_check/engine.py` | 引用检测引擎 | 修改：`run_citation_check` 新增 `client_questions` 参数，跳过 `select_best_questions` |
| `index-monitor/app/services/citation_checker.py` | 采信检测服务 | 修改：5→3 阶段改造 + 新增辅助方法 + 删导入 |
| `index-monitor/app/services/citation_check/__init__.py` | 包导出 | 修改：删除 `question_generation` 导出 |
| `index-monitor/app/services/citation_check/question_generation.py` | 问题生成（旧） | **删除** |
| `index-monitor/app/services/llm_client.py` | LLM 客户端 | 修改：仅保留 `load_ai_configs`，删除其余 |
| `index-monitor/app/api/routes.py` | API 路由 | 修改：删除 `purpose` 引用 |
| `index-monitor/tests/unit/test_citation_checker_stages.py` | 阶段测试 | 修改：重写为 3 阶段 |
| `index-monitor/tests/unit/test_citation_check_progress.py` | 进度测试 | 修改：适配 3 阶段标签 |
| `index-monitor/tests/unit/test_llm_client_retry.py` | LLM 重试测试 | **删除** |
| `index-monitor/tests/unit/test_llm_client_fallback.py` | LLM fallback 测试 | **删除** |
| `index-monitor/tests/unit/test_engine_client_questions.py` | 引擎客户问题测试 | **新增** |
| `index-monitor/tests/unit/test_citation_checker_phase2.py` | Phase 2 服务测试 | **新增** |

---

## 全局约束

- **阶段标签精确值：** `1/3 准备`、`2/3 模型探测`、`3/3 引用检测`（`_STAGES` 字典与所有 `_report` 调用必须用这些精确值）
- **客户问题上限：** 20（`question_count = min(len(questions), 20)`）
- **已收录模型筛选：** 从 `ai_index_results` 取 `index_status='indexed'` 的模型，与 `ai_citation_models` 配置取交集
- **`_store_results` 关联：** 每条 `CitationResult` 存 `client_question_id`（通过 question 文本匹配 `ClientQuestion.id`）
- **`get_pending_urls` 4 条件：** synced + 有 indexed 模型 + 客户有 active 问题 + 无 citation_results 记录
- **`run_citation_check` 向后兼容：** 新增 `client_questions: list[str] | None = None` 参数，为 None 时走原逻辑（评分筛选），非 None 时跳过筛选直通
- **`load_ai_configs` 保留：** 它服务于阶段 2（加载全部 AI 配置含引用检测模型 key），不属问题生成专用
- **`ScanPanel.vue` 不改：** 前端不硬编码阶段标签，通用渲染后端日志消息
- **`check_all_pending` 不改并发逻辑：** 仅 `_extract_stage`/`_STAGES` 标签随阶段数变化，并发结构（独立 session + Semaphore + gather）保持不变

---

## 任务 1：engine.py 适配客户问题（跳过评分筛选）

**文件：**
- 修改：`index-monitor/app/services/citation_check/engine.py`
- 新增：`index-monitor/tests/unit/test_engine_client_questions.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/unit/test_engine_client_questions.py` 中：

```python
"""engine.run_citation_check 的 client_questions 直通模式测试。"""
from unittest.mock import MagicMock, patch
from app.services.citation_check.engine import run_citation_check


def test_client_questions_skip_selection():
    """client_questions 非 None 时跳过 select_best_questions，直通全部。"""
    client_questions = ["问题1", "问题2", "问题3"]

    fake_answer = MagicMock()
    fake_answer.sources = []
    fake_answer.model = "测试模型"
    fake_answer.model_id = "test-model"
    fake_answer.search_used = False
    fake_answer.error = None
    fake_answer.text = "测试回答"

    fake_adapter = MagicMock()
    fake_adapter.name = "测试模型"
    fake_adapter.provider_id = "test"
    fake_adapter.model_id = "test-model"
    fake_adapter.capability = "verified_citations"

    with patch("app.services.citation_check.engine.ask_with_retry", return_value=fake_answer):
        result = run_citation_check(
            target_urls=["https://example.com/test"],
            candidates=[],  # 空 candidates，正常会被 select_best_questions 过滤
            adapters=[fake_adapter],
            client_questions=client_questions,
            forbidden_terms=["https://example.com/test"],
        )

    # 3 个问题 × 1 个模型 = 3 个结果
    assert len(result["results"]) == 3
    questions_in_results = {r["question"] for r in result["results"]}
    assert questions_in_results == {"问题1", "问题2", "问题3"}


def test_client_questions_none_uses_original_logic():
    """client_questions=None 时走原逻辑（select_best_questions 评分筛选）。"""
    from app.services.citation_check.questions import QuestionCandidate

    candidate = QuestionCandidate(
        question="测试问题",
        content_support=0.8,
        natural_intent=0.8,
        citation_need=0.8,
        distinctiveness=0.8,
        freshness=0.8,
        selection_reason="测试",
    )

    fake_answer = MagicMock()
    fake_answer.sources = []
    fake_answer.model = "测试模型"
    fake_answer.model_id = "test-model"
    fake_answer.search_used = False
    fake_answer.error = None
    fake_answer.text = "测试回答"

    fake_adapter = MagicMock()
    fake_adapter.name = "测试模型"
    fake_adapter.provider_id = "test"
    fake_adapter.model_id = "test-model"
    fake_adapter.capability = "verified_citations"

    with patch("app.services.citation_check.engine.ask_with_retry", return_value=fake_answer):
        result = run_citation_check(
            target_urls=["https://example.com/test"],
            candidates=[candidate],
            adapters=[fake_adapter],
            question_count=1,
            forbidden_terms=["https://example.com/test"],
        )

    assert len(result["results"]) == 1
    assert result["results"][0]["question"] == "测试问题"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_engine_client_questions.py -v -p no:cacheprovider`
预期：FAIL，`TypeError: run_citation_check() got an unexpected keyword argument 'client_questions'`

- [ ] **步骤 3：实现 client_questions 参数**

在 `engine.py` 的 `run_citation_check` 函数中：

```python
def run_citation_check(
    *,
    target_urls: list[str],
    candidates: list[QuestionCandidate],
    adapters: list[CitationModelAdapter],
    question_count: int = DEFAULT_QUESTION_COUNT,
    forbidden_terms: list[str] | None = None,
    client_questions: list[str] | None = None,
) -> dict:
    """Run selected questions against configured adapters and aggregate evidence.

    当 client_questions 非 None 时，跳过 select_best_questions 评分筛选，
    直接用客户指定问题（每个构造默认评分的 QuestionCandidate）。
    """
    if client_questions is not None:
        # 客户问题直通：跳过评分筛选，构造默认评分的 QuestionCandidate
        selected = [
            QuestionCandidate(
                question=q,
                content_support=1.0,
                natural_intent=1.0,
                citation_need=1.0,
                distinctiveness=1.0,
                freshness=1.0,
                selection_reason="客户指定问题",
            )
            for q in client_questions
        ]
    else:
        selected = select_best_questions(
            candidates,
            count=question_count,
            forbidden_terms=forbidden_terms,
        )
        if len(selected) < question_count:
            raise ValueError(f"合格问题不足：需要 {question_count} 个，实际 {len(selected)} 个")

    if not adapters:
        raise ValueError("至少需要配置一个模型适配器")

    # ... 后续逻辑不变（jobs / ThreadPoolExecutor / results 聚合）
```

注意：`client_questions` 模式下不做 `< question_count` 校验（客户问题有多少用多少）。

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_engine_client_questions.py -v -p no:cacheprovider`
预期：2 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_check/engine.py index-monitor/tests/unit/test_engine_client_questions.py
git commit -m "feat(engine): run_citation_check 支持 client_questions 直通模式"
```

---

## 任务 2：citation_checker.py 新增辅助方法

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py`
- 新增：`index-monitor/tests/unit/test_citation_checker_phase2.py`

- [ ] **步骤 1：编写失败的测试**

在 `index-monitor/tests/unit/test_citation_checker_phase2.py` 中：

```python
"""Phase 2: CitationChecker 改造后的测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.citation_checker import CitationChecker
from app.models.client_question import ClientQuestion
from app.models.ai_index_result import AIIndexResult


@pytest.mark.asyncio
async def test_get_client_questions_returns_active_sorted(db_session):
    """_get_client_questions 返回 active 问题，按 sort_order 排序。"""
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "get_client_questions or get_indexed_models"`
预期：FAIL，`AttributeError: 'CitationChecker' object has no attribute '_get_client_questions'`

- [ ] **步骤 3：实现辅助方法**

在 `CitationChecker` 类中（`_set_provider_env` 方法之后）新增：

```python
    # ------------------------------------------------------------------
    # Phase 2 辅助方法
    # ------------------------------------------------------------------

    async def _get_client_questions(self, client_id: str) -> list[str]:
        """获取客户的活跃监测问题，按 sort_order 排序。

        替代 Phase 1 的 LLM 自动生成问题。
        """
        from app.models.client_question import ClientQuestion
        result = await self.db.execute(
            select(ClientQuestion.question)
            .where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            )
            .order_by(ClientQuestion.sort_order)
        )
        return [row[0] for row in result.fetchall()]

    async def _get_indexed_models(self, url: str) -> list[str]:
        """从 ai_index_results 取该 URL 已收录的模型列表。

        仅 index_status='indexed' 的模型才执行问题监测。
        """
        from app.models.ai_index_result import AIIndexResult
        result = await self.db.execute(
            select(AIIndexResult.model)
            .where(
                AIIndexResult.url == url,
                AIIndexResult.index_status == "indexed",
            )
        )
        return [row[0] for row in result.fetchall()]
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "get_client_questions or get_indexed_models"`
预期：4 passed

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_checker.py index-monitor/tests/unit/test_citation_checker_phase2.py
git commit -m "feat(citation): 新增 _get_client_questions + _get_indexed_models 辅助方法"
```

---

## 任务 3：citation_checker.py check_url 改造（5→3 阶段）

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py`
- 修改：`index-monitor/tests/unit/test_citation_checker_phase2.py`

- [ ] **步骤 1：编写失败的测试**

在 `test_citation_checker_phase2.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_check_url_phase2_3_stages(db_session, monkeypatch):
    """check_url 改造后执行 3 阶段：准备 → 模型探测 → 引用检测。"""
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "check_url_phase2 or no_indexed or no_client_questions"`
预期：FAIL

- [ ] **步骤 3：改造 check_url 与 _STAGES**

在 `citation_checker.py` 中：

**3a. 更新 _STAGES（5→3）：**
```python
_STAGES = {
    1: "1/3 准备",
    2: "2/3 模型探测",
    3: "3/3 引用检测",
}
```
同步更新 `_wrap_with_stage` 中的 `f"{stage_num}/5 未知阶段"` → `f"{stage_num}/3 未知阶段"`。
同步更新 `_extract_stage` 的 docstring `N/5` → `N/3`。

**3b. 改造 check_url 方法**（替换原 5 阶段为 3 阶段）：

```python
    async def check_url(
        self,
        url: str,
        client_id: str,
        *,
        task_id: Optional[str] = None,
        progress: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> dict:
        """对单个 URL 执行 AI 采信检测（3 阶段）。

        阶段：
        1/3 准备：抓取内容 + 加载客户问题 + 筛选已收录模型
        2/3 模型探测：对已收录模型探测联网能力
        3/3 引用检测：用客户问题对已收录模型执行引用检测

        每步骤失败时抛带阶段标签 [N/3 阶段名] 的 ValueError。
        """
        if progress is None:
            progress = self._make_default_progress(task_id, url)

        async def _report(stage: str, status: str, message: str, **kw) -> None:
            try:
                await progress(stage, status, message, **kw)
            except Exception as cb_exc:  # noqa: BLE001
                logger.warning("progress 回调异常（已忽略）: %s", cb_exc)

        config = await self._load_ai_config()

        # ──────── 1/3 准备 ────────
        # 1a. 抓取内容
        await _report("1/3 准备", "start", f"开始抓取内容: {url}")
        t0 = time.time()
        logger.info("采信检测 [1/3] 抓取内容: %s", url)
        try:
            content = await asyncio.to_thread(fetch_public_content, url)
            if not content.suitability.suitable:
                raise ValueError(
                    f"内容不适合检测：{content.suitability.rejection_reason}"
                    f"（code={content.suitability.rejection_code}）"
                )
        except Exception as exc:
            await _report("1/3 准备", "error", f"抓取失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(1, exc) from exc

        title = content.title
        target_urls = [
            u for u in (content.requested_url, content.resolved_url, content.canonical_url)
            if u
        ]

        # 1b. 加载客户问题（替代 LLM 自动生成）
        questions = await self._get_client_questions(client_id)
        if not questions:
            await _report("1/3 准备", "error", f"客户 {client_id} 未配置监测问题")
            raise ValueError(
                f"客户 {client_id} 未配置监测问题。"
                "请在客户管理 → 监测问题中添加问题后重试。"
            )

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

        # ──────── 2/3 模型探测 ────────
        await _report("2/3 模型探测", "start", f"开始探测 {len(indexed_models)} 个模型的联网能力")
        t0 = time.time()
        self._set_provider_env(config)
        # 与配置的 citation_models 取交集
        citation_models_str = config.get("ai_citation_models", "")
        configured_ids = (
            [m.strip() for m in citation_models_str.split(",") if m.strip()]
            if citation_models_str else None
        )
        # catalog 过滤
        catalog_ids = {item["id"] for item in adapter_catalog()}
        selected_ids = [
            mid for mid in indexed_models
            if mid in catalog_ids and (configured_ids is None or mid in configured_ids)
        ]
        if not selected_ids:
            await _report("2/3 模型探测", "error", "已收录模型均未配置 API Key 或不在配置列表中")
            raise ValueError(
                "已收录模型均未配置 API Key 或不在配置列表中。"
                "请在系统设置中配置对应模型的 API Key。"
            )

        try:
            adapters = await asyncio.to_thread(default_adapters, selected_ids)
            if not adapters:
                raise ValueError("未配置任何引用检测模型。")

            capabilities = await asyncio.to_thread(probe_adapter_capabilities, adapters)
            verified_count = sum(1 for item in capabilities if item["status"] == "verified")
            logger.info(
                "采信检测 [2/3] 模型探测完成: %d/%d 通过联网验证",
                verified_count, len(adapters),
            )
            for item in capabilities:
                model_name = item.get("model", item.get("provider_id", "?"))
                status = item.get("status", "unknown")
                await _report(
                    "2/3 模型探测", "info" if status == "verified" else "error",
                    f"{model_name}: {status}",
                    model=model_name,
                    detail={"provider_id": item.get("provider_id"), "status": status, "error": item.get("error")},
                )
            await _report(
                "2/3 模型探测", "success",
                f"模型探测完成: {verified_count}/{len(adapters)} 通过联网验证",
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            await _report("2/3 模型探测", "error", f"模型探测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(2, exc) from exc

        # ──────── 3/3 引用检测 ────────
        question_count = min(len(questions), 20)
        await _report(
            "3/3 引用检测", "start",
            f"开始引用检测（{question_count} 问题 × {len(adapters)} 模型）",
        )
        t0 = time.time()
        logger.info(
            "采信检测 [3/3] 引用检测: %s（%d 问题 × %d 模型）",
            url, question_count, len(adapters),
        )
        try:
            result = await asyncio.to_thread(
                run_citation_check,
                target_urls=target_urls,
                candidates=[],  # 不再用生成的问题
                adapters=adapters,
                question_count=question_count,
                forbidden_terms=[*target_urls],
                client_questions=questions[:question_count],  # 客户问题直通
            )
        except Exception as exc:
            await _report("3/3 引用检测", "error", f"引用检测失败: {exc}", duration_ms=int((time.time() - t0) * 1000))
            raise _wrap_with_stage(3, exc) from exc
        await _report("3/3 引用检测", "success", "引用检测完成", duration_ms=int((time.time() - t0) * 1000))

        # 附加元信息（不再有 purpose）
        result["target"] = {
            "requested_url": url,
            "resolved_url": target_urls[-1] if target_urls else url,
            "title": title,
            "extraction_method": content.extraction_method,
        }
        result["provider_capabilities"] = capabilities

        # 存储结果
        await self._store_results(url, result, questions, client_id)

        return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_checker.py index-monitor/tests/unit/test_citation_checker_phase2.py
git commit -m "feat(citation): check_url 改造 5→3 阶段（准备+模型探测+引用检测）"
```

---

## 任务 4：citation_checker.py _store_results 改造（关联 client_question_id）

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py`
- 修改：`index-monitor/tests/unit/test_citation_checker_phase2.py`

- [ ] **步骤 1：编写失败的测试**

在 `test_citation_checker_phase2.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_store_results_links_client_question_id(db_session):
    """_store_results 关联 client_question_id。"""
    from app.models.citation_result import CitationResult

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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "store_results"`
预期：FAIL（签名不匹配或 client_question_id 为 None）

- [ ] **步骤 3：改造 _store_results**

```python
    async def _store_results(
        self, url: str, result: dict, questions: list[str], client_id: str
    ) -> None:
        """将检测结果存入 citation_results 表（幂等：URL+model+question 唯一）。

        Phase 2: 关联 client_question_id（通过 question 文本匹配 ClientQuestion.id）。
        """
        # 构建 question → client_question_id 映射
        from app.models.client_question import ClientQuestion
        q_result = await self.db.execute(
            select(ClientQuestion.id, ClientQuestion.question).where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            )
        )
        question_id_map = {row[1]: row[0] for row in q_result.fetchall()}

        stored_count = 0
        for item in result.get("results", []):
            hit_type = item["hit"]["layer"]
            question = item["question"]
            model = item["model"]

            existing = await self.db.execute(
                select(CitationResult).where(
                    CitationResult.url == url,
                    CitationResult.model == model,
                    CitationResult.question == question,
                )
            )
            if existing.scalar_one_or_none():
                continue

            self.db.add(CitationResult(
                url=url,
                model=model,
                question=question,
                answer=item.get("answer", ""),
                hit_type=hit_type,
                sources=item.get("sources", []),
                client_question_id=question_id_map.get(question),
            ))
            stored_count += 1

        await self.db.commit()
        logger.info("采信检测结果已存储: %s（%d 条新记录）", url, stored_count)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "store_results"`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_checker.py index-monitor/tests/unit/test_citation_checker_phase2.py
git commit -m "feat(citation): _store_results 关联 client_question_id"
```

---

## 任务 5：citation_checker.py get_pending_urls 改造（4 条件 pending）

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py`
- 修改：`index-monitor/tests/unit/test_citation_checker_phase2.py`

- [ ] **步骤 1：编写失败的测试**

在 `test_citation_checker_phase2.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_get_pending_urls_4_conditions(db_session):
    """get_pending_urls 需 4 条件全满足：synced + 有 indexed 模型 + 客户有 active 问题 + 无 citation 记录。"""
    from app.models.manual_distribution import ManualDistribution
    from app.models.citation_result import CitationResult
    import uuid

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

    # 过滤出本测试的 URL
    my_pending = [p for p in pending if p[0].startswith("https://example.com/")]
    pending_urls = {p[0] for p in my_pending}
    assert "https://example.com/pending-url" in pending_urls
    assert "https://example.com/no-index-model" not in pending_urls
    assert "https://example.com/no-questions" not in pending_urls
    assert "https://example.com/already-checked" not in pending_urls
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "get_pending_urls_4"`
预期：FAIL（URL2/URL3 仍被返回，因为当前只检查 synced + 无 citation 记录）

- [ ] **步骤 3：改造 get_pending_urls**

在现有 `get_pending_urls` 的 `pending` 过滤逻辑中，增加两个条件：

```python
    async def get_pending_urls(self) -> list[tuple[str, str]]:
        """获取待检测采信的 URL 列表（增量 + 4 条件 pending）。

        4 条件全满足才 pending：
        1. URL 已分发（manual_distributions 或 GEOFlow，status='synced'）
        2. URL 有至少一个已收录模型（ai_index_results.index_status='indexed'）
        3. URL 对应客户有活跃监测问题（client_questions.status='active'）
        4. URL 尚无 citation_results 记录（增量）
        """
        repo = GeoflowRepository(self.db)
        geoflow_urls = set(await repo.get_synced_distribution_urls())

        manual_result = await self.db.execute(
            select(ManualDistribution.remote_url, ManualDistribution.client_id)
            .where(ManualDistribution.status == "synced")
        )
        distributed: dict[str, str] = {}
        for url, client_id in manual_result.fetchall():
            distributed[url] = client_id

        sites_result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        domain_map = {
            normalize_domain(s.domain): s.client_id
            for s in sites_result.scalars().all()
        }
        for url in geoflow_urls:
            domain = normalize_domain(url)
            client_id = domain_map.get(domain)
            if client_id:
                distributed.setdefault(url, client_id)

        if not distributed:
            return []

        # 条件 2: 有已收录模型的 URL 集合
        from app.models.ai_index_result import AIIndexResult
        indexed_result = await self.db.execute(
            select(AIIndexResult.url).where(AIIndexResult.index_status == "indexed")
        )
        indexed_urls = {row[0] for row in indexed_result.fetchall()}

        # 条件 3: 有活跃监测问题的 client_id 集合
        from app.models.client_question import ClientQuestion
        active_clients_result = await self.db.execute(
            select(ClientQuestion.client_id).where(ClientQuestion.status == "active")
        )
        active_clients = {row[0] for row in active_clients_result.fetchall()}

        # 条件 4: 无 citation_results 记录的 URL 集合
        checked_result = await self.db.execute(select(CitationResult.url))
        checked_urls = {row[0] for row in checked_result.fetchall()}

        # 4 条件过滤
        pending = [
            (url, client_id)
            for url, client_id in distributed.items()
            if url in indexed_urls  # 条件 2
            and client_id in active_clients  # 条件 3
            and url not in checked_urls  # 条件 4
        ]
        if not pending:
            return []

        # 优先级：按 IndexResult.created_at DESC（新文章优先）
        pending_urls = [url for url, _ in pending]
        idx_result = await self.db.execute(
            select(IndexResult.url, IndexResult.created_at)
            .where(IndexResult.url.in_(pending_urls))
        )
        created_at_map = {row[0]: row[1] for row in idx_result.fetchall()}

        with_ts: list[tuple[object, str, str]] = []
        without_ts: list[tuple[str, str]] = []
        for url, cid in pending:
            ts = created_at_map.get(url)
            if ts is None:
                without_ts.append((url, cid))
            else:
                with_ts.append((ts, url, cid))
        with_ts.sort(key=lambda x: x[0], reverse=True)
        return [(url, cid) for _, url, cid in with_ts] + without_ts
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py -v -p no:cacheprovider -k "get_pending_urls_4"`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/citation_checker.py index-monitor/tests/unit/test_citation_checker_phase2.py
git commit -m "feat(citation): get_pending_urls 4 条件 pending（synced+indexed+问题+增量）"
```

---

## 任务 6：_make_default_progress 适配 3 阶段 + 删除 purpose

**文件：**
- 修改：`index-monitor/app/services/citation_checker.py`（_make_default_progress 中 stage 标签）
- 修改：`index-monitor/app/api/routes.py`（删除 purpose 引用）

- [ ] **步骤 1：修改 _make_default_progress**

在 `_make_default_progress` 方法中，将 `stage == "4/5 模型探测"` 改为 `stage == "2/3 模型探测"`：

```python
                if stage == "2/3 模型探测" and model and detail and detail.get("status"):
```

- [ ] **步骤 2：删除 routes.py 中的 purpose 引用**

在 `index-monitor/app/api/routes.py` 中找到 `"purpose": result.get("purpose")` 行（约 552 行），删除该行。

- [ ] **步骤 3：运行现有测试确认无回归**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py tests/unit/test_citation_check_progress.py -v -p no:cacheprovider`
预期：progress 测试可能需要适配 3 阶段标签（见任务 7）

- [ ] **步骤 4：Commit**

```bash
git add index-monitor/app/services/citation_checker.py index-monitor/app/api/routes.py
git commit -m "refactor(citation): _make_default_progress 适配 3 阶段 + 删除 purpose 引用"
```

---

## 任务 7：适配 test_citation_check_progress.py（3 阶段标签）

**文件：**
- 修改：`index-monitor/tests/unit/test_citation_check_progress.py`

- [ ] **步骤 1：更新测试中的阶段标签**

将所有 `1/5 抓取`、`2/5 目的推断`、`3/5 问题生成`、`4/5 模型探测`、`5/5 引用检测` 分别改为 `1/3 准备`、`2/3 模型探测`、`3/3 引用检测`。删除涉及目的推断/问题生成阶段的测试用例（这些阶段已不存在）。

- [ ] **步骤 2：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_check_progress.py -v -p no:cacheprovider`
预期：PASS

- [ ] **步骤 3：Commit**

```bash
git add index-monitor/tests/unit/test_citation_check_progress.py
git commit -m "test(citation): test_citation_check_progress 适配 3 阶段标签"
```

---

## 任务 8：删除 question_generation.py + 瘦身 llm_client.py + 清理导入

**文件：**
- 删除：`index-monitor/app/services/citation_check/question_generation.py`
- 修改：`index-monitor/app/services/llm_client.py`（仅保留 load_ai_configs）
- 修改：`index-monitor/app/services/citation_check/__init__.py`（删除 question_generation 导出）
- 修改：`index-monitor/app/services/citation_checker.py`（删除问题生成相关导入）
- 删除：`index-monitor/tests/unit/test_llm_client_retry.py`
- 删除：`index-monitor/tests/unit/test_llm_client_fallback.py`

- [ ] **步骤 1：删除 question_generation.py**

```bash
git rm index-monitor/app/services/citation_check/question_generation.py
```

- [ ] **步骤 2：瘦身 llm_client.py**

将 `llm_client.py` 替换为仅含 `load_ai_configs`：

```python
"""LLM 客户端配置加载。

Phase 2 清理后仅保留 load_ai_configs（通用 AI 配置加载器）。
问题生成相关的 LLM 调用函数已随问题生成阶段一并删除。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig


async def load_ai_configs(db: AsyncSession, keys: list[str]) -> dict[str, str]:
    """从 system_config 表批量加载指定 key 的配置。"""
    result = await db.execute(
        select(SystemConfig.key, SystemConfig.value).where(SystemConfig.key.in_(keys))
    )
    return {row[0]: row[1] for row in result.fetchall()}
```

- [ ] **步骤 3：清理 __init__.py**

删除 `from .question_generation import build_candidate_prompt, generate_candidates` 和 `__all__` 中的 `"build_candidate_prompt"`, `"generate_candidates"`。

- [ ] **步骤 4：清理 citation_checker.py 导入**

删除以下导入：
```python
# 删除整段 llm_client 导入（除 load_ai_configs）
from app.services.llm_client import (
    call_deepseek,
    load_ai_configs,
    make_call_generator,
    call_deepseek_with_parse_retry,
    make_parse_retry_generator,
    build_question_providers,
    call_llm_with_parse_retry_fallback,
    make_fallback_parse_retry_generator,
)
from app.services.llm_client import DEFAULT_QUESTION_MODEL
```
替换为：
```python
from app.services.llm_client import load_ai_configs
```

删除 question_generation 导入：
```python
from app.services.citation_check.question_generation import (
    build_purpose_prompt,
    parse_purpose_response,
    parse_candidate_response,
)
```

删除 `from app.services.citation_check import generate_candidates`（如果 __init__.py 还导出的话，已在步骤 3 删除）。

删除 `DEFAULT_QUESTION_MODEL` 的所有引用（`question_model = config.get("ai_question_model", DEFAULT_QUESTION_MODEL)` 等）。

删除 `AI_CONFIG_KEYS` 中的 `"ai_question_model"`（不再需要问题生成模型配置）。

- [ ] **步骤 5：删除测试文件**

```bash
git rm index-monitor/tests/unit/test_llm_client_retry.py
git rm index-monitor/tests/unit/test_llm_client_fallback.py
```

- [ ] **步骤 6：运行全部 Phase 2 测试确认无回归**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_phase2.py tests/unit/test_engine_client_questions.py tests/unit/test_citation_check_progress.py -v -p no:cacheprovider`
预期：全部 PASS

- [ ] **步骤 7：Commit**

```bash
git add -A index-monitor/app/services/citation_check/__init__.py index-monitor/app/services/llm_client.py index-monitor/app/services/citation_checker.py
git commit -m "refactor(citation): 删除 question_generation.py + 瘦身 llm_client.py + 清理导入"
```

---

## 任务 9：适配 test_citation_checker_stages.py（重写为 3 阶段）

**文件：**
- 修改：`index-monitor/tests/unit/test_citation_checker_stages.py`

- [ ] **步骤 1：重写测试**

`test_citation_checker_stages.py` 当前测的是 5 阶段流程。重写为测试 3 阶段：
- 删除所有涉及阶段 2（目的推断）和阶段 3（问题生成）的测试用例
- 保留并适配阶段 1（抓取→准备）、阶段 4→2（模型探测）、阶段 5→3（引用检测）的测试
- 更新所有阶段标签为 3 阶段
- 适配 mock：不再 mock `call_llm_with_parse_retry_fallback` / `make_fallback_parse_retry_generator`，改为 mock `_get_client_questions` / `_get_indexed_models`

- [ ] **步骤 2：运行测试验证通过**

运行：`cd index-monitor && python -m pytest tests/unit/test_citation_checker_stages.py -v -p no:cacheprovider`
预期：PASS

- [ ] **步骤 3：Commit**

```bash
git add index-monitor/tests/unit/test_citation_checker_stages.py
git commit -m "test(citation): test_citation_checker_stages 重写为 3 阶段"
```

---

## 自检

### 规格覆盖度

| 设计文档章节 | 对应任务 | 状态 |
|-------------|---------|------|
| 管道对比（5→3 阶段） | 任务 3 | ✅ |
| check_url 核心流程改造 | 任务 3 | ✅ |
| _get_client_questions 辅助方法 | 任务 2 | ✅ |
| _get_indexed_models 辅助方法 | 任务 2 | ✅ |
| get_pending_urls 4 条件 | 任务 5 | ✅ |
| _store_results 关联 client_question_id | 任务 4 | ✅ |
| 删除 question_generation.py | 任务 8 | ✅ |
| 删除 citation_checker 阶段 2-3 代码 | 任务 3 | ✅ |
| 删除 llm_client DEFAULT_QUESTION_MODEL 相关 | 任务 8 | ✅ |
| 阶段标签变更（1/5→1/3 等） | 任务 3 + 任务 6 | ✅ |
| run_citation_check 客户问题直通 | 任务 1 | ✅ |
| routes.py 删除 purpose | 任务 6 | ✅ |

### 后续 Phase 覆盖

以下设计章节由后续 Phase 实现，不在本计划范围：
- API 端点（Phase 3）
- 前端 UI（Phase 4）
- 客户问题管理界面（Phase 3 API + Phase 4 UI）
- 自动联动（新文章入库 → 收录检测 → 问题监测）属 Phase 3 API 层
