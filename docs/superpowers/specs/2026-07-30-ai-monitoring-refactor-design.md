# AI 监测逻辑重构设计：收录检测先行 + 用户指定问题

> **重构范围**：AI 采信检测管道重构，新增 AI 收录检测阶段，问题来源由自动生成改为客户指定。
> 影响层：数据模型、后端服务、API 端点、前端 UI（运营端 + 客户端）。

## 背景

当前 AI 采信检测（citation check）采用 5 阶段管道：抓取内容 → LLM 推断发布目的 → **LLM 自动生成问题** → 模型探测 → 引用检测。存在两个核心问题：

1. **自动生成的问题质量不可控**：LLM 基于文章内容生成的问题可能与文章核心信息无关（如反爬页内容被当正文时，生成了关于"var arg1 乱码"的问题），无法反映客户真正关心的监测需求。
2. **缺少 AI 收录前置检测**：在未确认 AI 大模型是否"收录"目标 URL 的情况下直接做引用检测，未收录的 URL 也会被全量检测，浪费算力且提及率分母不清晰。

搜索引擎收录检测的逻辑是：先确认收录，再评估排名/表现。AI 监测应同理——先确认 AI 大模型收录了该 URL，再用指定问题检测引用效果。

## 目标

1. 新增 **AI 收录检测**阶段：直接询问 AI 是否了解目标 URL，按模型分别判定收录状态
2. 问题来源改为 **客户指定**：每个客户维护一组监测问题，不再 LLM 自动生成
3. 收录检测先行：仅对已收录的 URL×模型组合执行问题监测
4. 运营端/客户端 **数据与功能完整隔离**：客户端只看价值证明，运营端看全貌
5. 算力控制：批量扫描只处理增量（pending），不全量重跑

## 成功标准

1. 新文章入库后自动触发 AI 收录检测（单次，该 URL × 所有配置模型）
2. 收录检测完成后自动触发问题监测（仅对已收录模型，使用客户问题集）
3. 未收录的 URL×模型 不执行问题监测，不计入 AI 提及率分母
4. 客户端只能看到自己的已收录文章 + 被引用的 Q&A 证据，看不到 pending/未收录/未引用
5. 运营端可管理客户问题（增删改查排序），可查看全量状态
6. 系统设置页面的批量扫描只处理 pending，不全量重跑
7. Dashboard 正确展示 AI 收录率、AI 提及率、待检测数等指标

## YAGNI 边界（明确不做）

- **不保留自动生成问题作为 fallback**：完全移除 LLM 问题生成逻辑，客户必须配置问题才能监测
- **不做 AI 收录状态定期重检**：收录检测是一次性的，不自动重新检测（用户可手动触发单 URL 重检）
- **不做问题模板/推荐**：客户问题完全由运营手动输入，不提供模板库
- **不做实时收录检测**：收录检测是异步的，不阻塞文章添加响应
- **不做多语言问题支持**：当前只支持中文问题
- **不做客户端问题编辑权限**：客户只能查看问题，不能编辑（防止选择"简单"问题人为提高提及率）

## 决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| AI 收录判定方式 | 直接询问 AI | 用户决策：直接问"你是否了解 [URL]"，简单明确 |
| 问题管理维度 | 按客户区分 | 不同客户行业不同，问题集独立；客户有专属问题 |
| 未收录处理 | 标记 + 不监测 + 不计入提及率 | 用户决策：未收录 URL 不重检、不监测、排除出分母 |
| 多模型收录 | 按模型分别判定 | 不同模型训练数据不同，收录状态独立 |
| 架构方案 | 方案 A：双阶段独立管道 | 收录检测和问题监测生命周期不同，分离后可独立重跑 |
| 问题来源 | 完全移除自动生成 | 用户决策：问题不能自动生成，必须用户指定 |
| 批量扫描范围 | 仅增量（pending） | 算力消耗控制，不全量重跑 |
| 客户端问题编辑 | 只读 | 防止客户选择"简单"问题人为提高提及率 |

## 数据模型

### 新增表 1：`monitor.client_questions`（客户问题集）

