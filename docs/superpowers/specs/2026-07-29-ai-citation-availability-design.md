# LumoraCite 采信检测可用性修复与稳定性增强设计

> **子项目 A**（共 4 个子项目）。本规格只覆盖采信检测"跑通且跑得稳"，不含配置统一（C）、问题生成质量提升（B）、可观测性（D）。

## 背景

LumoraCite 采信检测当前因模型名错误实际跑不通，且存在配额浪费和瞬态失败处理粗糙的问题。本子项目聚焦"可用性修复与稳定性增强"。

## 目标

让采信检测从"模型名错误导致跑不通"变为"跑得通、跑得稳、不浪费配额"。

## 成功标准

1. 单条 URL 检测端到端跑通（真实 DeepSeek Key + 至少 1 个联网模型 Key）
2. 同一批次内对同一模型的探测只发生 1 次（缓存命中）
3. DeepSeek 限流/超时时步骤级重试生效，不直接整条失败
4. `adapter_catalog()` 不再返回 deepseek 项

## YAGNI 边界（明确不做）

- 不统一两套 AI 配置（子项目 C）
- 不重做 prompt（子项目 B）
- 不加配置连通性自测 UI（子项目 C）
- 不引入 Redis 缓存（进程内 TTL 足够）
- 不加 URL 级自动重试（仅人工重试）

## 决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| DeepSeek 角色 | 只做问题生成 | DeepSeek 官方 API 不支持联网搜索，做引用检测模型先天不足 |
| 探测缓存 | 进程内 TTL（1h） | 准静态数据，零依赖，多 worker 重复探测可接受 |
| 重试策略 | 步骤级重试 + 人工重试 | 覆盖瞬态错误，避免 URL 级重试重复消耗配额 |

## 改动文件清单

| 文件 | 职责 | 改动性质 |
|------|------|----------|
| `index-monitor/app/services/llm_client.py` | DeepSeek 问题生成调用 | 修模型名 + 加步骤级重试 + JSON 解析重试 |
| `index-monitor/app/services/citation_check/providers.py` | 引用检测模型适配器目录 | 移除 DeepSeek 适配器 |
| `index-monitor/app/services/citation_check/engine.py` | 探测与检测执行 | 加探测结果 TTL 缓存 |
| `index-monitor/app/services/citation_checker.py` | 端到端流程编排 | catalog 过滤 + 阶段标签 + 用新重试 API |
| `index-monitor/app/services/citation_check/question_generation.py` | 目的推断与问题解析 | 多策略 JSON 清洗 + prompt 微调 |

## 详细设计

### 1. llm_client.py — DeepSeek 问题生成调用

**问题**：`DEFAULT_QUESTION_MODEL = "deepseek-v4-flash"` 模型名不存在（DeepSeek 官方实际支持 `deepseek-chat`/`deepseek-reasoner`）；`call_deepseek_sync` 无重试；`temperature=0.7` 对结构化 JSON 偏高。

**改动**：
1. `DEFAULT_QUESTION_MODEL = "deepseek-chat"`
2. 新增 `_call_with_retry(callable, args, max_retries=2, base_delay=1.0, retry_on=(httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError))`：指数退避（1s/2s/4s）；仅 429 和 5xx 重试，4xx 立即抛出；手写循环，零新依赖
3. `call_deepseek_sync` 包 `_call_with_retry`；`temperature` 改 `0.3`；`max_tokens` 提到 `8192`
4. 新增 `call_deepseek_with_parse_retry(api_key, model, prompt, parser)`：调用成功但 `parser(text)` 抛 `ValueError` 时，在 prompt 末尾追加"请严格只返回 JSON，不要任何解释"重调，最多 2 次
5. 新增 `make_parse_retry_generator(api_key, model, parser)`：包装 `make_call_generator` + 解析重试，供 `citation_checker` 用

**不改**：`get_ai_config` / `load_ai_configs` / `make_call_generator` 签名

### 2. providers.py — 引用检测模型适配器

**问题**：DeepSeek 适配器走 DashScope 端点 + DashScope Key 命名误导；DeepSeek 不支持联网搜索做引用检测先天不足。

**改动**：
1. 从 `default_adapters` 字典删除 `"deepseek"` 整个 `RawHttpAdapter(...)` 条目
2. 从 `adapter_catalog()` 返回列表删除 `{"id": "deepseek", ...}` 条目
3. `_PROVIDER_ENV_MAP` 中 `ai_dashscope_api_key → DASHSCOPE_API_KEY` 保留（千问仍用）

**不改**：其他 6 个适配器；`RawHttpAdapter`/`GeminiAdapter`/`AnthropicAdapter` 类定义

**副作用**：`system_config.ai_citation_models` 若配了 `"deepseek"`，需在 `citation_checker` 中优雅降级（见第 4 节）

### 3. engine.py — 探测与检测执行

**问题**：`probe_adapter_capabilities` 每次 `check_url` 都重新探测所有适配器，N 模型 = N 次联网调用 + N 次配额消耗。探测结果本质准静态。

