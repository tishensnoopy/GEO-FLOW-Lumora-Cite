# AI 监测链路重构设计（阶段 4：网页端校准 + 置信度标注）

> **日期**：2026-08-03
> **状态**：已确认（用户授权长程自主开发）
> **前置文档**：2026-08-03-monitoring-pipeline-refactor-design.md（阶段 1）

## 1. 背景与问题

### 1.1 API 模型 ≠ 网页版模型

阶段 1-3 的引用检测通过 API 调用 AI 模型（联网搜索），但存在固有偏差：
- API 调用的是固定版本模型，用户网页版可能是不同版本
- 单模型 ≠ 多产品线（豆包有文字/多模态/快速模式）
- 模型迭代速度快，API 版本滞后于网页版

### 1.2 客户信任问题

客户看到引用检测结果后，自然会问："这个结果可信吗？" 当前系统无法回答这个问题——所有结果都同等展示，没有置信度标注。

### 1.3 阶段 3 已就绪的能力

阶段 3 实现了 Playwright 网页端模拟引擎（元宝等无 API 平台），可以：
- 模拟用户在网页版 AI 平台搜索关键词
- 获取网页版 AI 回答全文 + 引用来源
- 结果更接近用户真实体验

## 2. 目标

1. **采样校准**：定期用网页端模拟对 API 引用检测结果进行采样复核
2. **置信度标注**：基于校准数据计算各平台置信度，标注到检测结果上
3. **客户透明**：在客户前端展示置信度，让客户了解检测结果的可信程度
4. **偏差修正**：用校准数据识别 API 偏差大的平台，提示运营关注

## 3. 能力边界

| 能力 | 阶段 4 状态 | 说明 |
|------|------------|------|
| 网页端校准 | ✅ 可用 | 元宝等有网页端模拟的平台 |
| API 平台校准 | ⚠️ 有限 | 仅元宝等无 API 平台可校准；有 API 的平台（千问/豆包等）网页端模拟需额外开发 |
| 置信度标注 | ✅ 可用 | 基于校准数据 + 命中类型 |
| 全平台校准 | ❌ 后续 | 需为每个有 API 的平台开发对应网页端模拟器 |

## 4. 整体架构

### 4.1 数据流

```
现有引用检测（阶段 1-3）
    ↓ citation_results（API 检测结果）
    
采样校准（阶段 4 新增）
    ↓ 抽取 10% citation_results
    ↓ 用网页端模拟重新检测（WebSimulationManager）
    ↓ 对比 API 结果 vs 网页端结果
    ↓ 存入 citation_calibrations
    
置信度计算
    ↓ 平台置信度 = 校准一致次数 / 总校准次数
    ↓ 单条置信度 = 平台置信度 × 命中类型权重
    
前端展示
    ↓ 回答快照页面：每条结果标注置信度标签
    ↓ AI 可见度页面：平台得分旁标注置信度
```

### 4.2 置信度模型

#### 平台置信度（per-model）

```
平台置信度 = (该平台校准一致次数) / (该平台总校准次数) × 100%

分级：
  ≥ 80% → 高置信度（绿色标签）
  50-79% → 中置信度（黄色标签）
  < 50% → 低置信度（红色标签）
  无校准数据 → 未校准（灰色标签）
```

#### 单条结果置信度

单条 citation_result 的置信度基于其所属平台的置信度 + 命中类型权重：

```
单条置信度 = 平台置信度 × 命中类型权重

命中类型权重：
  exact（精确命中）→ 1.0（完全继承平台置信度）
  domain（域名命中）→ 0.8（略降，因域名匹配不如精确匹配可靠）
  none（未命中）→ N/A（未命中无需置信度，结果本身就是"未被引用"）
```

## 5. 详细设计

### 5.1 数据模型

新增表 `citation_calibrations`（monitor schema）：

```python
class CitationCalibration(Base):
    __tablename__ = "citation_calibrations"
    __table_args__ = monitor_table_args(
        UniqueConstraint("citation_result_id", "platform_id", name="uq_calibration_result_platform"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    citation_result_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # FK → citation_results（逻辑外键，不建物理 FK 跨 schema 约束）

    platform_id = Column(String(64), nullable=False)  # 如 "yuanbao"
    # 网页端模拟结果
    web_answer = Column(Text)
    web_sources = Column(JSONB)
    web_hit_type = Column(String(32))  # exact / domain / none

    # API 检测结果（冗余存储，便于对比查询不回查 citation_results）
    api_hit_type = Column(String(32))

    # 对比结论
    matches = Column(Boolean, nullable=False)  # API 与网页端命中类型是否一致
    note = Column(Text)  # 校准备注（如"网页端超时"等异常说明）

    calibrated_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

Alembic 迁移：`016_add_citation_calibrations.py`

### 5.2 校准服务

新增文件：`app/services/calibration_service.py`

```python
class CalibrationService:
    """引用检测校准服务。

    采样部分 citation_results，用网页端模拟重新检测，
    对比 API 结果与网页端结果，计算平台置信度。
    """

    DEFAULT_SAMPLE_RATE = 0.1  # 默认采样 10%
    MIN_SAMPLE_SIZE = 5  # 最少采样 5 条（不足则全量校准）

    async def run_calibration(
        self, sample_rate: float = DEFAULT_SAMPLE_RATE
    ) -> dict:
        """执行一轮校准。

        1. 查询所有已配置网页端模拟的平台（如 yuanbao）
        2. 对每个平台，从 citation_results 采样（按 sample_rate）
        3. 用该平台网页端模拟重新检测每个采样点
        4. 对比 API hit_type vs 网页端 hit_type
        5. 存入 citation_calibrations
        返回：{platform_id: {sampled, calibrated, matched, match_rate}}
        """

    async def get_platform_confidence(self, model: str) -> dict:
        """获取某平台的置信度。

        返回：{
            "model": "qwen",
            "confidence": 85,  # 百分比
            "level": "high",  # high / medium / low / uncalibrated
            "total_calibrations": 20,
            "matched": 17,
        }
        """

    async def get_all_confidence(self) -> list[dict]:
        """获取所有有校准数据的平台置信度列表。"""

    async def get_result_confidence(self, citation_result_id: UUID) -> dict:
        """获取单条引用检测结果的置信度。

        基于：结果所属平台的置信度 × 命中类型权重。
        """