```
monitor.client_questions
├─ id              UUID PK
├─ client_id       VARCHAR(64)  NOT NULL  → monitor.clients
├─ question        TEXT         NOT NULL  -- 问题内容
├─ sort_order      INT          DEFAULT 0 -- 排序
├─ status          VARCHAR(32)  DEFAULT 'active'  -- active/inactive
├─ created_at      TIMESTAMPTZ
└─ updated_at      TIMESTAMPTZ
```

每个客户维护一组监测问题。添加文章时自动关联该客户的问题集。启用的问题用于该客户所有文章的 AI 监测。

### 新增表 2：`monitor.ai_index_results`（AI 收录检测结果）

```
monitor.ai_index_results
├─ id              UUID PK
├─ url             VARCHAR(512) NOT NULL
├─ model           VARCHAR(64)  NOT NULL  -- 千问/豆包/ChatGPT 等
├─ index_status    VARCHAR(32)  DEFAULT 'pending'  -- pending/indexed/not_indexed
├─ ai_response     TEXT                   -- AI 原始回答（供查看）
├─ checked_at      TIMESTAMPTZ
├─ created_at      TIMESTAMPTZ
└─ UNIQUE(url, model)                     -- 每个 URL×模型 只有一条记录
```

### 修改现有表：`monitor.citation_results`

```
+ client_question_id  UUID  NULLABLE  → monitor.client_questions
```

新增外键关联到客户问题，记录该结果是用哪条问题检测的。保留 `question` 文本字段做冗余（查询方便）。

### 迁移计划

- Alembic 012：创建 `client_questions` 表
- Alembic 013：创建 `ai_index_results` 表 + 给 `citation_results` 加 `client_question_id` 列
- 清空旧 `citation_results`（都是自动生成的脏数据，与新流程不兼容）

## 状态模型

每个 URL × 模型组合的完整生命周期：

```
                    ┌─── indexed（已收录）──→ 问题监测 → cited（被引用）/ not_cited（未引用）
URL × 模型 → pending ┤
                    └─── not_indexed（未收录）→ [结束，不监测]
```

### 统计指标定义

| 指标 | 计算公式 | 说明 |
|------|---------|------|
| AI 收录率 | `indexed / (indexed + not_indexed) × 100%` | 分母不含 pending |
| AI 提及率 | `cited / indexed × 100%` | 分母 = 已收录的 URL×模型数 |
| 待检测数 | `count(pending)` | 还没做收录检测的 URL×模型数 |
| 未收录数 | `count(not_indexed)` | 已检测但 AI 不认识的 URL×模型数 |

### 计算示例

10 篇文章 × 3 模型 = 30 个组合。收录检测结果：pending=6, indexed=15, not_indexed=9。
问题监测结果（仅对 15 个 indexed）：cited=9, not_cited=6。

```
AI 收录率 = 15 / (15+9) = 62.5%
AI 提及率 = 9 / 15 = 60.0%
待检测 = 6, 未收录 = 9
```

## AI 收录检测服务

### 新服务文件：`app/services/ai_index_checker.py`

### 核心流程

```
待检测 URL×模型组合（ai_index_results 无记录）
    ↓
并发检测（Semaphore 并发=3）
    ↓
┌─────────────────────────────────────────┐
│  单次检测 check_url(url, model)         │
│                                         │
│  1. 构建 prompt：                        │
│     "你是否了解这个网页的内容？           │
│      URL: {url}                         │
│      如果了解，请用100字以内描述主要内容。│
│      如果不了解，请只回答'不了解'。"      │
│                                         │
│  2. 调用 AI 模型（复用现有 adapter）      │
│     → 禁用 web_search，测纯训练数据知识   │
│                                         │
│  3. 解析响应 → indexed / not_indexed     │
│                                         │
│  4. 存入 ai_index_results               │
└─────────────────────────────────────────┘
```

### 响应判定规则

```python
NEGATIVE_PHRASES = [
    "不了解", "不知道", "无法访问", "没有相关信息",
    "未收录", "不清楚", "不熟悉", "无法获取",
    "我没有关于", "我无法确认",
]

def parse_index_response(response: str) -> str:
    text = response.strip()
    if len(text) < 20 and any(p in text for p in NEGATIVE_PHRASES):
        return "not_indexed"
    if text.startswith("不了解"):
        return "not_indexed"
    return "indexed"
```

### 三种触发场景