**改动**：
1. 模块级 `_PROBE_CACHE: dict[str, tuple[float, dict]]`，`_PROBE_CACHE_TTL = 3600`
2. key 格式 `f"{provider_id}:{model_id}"`
3. `_cache_key(adapter)` / `_get_cached(key)` / `_set_cached(key, value)` 辅助
4. `probe_adapter_capability(adapter, *, force_refresh=False)`：先查缓存，未命中调 `_probe_adapter_capability_uncached`（原逻辑）并写缓存
5. `probe_adapter_capabilities` 签名不变，内部逐个走缓存
6. 新增 `invalidate_probe_cache(provider_id=None)`：清全部或指定模型

**不改**：`run_citation_check`；`ask_with_retry`（仍 1 次重试）；常量

**线程安全**：进程内 dict 读写在 CPython 下由 GIL 保护；最坏情况两 worker 同时未命中各探测一次，结果一致无数据竞争。不加锁。

### 4. citation_checker.py — 端到端流程编排

**问题**：`selected_ids` 含已下线 id 时直接报错；单条失败缺阶段标签；步骤 2/3 无解析重试。

**改动**：
1. 步骤 4 加 catalog 过滤：从 `providers.adapter_catalog()` 取合法 id 集合，过滤 `selected_ids`，dropped 项 `logger.warning`
2. 步骤 2（目的推断）改用 `call_deepseek_with_parse_retry(..., parser=parse_purpose_response)`
3. 步骤 3（问题生成）改用 `make_parse_retry_generator(..., parser=parse_candidate_response)`
4. 每步骤包 `try/except`，捕获后 `raise ValueError(f"[阶段N] {original_msg}")` 重抛
5. 阶段标签：`[1/5 抓取]` `[2/5 目的推断]` `[3/5 问题生成]` `[4/5 模型探测]` `[5/5 引用检测]`
6. `check_all_pending` 的 `failures` 项变 `{"url", "stage", "error"}`，新增 `_extract_stage(msg)` 用正则提取 `[... ]` 前缀
7. 新增 `on_config_changed()` 调用 `invalidate_probe_cache()`，供后续 API 路由调用（本子项目只暴露入口）

**不改**：`get_pending_urls`；`_load_ai_config` / `_set_provider_env`；`_store_results`

### 5. question_generation.py — 目的推断与问题解析

**问题**：解析失败直接 `raise ValueError`，瞬态脏数据无重试；解析器不应知道如何调 LLM，只做"更宽容的解析"。

**改动**：
1. 新增 `_candidate_cleanings(raw)`：依次返回 [原样, 去 markdown 围栏, 提取最大 {...}, 去 trailing 逗号] 的清洗结果
2. `parse_purpose_response` 遍历清洗策略，首个成功解析的返回；全部失败 `raise ValueError`
3. `parse_candidate_response` 同样改造，提取 `_candidate_array_cleanings`（提取最大 `[...]`）
4. `build_purpose_prompt` / `build_candidate_prompt` 在"只返回 JSON"后追加"不要使用 ```json 代码块围栏"

**不改**：`ArticlePurpose` dataclass；`generate_candidates` 签名；`CONTENT_TYPES` / `PUBLISHING_PURPOSES`

## 跨文件依赖关系

```
question_generation.py  ← 多策略清洗（无外部新依赖）
        ↑
llm_client.py           ← 新增 call_deepseek_with_parse_retry + make_parse_retry_generator
        ↑                  调用 question_generation 的解析器判断是否可重试
citation_checker.py     ← 用新 API，加 catalog 过滤，加阶段标签
        ↓
engine.py               ← 加探测缓存（独立）
providers.py            ← 删 DeepSeek 适配器（独立）
```

实现顺序：`providers.py` → `engine.py` → `question_generation.py` → `llm_client.py` → `citation_checker.py`（被依赖的先做）

## 测试策略

| 文件 | 测试方式 |
|------|----------|
| llm_client.py | 单元测试：mock httpx，验证 429 重试、4xx 不重试、JSON 解析重试 |
| providers.py | 单元测试：验证 `default_adapters()` 不含 deepseek、`adapter_catalog()` 不含 deepseek |
| engine.py | 单元测试：mock adapter，验证首次探测、缓存命中、`force_refresh`、`invalidate_probe_cache` |
| citation_checker.py | 单元测试：mock 下游，验证 catalog 过滤告警、阶段标签、失败汇总结构 |
| question_generation.py | 单元测试：脏 JSON（带围栏/trailing 逗号/嵌套），验证多策略清洗能解析 |

## 后续子项目（不在本规格范围）

- **B**：AI 问题生成质量提升（重做 prompt、候选评分去重、多模型对比）
- **C**：跨系统 AI 配置统一（LumoraCite 复用 GEOFlow `ai_models` 表）
- **D**：AI 模型可观测性与 A/B 评估
