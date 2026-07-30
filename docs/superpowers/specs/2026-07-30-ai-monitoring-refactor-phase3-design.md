# AI 监测逻辑重构 Phase 3：API 层设计

> **重构范围**：AI 监测重构的 API 端点层——客户问题管理 CRUD、AI 收录检测/问题监测触发端点、新文章入库自动联动、客户端只读 API、统一扫描触发入口。
> **前置依赖**：Phase 1（数据模型 + AI 收录检测服务）、Phase 2（问题监测服务 3 阶段改造）已完成并推送。
> **影响层**：API 路由、服务编排、调度器。前端 UI 属 Phase 4，不在本规格范围。

## 背景

Phase 1 和 Phase 2 完成了数据模型（`client_questions`、`ai_index_results`、`citation_results.client_question_id`）和服务层（`AIIndexChecker`、`CitationChecker` 3 阶段改造）。但服务层尚无 API 端点暴露：

- 客户问题无法通过 API 管理（当前无 CRUD 端点）
- AI 收录检测无法通过 API 触发（`AIIndexChecker` 无路由）
- 新文章入库后不会自动触发 AI 收录检测（`create_manual_distribution` 仅触发搜索引擎收录检测）
- 客户端无法查看自己的收录概览和引用证据（无客户端只读 API）
- 现有扫描端点不支持 `ai_index` 类型

Phase 3 补齐 API 层，使 Phase 1/2 的服务能力可通过 HTTP 端点访问，并实现设计文档要求的自动联动链路。

## 目标

1. 暴露客户问题管理 CRUD 端点（运营端可编辑，客户端只读）
2. 暴露 AI 收录检测触发 + 结果查询端点
3. 暴露问题监测触发 + 结果查询端点
4. 实现新文章入库 → AI 收录检测 → 问题监测的自动联动
5. 提供客户端只读 API（概览、证据、问题、统计、导出）
6. 新建统一扫描触发入口，支持 index/ai_index/citation/all 四种类型
7. 实现管理员与客户端的完整数据隔离

## 依赖（Phase 1/2 产出）

| 产出 | 文件 | Phase 3 用途 |
|------|------|-------------|
| `ClientQuestion` 模型 | `app/models/client_question.py` | 问题管理 CRUD 读写 |
| `AIIndexResult` 模型 | `app/models/ai_index_result.py` | 收录结果查询 |
| `CitationResult.client_question_id` 列 | `app/models/citation_result.py` | 监测结果关联问题 |
| `AIIndexChecker` 服务 | `app/services/ai_index_checker.py` | 收录检测触发 |
| `CitationChecker` 服务（3 阶段） | `app/services/citation_checker.py` | 问题监测触发 |
| `scan_task_manager` | `app/services/scan_task_manager.py` | 扫描任务进度管理 |
| `scan_lock` | `app/services/scan_lock.py` | 扫描并发锁 |

## 决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 自动联动实现方式 | 链式异步回调 | 手动添加文章后异步触发 AI 收录检测，检测完成后自动触发问题监测。实现设计文档"新文章入库后自动触发"的成功标准 |
| 自动联动代码组织 | 新建 `auto_pipeline.py` 服务 | 链路逻辑集中、可独立测试、可复用。符合隔离和清晰的设计原则 |
| 扫描入口整合 | 新建统一入口 + 保留旧端点 | 新建 `POST /admin/scan/trigger` 支持 4 种类型；旧端点标记 deprecated 内部转发，向后兼容 |
| 客户端路由组织 | 新建 `client_routes.py` | 客户端只读端点集中管理，与运营端物理隔离。client_id 强制从 JWT 取 |
| 收录检测后衔接 | 自动触发问题监测 | 收录检测完成后自动对 indexed 模型触发问题监测，实现设计文档完整链路 |
| 旧端点处理 | deprecated 但不删除 | 避免破坏性变更，前端 Phase 4 再迁移调用方 |

## 架构概览

### 新增文件