| 场景 | 触发方式 | 处理范围 | 算力消耗 |
|------|---------|---------|---------|
| 自动单次 | 新文章入库时自动触发 | 仅该 URL × 所有配置模型 | 低 |
| 手动批量增量 | 系统设置页面点"扫描" | 仅 pending URL×模型组合 | 可控 |
| 手动单次重检 | 文章列表点"重新检测" | 仅该 URL × 所有配置模型，覆盖旧结果 | 低 |

**关键原则**：系统设置页面的批量扫描永不全量重跑——只处理 pending（增量）。已检测过的收录状态保持不变，除非用户手动对单个 URL 点"重新检测"。

### 自动联动

```
新文章入库
  ↓ 自动触发
AI 收录检测（单次，该 URL × 所有模型）
  ↓ 收录检测完成后自动触发
问题监测（仅对已收录的模型，使用该客户的问题集）
  ↓
完成，结果入 citation_results
```

### 类结构

```python
class AIIndexChecker:
    def __init__(self, db: AsyncSession): ...

    async def get_pending_urls(self) -> list[tuple[str, str, str]]:
        """返回 [(url, client_id, model), ...]
        筛选：synced 分发 + ai_index_results 无记录"""

    async def check_url(self, url: str, model: str, *,
                        task_id=None, progress=None) -> dict:
        """检测单个 URL 在单个模型上的收录状态"""

    async def check_all_pending(self, *, task_id=None,
                                concurrency=3) -> dict:
        """批量检测，返回 {total, success, failed, failures}"""
```

### 关键设计决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| 复用 adapter | 用现有 `default_adapters` | 统一 API 调用、限流、重试逻辑 |
| 禁用 web_search | 检测时关闭联网搜索 | 测训练数据是否收录，非实时检索能力 |
| 日志表 | 复用 `citation_check_logs`，stage="收录检测" | 避免新增表，ScanPanel 统一展示 |
| 错误处理 | API 失败 → 保持 `pending` 状态 | 与 not_indexed 区分，可重试 |
| 增量检测 | `ai_index_results` 无记录才检测 | 收录状态稳定，不重复检测 |

### 扫描触发集成

```
index     → 搜索引擎收录检测（不变）
ai_index  → AI 收录检测（新）
citation  → 问题监测（改造，仅对 AI 已收录的 URL×模型）
all       → index → ai_index → citation 顺序执行
```

## 问题监测服务改造

### 管道对比

```
【当前 5 阶段】                    【新 3 阶段】
1/5 抓取内容            ──保留──→  1/3 准备（抓取 + 加载客户问题 + 筛选已收录模型）
2/5 目的推断（LLM）     ──删除──→  ×（不再需要）
3/5 问题生成（LLM）     ──删除──→  ×（改为客户问题集）
4/5 模型探测            ──保留──→  2/3 模型探测（仅对已收录模型）
5/5 引用检测            ──保留──→  3/3 引用检测（用客户问题，非生成问题）
```

### 改造后的 `check_url` 核心流程

```python
async def check_url(self, url: str, client_id: str, *,
                    task_id=None, progress=None) -> dict:

    # ──────── 1/3 准备 ────────
    # 1a. 抓取内容（保留：获取标题、目标 URL 列表、适合性检测）
    content = await fetch_public_content(url)
    if not content.suitability.suitable:
        raise ValueError(f"内容不适合检测：{content.suitability.rejection_reason}")
    title = content.title
    target_urls = [content.requested_url, content.resolved_url, content.canonical_url]

    # 1b. 加载客户问题（新：替代自动生成）
    questions = await self._get_client_questions(client_id)
    if not questions:
        raise ValueError(
            f"客户 {client_id} 未配置监测问题。"
            "请在客户管理 → 监测问题中添加问题后重试。"
        )

    # 1c. 筛选已收录模型（新：从 ai_index_results 取 index_status='indexed'）
    indexed_models = await self._get_indexed_models(url)
    if not indexed_models:
        raise ValueError("该 URL 未被任何 AI 模型收录，跳过问题监测")

    # ──────── 2/3 模型探测 ────────
    adapters = await self._build_adapters_for_models(indexed_models, config)
    capabilities = await probe_adapter_capabilities(adapters)

    # ──────── 3/3 引用检测 ────────
    result = await run_citation_check(
        target_urls=target_urls,
        candidates=questions,           # ← 客户问题替代生成问题
        adapters=adapters,
        question_count=len(questions),   # ← 用全部客户问题（上限 20）
        forbidden_terms=[*target_urls],
    )

    await self._store_results(url, result, questions)
    return result
```

