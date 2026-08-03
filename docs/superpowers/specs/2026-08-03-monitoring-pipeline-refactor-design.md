# AI 监测链路重构设计（阶段 1：引用检测链路打通）

> **日期**：2026-08-03
> **状态**：已确认，待编写实现计划
> **前置文档**：2026-07-30-ai-monitoring-refactor-design.md（Phase 1-4 重构）

## 1. 背景与问题

### 1.1 核心悖论

当前监测系统存在根本性逻辑缺陷，导致监测链路跑不通：

**训练数据收录检测 ≠ 用户真实体验**

当前 `ai_index_checker` 禁用联网搜索，测的是"模型训练数据中是否包含这篇文章"。但用户实际使用豆包/千问/文心时，模型用的是**联网搜索**。一篇文章可能不在训练数据里（API 判 not_indexed），但用户搜索时通过联网检索能找到（实际有效）。

### 1.2 三重脱节

| 脱节 | 说明 |
|------|------|
| 训练数据 ≠ 联网搜索 | 系统禁用联网搜索测训练数据，用户实际用联网搜索 |
| API 模型 ≠ 网页版模型 | API 调的是固定版本，用户网页版可能是不同版本 |
| 单模型 ≠ 多产品线 | 豆包有文字/多模态/快速模式，API 只能测一个入口 |

### 1.3 文章与关键词关联缺失

当前系统 `client_questions`（客户问题）和 `manual_distributions`（发稿记录）之间没有直接关联。引用检测时所有文章用所有客户问题检测，导致：
- 组合爆炸：100 篇 × 10 问题 × 6 模型 = 6000 次调用
- 大量无关检测（文章讲"数字化转型"，却用"AI营销工具"的问题检测）
- 检测结果无意义（不相关的关键词当然不会被引用）

## 2. 目标

1. **打通引用检测链路**：取消收录检测前置依赖，引用检测直接执行
2. **建立文章→关键词关联**：AI 自动推断每篇文章最相关的客户问题，定向检测
3. **费用可控**：增量检测 + 关键词关联，将 API 调用量从 6000 次/轮降至 ~1200 次/轮
4. **数据可信**：引用检测基于联网搜索，与用户真实体验一致，客户可自行验证

## 3. 能力边界（诚实声明）

| 能力 | 阶段 1 状态 | 说明 |
|------|------------|------|
| 有 API 平台引用检测 | ✅ 可用 | 豆包/千问/文心/DeepSeek/OpenAI/Gemini/Claude |
| 无 API 平台检测 | ❌ 不支持 | 元宝等需阶段 3 Playwright 网页端模拟 |
| 模型版本精确性 | ⚠️ 有限 | API 模型版本 ≠ 网页版，需阶段 4 校准 |
| 回答快照展示 | ❌ 阶段 2 | 数据已存储，前端展示在阶段 2 |
| AI 可见度得分 | ❌ 阶段 2 | 指标翻译层在阶段 2 |
| 网页端校准 | ❌ 阶段 4 | 置信度标注在阶段 4 |

## 4. 整体架构

### 4.1 数据流

```
文章分发（GEOFlow / 手动录入）
    ↓
AI 自动推断关键词关联（DeepSeek 分析文章内容 → 匹配客户 1-3 个问题）
    ↓
引用检测（对每篇文章 × 关联关键词 × 已配置模型，联网搜索提问）
    ↓
结果存储（citation_results: answer + sources + hit_type + client_question_id）
    ↓
前端展示（阶段 2：回答快照 + AI 可见度得分）
```

### 4.2 与当前架构对比

```
当前架构（不可信 + 阻塞）：
  ai_index_checker（禁用联网，测训练数据）
       ↓ 只筛选 indexed 的模型
  citation_checker（联网搜索，测关键词引用）
  问题：前置依赖导致大量文章无法进入引用检测

新架构（可信 + 畅通）：
  article_question_inferrer（DeepSeek 推断文章→关键词关联）
       ↓
  citation_checker（联网搜索，测关键词引用）
       ↓ 直接对所有发稿 × 关联关键词 × 已配置模型执行
  结果存入 citation_results（已有 client_question_id 关联）
  
  ai_index_checker 保留代码，但：
  - 不再是 citation_checker 的前置条件
  - 不再自动执行（管理员可手动触发，作为可选参考）
```

## 5. 详细设计

### 5.1 文章→关键词关联（AI 自动推断）

#### 5.1.1 数据模型

新增表 `article_question_mappings`（monitor schema）：