| 文件 | 职责 |
|------|------|
| `app/api/client_question_routes.py` | 客户问题管理 CRUD（运营端）+ 问题只读（客户端） |
| `app/api/ai_index_routes.py` | AI 收录检测触发 + 结果查询 + 统计（运营端） |
| `app/api/client_routes.py` | 客户端只读 API（概览/证据/统计/导出） |
| `app/services/auto_pipeline.py` | 自动联动管道（收录检测 → 问题监测） |
| `app/services/client_question_service.py` | 客户问题业务逻辑（CRUD + 排序 + 校验） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `app/api/admin_routes.py` | 新增统一扫描触发端点；`create_manual_distribution` 添加 auto_pipeline 触发 |
| `app/api/routes.py` | 旧 `scan/trigger/{type}` 标记 deprecated，内部转发到新统一入口 |
| `app/services/scheduler.py` | 新增 02:30 AI 收录检测定时任务（兜底 pending） |
| `app/main.py` | 注册 3 个新路由模块 |

## API 端点详细设计

### 1. 客户问题管理（运营端 CRUD）

认证：`Depends(get_current_admin)`

```
GET    /api/v1/admin/clients/{client_id}/questions
       → 列出指定客户的所有问题（按 sort_order 排序）
       → 返回：[{id, question, sort_order, status, created_at, updated_at}]

POST   /api/v1/admin/clients/{client_id}/questions
       → 添加问题
       → 请求体：{question: str, sort_order?: int}
       → sort_order 省略时追加到末尾（当前最大值 + 1）
       → 校验：question 非空且 ≤ 500 字；client_id 存在
       → 返回：201 + {id, question, sort_order, status}

PUT    /api/v1/admin/clients/{client_id}/questions/{qid}
       → 编辑问题内容或状态
       → 请求体：{question?: str, status?: "active"|"inactive"}
       → 校验：qid 属于该 client_id
       → 返回：{id, question, sort_order, status}

DELETE /api/v1/admin/clients/{client_id}/questions/{qid}
       → 删除问题（硬删除，已有 citation_results 的 client_question_id 置 NULL）
       → 返回：204

PUT    /api/v1/admin/clients/{client_id}/questions/reorder
       → 批量排序
       → 请求体：{ordered_ids: [uuid, ...]}
       → 按 ordered_ids 顺序依次写入 sort_order = 1, 2, 3, ...
       → 校验：ordered_ids 中的 id 全部属于该 client_id
       → 返回：{reordered: count}
```

### 2. 监测问题（客户端只读）

认证：`Depends(get_current_client_id)`

```
GET    /api/v1/questions
       → 查看自己的监测问题（client_id 从 JWT 取，不接受传参）
       → 仅返回 status='active' 的问题
       → 返回：[{id, question, sort_order}]
```

### 3. AI 收录检测（运营端）

认证：`Depends(get_current_admin)`

```
POST   /api/v1/admin/ai-index/scan
       → 批量增量检测（仅 pending URL×模型组合）
       → 复用 scan_lock 互斥
       → 创建 scan_task，asyncio.create_task 后台执行
       → 返回：{task_id, queued, message}

POST   /api/v1/admin/ai-index/scan/{url}
       → 单 URL 重新检测（覆盖旧结果）
       → 对该 URL × 所有配置模型执行检测（含已检测的，覆盖旧状态）
       → 不走批量 scan_lock（单 URL 耗时短）
       → 返回：{task_id, models_count, message}

GET    /api/v1/admin/ai-index/results
       → 查询收录结果（全状态，可过滤）
       → 查询参数：url?, model?, index_status?, client_id?, page, page_size
       → 返回：{items: [{id, url, model, index_status, ai_response, checked_at}], total, page}

GET    /api/v1/admin/ai-index/stats
       → 收录统计
       → 查询参数：client_id?
       → 返回：{
             total_combinations,     # URL×模型总组合数
             indexed,                # 已收录数
             not_indexed,            # 未收录数
             pending,                # 待检测数
             index_rate,             # 收录率 = indexed / (indexed + not_indexed)
             by_model: [{model, indexed, not_indexed, pending, rate}],
             by_client: [{client_id, indexed, not_indexed, pending, rate}]
           }
```

### 4. 问题监测（运营端）

认证：`Depends(get_current_admin)`