### 新增辅助方法

```python
async def _get_client_questions(self, client_id: str) -> list[str]:
    """获取客户的活跃监测问题，按 sort_order 排序。"""
    result = await self.db.execute(
        select(ClientQuestion.question)
        .where(ClientQuestion.client_id == client_id,
               ClientQuestion.status == 'active')
        .order_by(ClientQuestion.sort_order)
    )
    return [row[0] for row in result.fetchall()]

async def _get_indexed_models(self, url: str) -> list[str]:
    """从 ai_index_results 取该 URL 已收录的模型列表。"""
    result = await self.db.execute(
        select(AIIndexResult.model)
        .where(AIIndexResult.url == url,
               AIIndexResult.index_status == 'indexed')
    )
    return [row[0] for row in result.fetchall()]
```

### 改造后的 `get_pending_urls`

四个条件全部满足才 pending：

1. URL 已分发（manual_distributions 或 GEOFlow，status='synced'）
2. URL 有至少一个已收录模型（ai_index_results.index_status='indexed'）
3. URL 对应客户有活跃监测问题（client_questions.status='active'）
4. URL 尚无 citation_results 记录（增量，不全量重跑）

### 改造后的 `_store_results`

```python
async def _store_results(self, url: str, result: dict, questions: list[str]) -> None:
    for item in result.get("results", []):
        question = item["question"]
        model = item["model"]

        # 幂等检查：URL + model + question
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
            hit_type=item["hit"]["layer"],
            sources=item.get("sources", []),
            client_question_id=question_id,  # ← 新：关联客户问题
        ))
    await self.db.commit()
```

### 删除的代码

| 文件 | 删除内容 | 理由 |
|------|---------|------|
| `question_generation.py` | `build_purpose_prompt`, `parse_purpose_response`, `generate_candidates`, `parse_candidate_response` | 不再自动生成问题 |
| `citation_checker.py` | 阶段 2（目的推断）+ 阶段 3（问题生成）相关代码 | 改为客户问题 |
| `citation_checker.py` | `question_providers` / `build_question_providers` / `call_llm_with_parse_retry_fallback` 调用 | 问题生成 LLM 调用不再需要 |
| `llm_client.py` | `DEFAULT_QUESTION_MODEL` 相关（仅问题生成用途） | 不再生成问题 |

### 保留的代码

| 文件 | 保留内容 | 理由 |
|------|---------|------|
| `fetcher.py` | `fetch_public_content` | 阶段 1 仍需抓取内容 |
| `suitability.py` | `evaluate_content_suitability` + 反爬检测 | 内容适合性检查仍需 |
| `engine.py` | `probe_adapter_capabilities` | 阶段 2 模型探测仍需 |
| `matching.py` | 引用匹配逻辑 | 阶段 3 引用检测核心 |
| `providers.py` | `default_adapters`, `adapter_catalog` | AI 模型 adapter 复用 |
| `reporting.py` | 报告生成 | 保留 |

### 阶段标签变更

```
citation_check_logs.stage 字段值：
  旧：1/5 抓取, 2/5 目的推断, 3/5 问题生成, 4/5 模型探测, 5/5 引用检测
  新：1/3 准备, 2/3 模型探测, 3/3 引用检测
```

## 管理员与客户端完整隔离

### 核心原则

**客户端 = 价值证明**（看效果，不看过程）
**运营端 = 运维监控**（看全貌，能排查）

### 功能权限隔离