```python
class ArticleQuestionMapping(Base):
    __tablename__ = "article_question_mappings"
    __table_args__ = monitor_table_args(
        UniqueConstraint("distribution_id", "client_question_id", name="uq_article_question"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    distribution_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # FK → manual_distributions
    client_question_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # FK → client_questions
    relevance_score = Column(Float, nullable=False, default=0.0)  # AI 推断置信度 0-1
    inferred_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

Alembic 迁移：`012_add_article_question_mappings.py`

#### 5.1.2 推断服务

新增文件：`app/services/article_question_inferrer.py`

```python
class ArticleQuestionInferrer:
    """AI 自动推断文章与客户问题的关联关系。

    文章分发到 monitor.manual_distributions 后自动触发。
    用 DeepSeek 分析文章内容，匹配最相关的 1-3 个客户问题。
    """

    async def infer_for_distribution(self, distribution_id: UUID, client_id: str) -> list[dict]:
        """
        1. 抓取文章内容（标题 + 正文前 500 字）
        2. 获取客户所有 active 问题列表
        3. 调用 DeepSeek 推断最相关的 1-3 个问题
        4. 存入 article_question_mappings
        5. 返回关联结果
        """
```

**推断 prompt**：
```
你是内容分析专家。以下是客户的一篇文章片段，请从客户问题列表中选择最相关的 1-3 个问题，
并给出相关性评分（0.0-1.0）。

文章标题：{title}
文章片段：{content[:500]}

客户问题列表：
{questions}

请返回 JSON 格式：
[
  {"question_id": "...", "score": 0.9},
  {"question_id": "...", "score": 0.7}
]

只返回最相关的 1-3 个问题，评分低于 0.3 的不要返回。
```

**降级逻辑**：
- DeepSeek 调用失败 → 记录日志，该文章暂不检测
- 无匹配问题（所有评分 < 0.3）→ 记录日志，该文章跳过引用检测
- 客户无 active 问题 → 跳过推断

#### 5.1.3 触发时机

| 触发场景 | 方式 |
|---------|------|
| 手动录入发稿 | `manual_distribution` 创建后自动触发推断 |
| GEOFlow 分发同步 | 同步到 monitor schema 后自动触发推断 |
| 批量补推断 | 管理员手动触发，对历史无关联的发稿批量推断 |
| 客户问题变更 | 客户问题新增/修改后，对该客户所有发稿重新推断 |

### 5.2 引用检测链路重构

#### 5.2.1 改动：citation_checker.py

```python
class CitationChecker:
    async def check_url(self, url: str, client_id: str) -> dict:
        """
        新流程（无前置依赖）：
        1. 抓取文章内容
        2. 获取文章关联的关键词（从 article_question_mappings）
           - 若无关联 → 自动触发推断
           - 推断后仍无关联 → 跳过，记录日志
        3. 对每个关联关键词 × 每个已配置模型，执行引用检测
           - 联网搜索提问关键词
           - 获取 AI 回答 + sources
           - classify_citation_hit 判定 hit_type
        4. 存入 citation_results
        """
```

**移除的逻辑**：
- `_filter_indexed_models()`：不再筛选已收录模型，直接用所有已配置模型
- 对 `ai_index_results` 的依赖查询

**新增的逻辑**：
- `_get_related_questions(url, client_id)`：从 article_question_mappings 获取关联关键词
- 若无关联，调用 `ArticleQuestionInferrer` 自动推断

#### 5.2.2 改动：auto_pipeline.py

```python
class AutoPipeline:
    async def trigger_for_url(self, url: str, client_id: str):
        """
        新流程：
        1. AI 收录检测（可选，不阻塞主流程）
        2. 引用检测（直接执行，不再依赖收录检测结果）
        """
        # 收录检测降级为可选（失败不阻塞）
        try:
            await self._run_ai_index_check(url, client_id)
        except Exception as e:
            logger.warning(f"AI收录检测失败（不阻塞）: {e}")

        # 引用检测直接执行
        await self._run_citation_check(url, client_id)
```

#### 5.2.3 改动：admin_routes.py

`/scan/trigger` 的 citation 类型：
- 不再要求 ai_index 先执行
- citation 类型独立触发，直接调用 citation_checker

### 5.3 费用控制

#### 5.3.1 增量检测

```python
async def get_pending_citation_combos(client_id: str) -> list[tuple]:
    """
    待检测组合 = 所有 (article, question, model) 组合
                - citation_results 中已有的 (url, question, model) 组合
    
    SQL:
    SELECT m.distribution_id, m.client_question_id, cfg.model
    FROM article_question_mappings m
    CROSS JOIN (SELECT unnest(string_to_array(config_value, ',')) AS model
                FROM system_config WHERE config_key = 'ai_citation_models') cfg
    LEFT JOIN citation_results cr
      ON cr.url = (SELECT remote_url FROM manual_distributions WHERE id = m.distribution_id)
     AND cr.client_question_id = m.client_question_id
     AND cr.model = cfg.model
    WHERE cr.id IS NULL  -- 只取未检测的
      AND m.relevance_score >= 0.3  -- 只检测相关性达标的
    """