```
POST   /api/v1/admin/citation/scan
       → 批量增量监测（仅 pending URL，4 条件过滤）
       → 复用 scan_lock 互斥
       → 创建 scan_task，asyncio.create_task 后台执行
       → 返回：{task_id, queued, message}

POST   /api/v1/admin/citation/scan/{url}
       → 单 URL 重新监测
       → 删除该 URL 的旧 citation_results，重新检测
       → 返回：{task_id, message}

GET    /api/v1/admin/citation/results
       → 查询监测结果（全状态）
       → 查询参数：url?, model?, hit_type?, client_id?, page, page_size
       → 返回：{items: [{id, url, model, question, answer, hit_type, sources, client_question_id, checked_at}], total, page}
```

### 5. 统一扫描触发（运营端）

认证：`Depends(get_current_admin)`

```
POST   /api/v1/admin/scan/trigger
       → 请求体：{scan_type: "index"|"ai_index"|"citation"|"all"}
       → scan_type='all' 时按顺序执行：index → ai_index → citation
       → 每个阶段创建独立 scan_task，前端可分别查看进度
       → 复用 scan_lock 互斥（按阶段类型分别加锁）
       → 返回：{task_ids: {index?: str, ai_index?: str, citation?: str}, message}
```

### 6. 客户端只读 API

认证：`Depends(get_current_client_id)`——client_id 强制从 JWT 取

```
GET    /api/v1/ai-index/overview
       → 我的收录概览（仅已收录，简化）
       → 仅返回该客户 URL 的 index_status='indexed' 记录
       → 返回：{
             total_indexed,          # 已收录 URL 数
             total_not_indexed,      # 未收录 URL 数（仅计数，不列详情）
             index_rate,             # 收录率
             articles: [{url, title, model, index_status, checked_at}]
           }

GET    /api/v1/citations/evidence
       → 我的引用证据（仅被引用的 Q&A）
       → 仅返回该客户 URL 的 hit_type != 'none' 的记录
       → 返回：[{id, url, title, model, question, answer, hit_type, sources, checked_at}]

GET    /api/v1/stats
       → 我的统计卡片数据
       → 返回：{
             ai_indexed_count,       # AI 收录数
             ai_cited_count,         # AI 提及数
             ai_mention_rate,        # 提及率 = cited / indexed
             total_articles,         # 文章总数
             index_rate              # 搜索引擎收录率
           }

GET    /api/v1/export/report
       → 导出自己的引用证据 PDF
       → 复用现有 ExportService，限定 client_id
       → 返回：202 + {task_id}（异步生成，前端轮询下载）
```

### 7. 现有端点改造

| 端点 | 改造 |
|------|------|
| `POST /api/v1/distributions` | 添加文章成功后，`asyncio.create_task(auto_pipeline.trigger_for_url(url, client_id))` |
| `POST /api/v1/scan/trigger/{type}` | 标记 `@deprecated`，内部转发到 `/admin/scan/trigger`，响应头加 `Deprecation: true`（语义相同：全量 pending 扫描） |
| `POST /api/v1/admin/distributions/batch-scan` | 扩展 `scan_type` 支持 `ai_index`/`all`（语义不同：扫描选定记录，不转发到全量入口） |
| `GET /api/v1/articles`（客户） | 精简返回字段：仅已收录文章 + 是否被引用标记；隐藏 pending/not_indexed |
| `GET /api/v1/citations/detail` | 客户端访问时仅返回自己的 + 仅被引用的 |

## 自动联动机制

### 核心服务：`auto_pipeline.py`

```python
class AutoPipeline:
    """新文章入库自动联动管道：AI 收录检测 → 问题监测。

    链式异步回调，两阶段独立执行，错误隔离。
    """

    async def trigger_for_url(self, url: str, client_id: str) -> None:
        """对新文章触发完整联动链路。

        阶段 1: AI 收录检测（该 URL × 所有配置模型）
        阶段 2: 自动衔接——仅对 indexed 模型触发问题监测
        """
        # 阶段 1: AI 收录检测
        async with async_session() as db:
            checker = AIIndexChecker(db)
            models = checker._get_configured_models()
            for model in models:
                try:
                    await checker.check_url(url, model)
                except Exception as exc:
                    logger.error("自动联动-收录检测失败 %s [%s]: %s", url, model, exc)
                    # 单模型失败不阻塞其他模型

        # 阶段 2: 自动衔接判定
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
                select(ClientQuestion).where(
                    ClientQuestion.client_id == client_id,
                    ClientQuestion.status == "active",
                )
            )
            if not q_result.fetchall():
                logger.warning("自动联动-跳过问题监测 %s：客户 %s 未配置监测问题", url, client_id)
                return

        # 阶段 3: 问题监测
        async with async_session() as db:
            try:
                checker = CitationChecker(db)
                await checker.check_url(url, client_id)
            except Exception as exc:
                logger.error("自动联动-问题监测失败 %s: %s", url, exc)
```