| 功能 | 运营端 | 客户端 | 说明 |
|------|:---:|:---:|------|
| 客户管理（CRUD） | ✅ | ❌ | 只有 admin 能创建/编辑/删除客户 |
| 监测问题管理 | ✅ 编辑 | 👁️ 只读 | admin 为客户配置问题，客户只能查看 |
| AI 收录检测触发 | ✅ | ❌ | 客户不能触发检测 |
| 问题监测触发 | ✅ | ❌ | 同上 |
| 重新检测 | ✅ | ❌ | 客户不能主动重跑 |
| 系统设置（API Key） | ✅ | ❌ | AI 模型配置、API Key 管理 |
| 审计日志 | ✅ | ❌ | 运营操作记录 |
| 手动添加文章 | ✅ | ❌ | 运营代客户录入 |
| 批量扫描 | ✅ | ❌ | 运营触发批量检测 |
| 查看 AI 引用证据 | ✅ 全部 | ✅ 仅自己的 | 客户只看自己被引用的证据 |
| 导出报告 | ✅ 全量 | ✅ 仅自己 | 客户可导出自己的引用证据报告 |
| 查看收录概览 | ✅ 全部客户 | ✅ 仅自己 | 数据范围不同 |

### 数据范围隔离

- 客户端 API 的 `client_id` 只从 JWT token 取，不接受传参
- 所有客户端查询的 SQL 强制带 `WHERE client_id = :jwt_client_id`
- 防止客户通过修改参数查看其他客户数据

### 监测问题管理隔离

- 运营端：客户管理 → 编辑客户 → 监测问题 Tab，可增删改查排序
- 客户端：我的监测 → 监测问题（只读展示），无操作按钮
- 客户不能编辑问题：防止选择"简单"问题人为提高提及率

### UI 导航隔离

**运营端导航**：数据概览（全局）、文章管理（全状态）、分发记录、客户管理、监测问题管理、系统设置、审计日志、扫描中心

**客户端导航**：我的概览（仅自己）、我的文章（已收录）、AI 引用证据（被引用 Q&A）、监测问题（只读）、趋势分析、导出报告

### 客户端 Dashboard 展示内容

**展示**：
- 统计卡片：AI 收录数、AI 提及数、提及率
- AI 引用证据列表（仅被引用的 Q&A，高亮引用部分）
- AI 收录概览（已收录文章 + 是否被引用标记）
- 趋势图：收录率 & 提及率变化

**不展示**：
- 未收录的 URL 列表（负面信息）
- 未引用的详细列表（只展示被引用的）
- pending 状态（后台处理中）
- 技术错误日志
- 模型探测细节

### 运营端 Dashboard 展示内容

- 统计卡片：待检测、已收录、未收录、被引用、未引用
- AI 收录率、AI 提及率
- 完整文章列表（所有状态可见，含重新检测按钮）
- 按模型维度：收录率/提及率对比
- 按客户维度：各客户收录/提及统计
- 错误日志/失败重试

## API 端点

### 监测问题管理（运营端，CRUD）

```
GET    /api/v1/admin/clients/{client_id}/questions          列出客户问题
POST   /api/v1/admin/clients/{client_id}/questions          添加问题
PUT    /api/v1/admin/clients/{client_id}/questions/{qid}    编辑问题
DELETE /api/v1/admin/clients/{client_id}/questions/{qid}    删除问题
PUT    /api/v1/admin/clients/{client_id}/questions/reorder  批量排序
```

### 监测问题（客户端，只读）

```
GET    /api/v1/questions    查看自己的监测问题（只读，client_id 从 JWT 取）
```

### AI 收录检测（运营端）

```
POST   /api/v1/admin/ai-index/scan          批量增量检测（仅 pending）
POST   /api/v1/admin/ai-index/scan/{url}    单 URL 重新检测（覆盖旧结果）
GET    /api/v1/admin/ai-index/results       查询收录结果（全状态，可过滤）
GET    /api/v1/admin/ai-index/stats         收录统计（按模型/客户维度）
```

### 问题监测（运营端）

```
POST   /api/v1/admin/citation/scan          批量增量监测（仅 pending）
POST   /api/v1/admin/citation/scan/{url}    单 URL 重新监测
GET    /api/v1/admin/citation/results       查询监测结果（全状态）
```

### 客户端数据（只读，仅自己的）

```
GET    /api/v1/ai-index/overview            我的收录概览（仅已收录，简化）
GET    /api/v1/citations/evidence           我的引用证据（仅被引用的 Q&A）
GET    /api/v1/stats                         我的统计卡片数据
GET    /api/v1/export/report                 导出自己的引用证据 PDF
```

### 统一扫描触发（运营端）