```

#### 5.3.2 费用预估

```
100 篇文章 × 平均 2 个关联问题 × 6 个模型 = 1200 次 API 调用
单次引用检测约 3000 token（input 2000 + output 1000）
1200 × 3000 token = 360 万 token

各模型单轮全量检测预估费用：
  DeepSeek（问题推断）：100 × 500 token = 5 万 token → 约 ¥0.05
  千问/豆包/文心：1200 × 3000 token → 各约 ¥3.6
  Gemini：1200 × 3000 token → 约 ¥22
  OpenAI：1200 × 3000 token → 约 ¥130
  Claude：1200 × 3000 token → 约 ¥220

  全模型全量：约 ¥400/轮
  仅国内模型（千问+豆包+文心）：约 ¥11/轮
```

### 5.4 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| DeepSeek 推断失败 | 记录日志，文章暂不检测，下次扫描重试 |
| 文章内容抓取失败 | 记录日志，用标题做推断降级处理 |
| 引用检测 API 调用失败 | 重试 2 次，仍失败则记录 pending 状态 |
| 客户无 active 问题 | 跳过该客户，记录日志 |
| 关联问题全被删除 | 重新触发推断 |

## 6. 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app/models/article_question_mapping.py` | 新增 | 文章→关键词关联模型 |
| `app/services/article_question_inferrer.py` | 新增 | AI 自动推断服务 |
| `app/services/citation_checker.py` | 修改 | 移除前置依赖，改为从关联表获取关键词 |
| `app/services/auto_pipeline.py` | 修改 | 收录检测降级为可选，引用检测直接执行 |
| `app/api/admin_routes.py` | 修改 | citation 扫描类型独立触发 |
| `app/api/client_routes.py` | 修改 | 新增获取文章关联关键词的 API |
| `alembic/versions/012_add_article_question_mappings.py` | 新增 | 数据库迁移 |
| `tests/unit/test_article_question_inferrer.py` | 新增 | 推断服务单元测试 |
| `tests/unit/test_citation_checker_no_index_dep.py` | 新增 | 引用检测无前置依赖测试 |

## 7. 测试策略

### 7.1 单元测试

1. **ArticleQuestionInferrer**：
   - 正常推断：文章内容匹配到 2 个问题
   - 无匹配：所有评分 < 0.3，返回空列表
   - DeepSeek 调用失败：降级处理，不抛异常
   - 客户无 active 问题：跳过推断

2. **CitationChecker（无前置依赖）**：
   - 有关联关键词：正常执行引用检测
   - 无关联关键词：自动触发推断
   - 推断后仍无关联：跳过，记录日志
   - 多模型并行检测：每个模型独立执行

3. **AutoPipeline**：
   - 收录检测失败不阻塞引用检测
   - 引用检测直接执行

### 7.2 集成测试

1. 端到端：文章分发 → AI 推断 → 引用检测 → 结果存储
2. 增量检测：已检测的组合不重复检测
3. 批量补推断：对历史无关联的发稿批量推断

## 8. 与竞品对比

| 维度 | 竞品 | 我们（阶段 1 后） |
|------|------|-----------------|
| 引用检测链路 | ✅ 畅通 | ✅ 畅通 |
| 文章→关键词关联 | ✅ 有 | ✅ AI 自动推断 |
| 无 API 平台检测 | ✅ 网页端模拟 | ❌ 阶段 3 |
| 回答快照展示 | ✅ 有 | ❌ 阶段 2 |
| AI 可见度得分 | ✅ 有 | ❌ 阶段 2 |
| 网页端校准 | ❌ 未观察到 | ❌ 阶段 4 |
| 数据可验证性 | ✅ 有回答全文 | ✅ 有回答全文 |

## 9. 后续阶段

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 阶段 2 | 客户透明度 + 指标翻译 + 回答快照展示 | 阶段 1 数据 |
| 阶段 3 | Playwright 网页端模拟引擎（元宝等无 API 平台） | 阶段 1 架构 |
| 阶段 4 | 网页端校准 + 置信度标注 | 阶段 3 |