### 触发点

| 触发点 | 机制 | 说明 |
|--------|------|------|
| 手动添加文章 | `POST /distributions` 成功后 `asyncio.create_task` | 不阻塞 HTTP 响应 |
| 定时兜底 | scheduler 02:30 扫 pending AI 收录检测 | 作为 fallback，处理触发失败的 URL |

### 关键设计点

- **幂等**：收录检测用 upsert（UNIQUE(url, model)）；问题监测用 select-then-insert 跳过已存在
- **错误隔离**：单阶段失败不阻塞另一阶段，记日志并保留 pending 状态可重试
- **独立 session**：每个阶段用独立 `async_session`，避免 AsyncSession 并发不安全
- **不阻塞响应**：`asyncio.create_task` 后台执行，HTTP 立即返回

## 客户端隔离设计

### 隔离原则

1. **client_id 强制从 JWT 取**——所有客户端端点用 `Depends(get_current_client_id)`，不接受传参
2. **SQL 强制过滤**——所有查询带 `WHERE client_id = :jwt_client_id`
3. **数据范围限制**：
   - 收录概览：仅返回 `index_status='indexed'` 的记录（隐藏 pending/not_indexed 详情）
   - 引用证据：仅返回 `hit_type != 'none'` 的记录（隐藏未引用）
   - 统计卡片：仅计算自己的数据
4. **无操作权限**：客户端端点全部为 GET，无 POST/PUT/DELETE

### 客户端 URL 归属判定

客户端 API 需判定哪些 URL 属于该客户。判定逻辑：

```python
async def _get_client_urls(db: AsyncSession, client_id: str) -> set[str]:
    """获取属于该客户的所有 URL（手动录入 + GEOFlow 分发匹配 ClientSite）。"""
    # 1. 手动录入
    manual = await db.execute(
        select(ManualDistribution.remote_url).where(
            ManualDistribution.client_id == client_id,
            ManualDistribution.status == "synced",
        )
    )
    urls = {row[0] for row in manual.fetchall()}

    # 2. GEOFlow 分发（按 ClientSite.domain 匹配）
    repo = GeoflowRepository(db)
    geoflow_urls = await repo.get_synced_distribution_urls()
    sites = await db.execute(
        select(ClientSite).where(
            ClientSite.client_id == client_id,
            ClientSite.status == "active",
        )
    )
    domains = {normalize_domain(s.domain) for s in sites.scalars().all()}
    urls.update(u for u in geoflow_urls if normalize_domain(u) in domains)

    return urls
```

### 统计指标计算（客户端）

| 指标 | 计算公式 |
|------|---------|
| AI 收录数 | `count(ai_index_results WHERE url ∈ client_urls AND index_status='indexed')` |
| AI 提及数 | `count(citation_results WHERE url ∈ client_urls AND hit_type != 'none')` |
| AI 提及率 | `AI 提及数 / AI 收录数 × 100%`（收录数为 0 时返回 0） |
| 文章总数 | `count(distinct url WHERE url ∈ client_urls)` |

## 调度器改造

`scheduler.py` 新增 AI 收录检测定时任务：

```python
async def scheduled_ai_index_check():
    """每日 02:30 AI 收录检测（兜底 pending）。

    处理自动联动触发失败的 URL×模型组合。
    在搜索引擎收录检测（02:00）之后、采信检测（03:00）之前执行。
    """
    async with async_session() as db:
        if not await acquire_scan_lock(db, "ai_index"):
            logger.warning("已有 AI 收录扫描在运行，定时任务跳过")
            return
        try:
            checker = AIIndexChecker(db)
            pending = await checker.get_pending_urls()
            if not pending:
                logger.info("AI 收录检测：无待检测组合")
                return
            task_id = create_task("ai_index", len(pending), pending)
            logger.info("AI 收录检测定时任务启动：共 %d 组合（task_id=%s）", len(pending), task_id)
            await checker.check_all_pending(task_id=task_id)
            complete_task(task_id)
        finally:
            await release_scan_lock(db, "ai_index")

# start_scheduler 中注册：
scheduler.add_job(
    scheduled_ai_index_check,
    CronTrigger(hour=2, minute=30),
    id="ai_index_check",
    replace_existing=True,
)
```