```python
class ScanTriggerRequest(BaseModel):
    scan_type: str  # 'index' | 'ai_index' | 'citation' | 'all'

# POST /api/v1/admin/scan/trigger
# scan_type='all' 时按顺序执行：index → ai_index → citation
```

### 现有端点改造

| 端点 | 改造内容 |
|------|---------|
| `GET /api/v1/articles`（客户） | 返回字段精简：仅已收录文章 + 是否被引用标记，隐藏 pending/not_indexed |
| `GET /api/v1/admin/articles` | 新增字段：`ai_index_status`、`citation_status`、`indexed_models` |
| `POST /api/v1/scan/trigger/{type}` | 迁移到 `/admin/scan/trigger`，新增 `ai_index` 和 `all` 类型 |
| `GET /api/v1/citations/detail` | 客户端访问时仅返回自己的 + 仅被引用的 |

## 前端文件结构

```
dashboard/src/
├── layouts/
│   ├── AdminLayout.vue          ← 运营端导航（已有，需更新菜单）
│   └── CustomerLayout.vue       ← 客户端导航（新，精简菜单）
├── router/
│   └── index.js                 ← 路由守卫：admin/customer 分流
├── views/
│   ├── admin/                   ← 运营端页面
│   │   ├── Dashboard.vue        ← 改造：新增卡片+图表
│   │   ├── Articles.vue         ← 改造：全状态+新列+重新检测按钮
│   │   ├── Distributions.vue    ← 不变
│   │   ├── Clients.vue          ← 改造：增加"监测问题"入口
│   │   ├── ClientQuestions.vue  ← 新：问题管理（增删改查排序）
│   │   ├── ScanCenter.vue       ← 新：统一扫描中心
│   │   ├── Settings.vue         ← 改造：扫描类型选项
│   │   └── AuditLogs.vue        ← 不变
│   ├── customer/                ← 客户端页面（新目录）
│   │   ├── MyOverview.vue       ← 新：我的概览（卡片+趋势图）
│   │   ├── MyArticles.vue       ← 新：我的文章（仅已收录，简化）
│   │   ├── CitationEvidence.vue ← 新：AI 引用证据（Q&A 卡片展示）
│   │   ├── MyQuestions.vue      ← 新：监测问题（只读）
│   │   └── ExportReport.vue     ← 新：导出报告
│   └── shared/
│       └── ScanPanel.vue        ← 改造：3 阶段进度（原 5 阶段）
├── components/
│   ├── CitationCard.vue         ← 新：引用证据卡片（高亮引用部分）
│   ├── IndexStatusBadge.vue     ← 新：收录状态标签
│   └── ModelTag.vue             ← 新：AI 模型标签
└── api/
    ├── questions.js             ← 新：问题管理 API
    ├── aiIndex.js               ← 新：AI 收录 API
    └── citation.js              ← 改造：引用证据 API
```

## 路由守卫设计

```javascript
const routes = [
  // 运营端路由
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAdmin: true },
    children: [
      { path: 'dashboard', component: AdminDashboard },
      { path: 'articles', component: AdminArticles },
      { path: 'clients', component: AdminClients },
      { path: 'clients/:id/questions', component: ClientQuestions },
      { path: 'scan-center', component: ScanCenter },
      { path: 'settings', component: Settings },
      { path: 'audit-logs', component: AuditLogs },
    ]
  },
  // 客户端路由
  {
    path: '/customer',
    component: CustomerLayout,
    meta: { requiresCustomer: true },
    children: [
      { path: 'overview', component: MyOverview },
      { path: 'articles', component: MyArticles },
      { path: 'evidence', component: CitationEvidence },
      { path: 'questions', component: MyQuestions },
      { path: 'export', component: ExportReport },
    ]
  },
  // 登录后按角色重定向
  { path: '/', redirect: to => {
    return localStorage.getItem('role') === 'admin' ? '/admin/dashboard' : '/customer/overview'
  }}
]
```

## Dashboard 图表调整