```

### 5.3 采样策略

```python
async def _sample_citation_results(
    self, platform_id: str, sample_rate: float
) -> list[CitationResult]:
    """采样待校准的 citation_results。

    策略：
    1. 只采样该平台已检测过的 citation_results（有 API 结果）
    2. 排除已校准过的（citation_calibrations 中已有记录的）
    3. 按 sample_rate 随机采样，但不低于 MIN_SAMPLE_SIZE
    4. 如果总数不足 MIN_SAMPLE_SIZE，则全量校准
    """
```

### 5.4 对比逻辑

```python
def _compare_hits(api_hit: str, web_hit: str) -> bool:
    """对比 API 与网页端命中类型是否一致。

    一致定义：
    - 两者都是 cited（exact 或 domain）→ 一致（都判定为被引用）
    - 两者都是 none → 一致（都判定为未被引用）
    - 一个 cited 一个 none → 不一致

    注意：不区分 exact 和 domain（两者都算"被引用"），
    因为 API 和网页端的 URL 格式可能略有差异，精确/域名判定可能不同，
    但"是否被引用"的结论应一致。
    """
    api_cited = api_hit in ("exact", "domain")
    web_cited = web_hit in ("exact", "domain")
    return api_cited == web_cited
```

### 5.5 API 端点

#### 管理端（admin_routes.py）

```python
@router.post("/calibration/trigger")
async def trigger_calibration(
    sample_rate: float = 0.1,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """手动触发校准任务。"""

@router.get("/calibration/results")
async def get_calibration_results(
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """查看校准结果概览（各平台置信度 + 最近校准记录）。"""
```

#### 客户端（client_routes.py）

```python
@router.get("/client/confidence")
async def client_confidence(
    client_id: str = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db),
):
    """客户查看各平台置信度。

    返回：{
        "platforms": [
            {"model": "qwen", "confidence": 85, "level": "high", ...},
            ...
        ],
        "overall_confidence": 78,
    }
    """
```

同时增强现有 `client_rankings` 和 `client_visibility` API：
- `client_rankings`：每条 result 增加 `confidence` 字段
- `client_visibility`：每个 platform_score 增加 `confidence` 字段

### 5.6 前端展示

#### 回答快照页面（ClientRankings.vue）

每条 AI 回答卡片增加置信度标签：
```
[元宝] [exact] [高置信度 85%] [2026-08-03 14:30]
回答内容...
```

#### AI 可见度页面（ClientOverview.vue）

平台得分列表增加置信度列：
```
千问    得分 72  [高置信度]
豆包    得分 65  [中置信度]
元宝    得分 80  [未校准]
```

### 5.7 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 网页端模拟超时 | 记录 note="网页端超时"，matches=False |
| 网页端模拟失败（Playwright 未安装） | 记录 note=错误信息，跳过该校准点 |
| 无可校准数据（citation_results 为空） | 返回空结果，不报错 |
| 采样率为 0 | 返回空结果，不报错 |

## 6. 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app/models/citation_calibration.py` | 新增 | 校准结果模型 |
| `alembic/versions/016_add_citation_calibrations.py` | 新增 | 数据库迁移 |
| `app/services/calibration_service.py` | 新增 | 校准服务 |
| `app/api/admin_routes.py` | 修改 | 新增校准触发/查询端点 |
| `app/api/client_routes.py` | 修改 | 新增客户置信度端点 + 增强 rankings/visibility |
| `dashboard/src/views/client/ClientRankings.vue` | 修改 | 回答快照增加置信度标签 |
| `dashboard/src/views/client/ClientOverview.vue` | 修改 | 可见度增加置信度列 |
| `dashboard/src/api/clientView.js` | 修改 | 新增 confidence API 调用 |
| `tests/unit/test_citation_calibration.py` | 新增 | 模型测试 |
| `tests/unit/test_calibration_service.py` | 新增 | 服务测试 |

## 7. 测试策略

### 7.1 单元测试

1. **CitationCalibration 模型**：字段完整性、schema、唯一约束
2. **CalibrationService**：
   - 采样逻辑（sample_rate、MIN_SAMPLE_SIZE、排除已校准）
   - 对比逻辑（_compare_hits 各种组合）
   - 置信度计算（分级边界）
   - 网页端模拟失败降级
   - 无数据时的空返回
3. **API 端点**：
   - 管理端触发校准（权限+采样率参数）
   - 客户端置信度查询（数据隔离）
   - rankings/visibility 增强（confidence 字段存在）

### 7.2 集成验证

- 端到端：触发校准 → 采样 → 网页端模拟 → 对比 → 存储 → 查询置信度

## 8. 与前序阶段的关系

| 阶段 | 内容 | 阶段 4 依赖 |
|------|------|------------|
| 阶段 1 | 引用检测链路打通 | ✅ citation_results 数据 |
| 阶段 2 | 客户透明度 + 指标翻译 | ✅ client_rankings/visibility API |
| 阶段 3 | 网页端模拟引擎 | ✅ WebSimulationManager |
| 阶段 4 | 网页端校准 + 置信度 | 本阶段 |