## 测试策略

### 单元测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/unit/test_client_question_service.py` | CRUD 逻辑、排序、校验（question 非空/长度/client_id 存在） |
| `tests/unit/test_auto_pipeline.py` | 链式回调、无 indexed 模型时跳过、无客户问题时跳过、错误隔离 |
| `tests/unit/test_client_isolation.py` | client_id 强制 JWT、URL 归属判定、数据范围过滤 |

### 集成测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/integration/test_client_question_api.py` | 问题管理 CRUD 端点全流程 |
| `tests/integration/test_ai_index_api.py` | 收录检测触发 + 结果查询 + 统计 |
| `tests/integration/test_auto_pipeline_e2e.py` | 新文章入库 → 收录检测 → 问题监测 完整链路 |
| `tests/integration/test_client_api_isolation.py` | 客户 A 不能看到客户 B 的数据 |
| `tests/integration/test_unified_scan_trigger.py` | 统一扫描触发 4 种类型 + all 顺序执行 |

### 端到端验证

- 运营端：添加问题 → 添加文章 → 验证自动联动 → 查看收录结果 → 查看监测结果
- 客户端：登录 → 查看概览 → 查看引用证据 → 导出报告
- 隔离验证：客户 A 不能看到客户 B 的数据

## YAGNI 边界（明确不做）

- **不实现前端 UI**：前端属 Phase 4，Phase 3 仅交付 API 端点
- **不做批量问题导入**：问题逐条添加，不提供 CSV/批量导入
- **不做问题模板/推荐**：问题完全由运营手动输入
- **不做 AI 收录状态定期重检**：收录检测是一次性的，仅手动重检或定时兜底 pending
- **不做客户端问题编辑**：客户端只读
- **不删除旧扫描端点**：标记 deprecated，Phase 4 前端迁移后再删除
- **不做实时收录检测**：收录检测是异步的，不阻塞文章添加响应

## 改动文件清单

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/api/client_question_routes.py` | 客户问题管理路由 | 新增 |
| `index-monitor/app/api/ai_index_routes.py` | AI 收录检测路由 | 新增 |
| `index-monitor/app/api/client_routes.py` | 客户端只读路由 | 新增 |
| `index-monitor/app/services/auto_pipeline.py` | 自动联动管道 | 新增 |
| `index-monitor/app/services/client_question_service.py` | 客户问题业务逻辑 | 新增 |
| `index-monitor/app/api/admin_routes.py` | 运营端路由 | 修改：新增统一扫描 + auto_pipeline 触发 |
| `index-monitor/app/api/routes.py` | 通用路由 | 修改：旧端点 deprecated 转发 |
| `index-monitor/app/services/scheduler.py` | 调度器 | 修改：新增 AI 收录检测定时任务 |
| `index-monitor/app/main.py` | 应用入口 | 修改：注册新路由 |
| `index-monitor/tests/unit/test_client_question_service.py` | 问题服务测试 | 新增 |
| `index-monitor/tests/unit/test_auto_pipeline.py` | 自动联动测试 | 新增 |
| `index-monitor/tests/unit/test_client_isolation.py` | 客户端隔离测试 | 新增 |
| `index-monitor/tests/integration/test_client_question_api.py` | 问题 API 集成测试 | 新增 |
| `index-monitor/tests/integration/test_ai_index_api.py` | 收录 API 集成测试 | 新增 |
| `index-monitor/tests/integration/test_auto_pipeline_e2e.py` | 联动 E2E 测试 | 新增 |
| `index-monitor/tests/integration/test_client_api_isolation.py` | 隔离集成测试 | 新增 |
| `index-monitor/tests/integration/test_unified_scan_trigger.py` | 统一扫描测试 | 新增 |