| 现有图表 | 调整 |
|---------|------|
| 统计卡片 | 新增"AI 收录率""AI 提及率""待检测"3 个卡片 |
| AI 采信分布饼图 | 改为 4 态：已收录被引用 / 已收录未引用 / 未收录 / 待检测 |
| 多引擎收录趋势 | 保留不变（搜索引擎收录） |
| 引擎收录对比柱状图 | 保留不变 |
| 来源分布环形图 | 保留不变 |
| 新增：AI 收录趋势 | 按时间展示 AI 收录率变化 |
| 新增：模型维度对比 | 按模型展示收录率和提及率（柱状图） |

## ScanPanel 改造（5 阶段 → 3 阶段）

```
【AI 收录检测进度】
  ✓ 千问 → 已收录 (1.2s)
  ✗ 豆包 → 未收录 (0.8s)
  ✓ ChatGPT → 已收录 (2.1s)

【问题监测进度】
  1/3 准备    ████████ 完成 (0.5s)
  2/3 模型探测 ████████ 完成 (3.2s)  千问✓ 豆包✓
  3/3 引用检测 ██████░░░ 60% (3/5 问题)  ← 实时进度
```

## 改动文件清单

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/models/client_question.py` | 客户问题模型 | 新增 |
| `index-monitor/app/models/ai_index_result.py` | AI 收录结果模型 | 新增 |
| `index-monitor/app/services/ai_index_checker.py` | AI 收录检测服务 | 新增 |
| `index-monitor/app/api/client_question_routes.py` | 问题管理路由（运营端） | 新增 |
| `index-monitor/app/api/ai_index_routes.py` | AI 收录检测路由 | 新增 |
| `index-monitor/alembic/versions/012_create_client_questions.py` | 迁移：客户问题表 | 新增 |
| `index-monitor/alembic/versions/013_create_ai_index_results.py` | 迁移：AI 收录结果表 + citation_results 加列 | 新增 |
| `index-monitor/app/services/citation_checker.py` | 采信检测管道 | 改造：删阶段 2-3，加客户问题+已收录模型筛选 |
| `index-monitor/app/services/citation_check/question_generation.py` | 问题生成 | 删除（或废弃） |
| `index-monitor/app/api/routes.py` | 客户端路由 | 改造：精简返回字段 |
| `index-monitor/app/api/admin_routes.py` | 运营端路由 | 改造：新增端点 |
| `index-monitor/app/services/scan_task_manager.py` | 扫描任务管理 | 改造：阶段标签更新 |
| `dashboard/src/views/admin/ClientQuestions.vue` | 问题管理页 | 新增 |
| `dashboard/src/views/admin/ScanCenter.vue` | 扫描中心 | 新增 |
| `dashboard/src/views/customer/MyOverview.vue` | 客户概览 | 新增 |
| `dashboard/src/views/customer/MyArticles.vue` | 客户文章 | 新增 |
| `dashboard/src/views/customer/CitationEvidence.vue` | 引用证据 | 新增 |
| `dashboard/src/views/customer/MyQuestions.vue` | 客户问题（只读） | 新增 |
| `dashboard/src/layouts/CustomerLayout.vue` | 客户端导航 | 新增 |
| `dashboard/src/router/index.js` | 路由 | 改造：admin/customer 分流 |
| `dashboard/src/views/admin/Dashboard.vue` | 运营仪表盘 | 改造：新卡片+图表 |
| `dashboard/src/views/admin/Articles.vue` | 运营文章列表 | 改造：新列+重新检测 |
| `dashboard/src/components/ScanPanel.vue` | 扫描进度 | 改造：3 阶段显示 |
| `dashboard/src/components/CitationCard.vue` | 引用证据卡片 | 新增 |

## 测试策略

1. **单元测试**：
   - `parse_index_response` 判定逻辑（否定短语、短回复、正常描述）
   - `_get_client_questions` / `_get_indexed_models` 查询逻辑
   - `get_pending_urls` 四条件过滤

2. **集成测试**：
   - 新文章入库 → 自动收录检测 → 自动问题监测 完整链路
   - 未收录 URL 不触发问题监测
   - 客户无问题时跳过监测并提示
   - 客户端 API 强制按 client_id 过滤

3. **端到端测试**：
   - 运营端：添加问题 → 添加文章 → 触发扫描 → 查看结果
   - 客户端：登录 → 查看概览 → 查看引用证据 → 导出报告
   - 隔离验证：客户 A 不能看到客户 B 的数据
