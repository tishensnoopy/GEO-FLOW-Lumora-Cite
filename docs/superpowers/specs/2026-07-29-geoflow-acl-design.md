# GEOFlow Schema 防腐层与契约测试设计

## 背景与约束

GEOFlow 是独立演进、可升级的上游项目（GitHub 独立仓库）；LumoraCite 维护性较差、改动没底气。当前 LumoraCite 通过 SQLAlchemy 直接映射并查询 GEOFlow 的 `public` schema 表——GEOFlow 升级做一次 migration（改字段名/类型/拆表），LumoraCite 就会运行时崩溃，且编译期发现不了。这违背了"GEOFlow 独立可升级"的前提。

本规格在 LumoraCite 侧引入防腐层（ACL）+ 独立 schema 契约测试，让 GEOFlow 升级对 LumoraCite 的破坏可提前检测。

**决策组合**：防腐层用仓储模式（集中所有 GEOFlow schema 知识到一个文件）+ 独立契约测试套件（升级前手动跑，未来接 CI）。

## 目标

1. LumoraCite 对 GEOFlow schema 的所有直接依赖被隔离在 `app/integration/geoflow/` 一个包内
2. GEOFlow schema 变化时，LumoraCite 只需改防腐层一处，调用方零改动
3. 升级 GEOFlow 前跑契约测试，立即知道会不会破坏 LumoraCite
4. `app/models/geoflow_models.py` 被删除，LumoraCite 不再直接持有 GEOFlow ORM 模型

## 成功标准

- 7 个引用 GEOFlow 模型的文件全部改为通过仓储调用
- `app/models/geoflow_models.py` 删除
- 仓储单元测试覆盖所有 6 个方法
- 契约测试套件可对真实 GEOFlow DB 运行通过
- 现有业务测试全部通过（无回归）

## YAGNI 边界（明确不做）

- 不引入 GEOFlow HTTP API（DB 直读 + 仓储隔离已足够，API 化是后续子项目）
- 不改 `geoflow_models.py` 的表名（GEOFlow 那边不变，只是 LumoraCite 不再直接引用它）
- 不做读写双向同步（LumoraCite 对 GEOFlow 纯只读，无写操作）
- 不改 SSO 集成（SSO 已走 API，与 DB 防腐层无关）
- 不改 LumoraCite 的业务逻辑（只改数据访问方式）
- 不接入 CI（当前没 CI，契约测试手动跑；未来有 CI 直接接入）
- 不测 GEOFlow 的业务逻辑（只测 schema 结构和仓储查询能跑通）

## 依赖面现状（基线）

LumoraCite 对 GEOFlow 的依赖是**纯只读**——无任何 `db.add/insert/update` 写入 GEOFlow 表。

**4 张表**：
| 表名 | ORM 模型 | 引用文件数 |
|------|---------|-----------|
| `article_distributions` | `GeoflowArticleDistribution` | 5（核心） |
| `articles` | `GeoflowArticle` | 3（join 查询） |
| `distribution_channels` | `GeoflowDistributionChannel` | 2（join 查询） |
| `admins` | `GeoflowAdmin` | 1（仅注释，SSO 已走 API） |

**防腐层覆盖范围**：前三张表。`admins` 已走 SSO API 调用，不纳入。

**7 个引用文件**（按迁移顺序）：
1. `app/api/trend_routes.py` — 单表聚合
2. `app/api/admin_routes.py` — 单表点查
3. `app/services/index_checker.py` — 单表过滤
4. `app/services/citation_checker.py` — 单表过滤
5. `app/services/scheduler.py` — 单表过滤 + domain 聚合
6. `app/services/archive_service.py` — 三表 join
7. `app/services/distribution_query.py` — 三表 join + 分页

## 详细设计

### 1. 文件结构

新增 `app/integration/geoflow/` 包，防腐层所有代码集中于此：

```
app/integration/geoflow/
├── __init__.py
├── dto.py              # DistributionDTO / ArticleDTO / DistributionChannelDTO / 复合 DTO
├── repository.py       # GeoflowRepository 仓储类（6 个业务方法）
├── reader.py           # 底层 SQLAlchemy 查询实现（仓储内部用）
└── mappers.py          # raw row → DTO 的映射函数
```

**分层意图**：
- `dto.py`：纯数据契约，无依赖。契约测试和所有调用方都依赖它
- `repository.py`：业务语义方法。调用方只接触这一层
- `reader.py` + `mappers.py`：GEOFlow schema 细节被锁在这里。schema 变化只改这两个文件

### 2. DTO 定义（防腐层的契约边界）

```python
@dataclass(frozen=True)
class DistributionDTO:
    id: int
    article_id: int | None
    remote_url: str
    status: str
    action: str
    distribution_channel_id: int | None
    created_at: datetime

@dataclass(frozen=True)
class ArticleDTO:
    """articles 表中 LumoraCite 实际消费的字段（基于 archive_service / distribution_query 的真实使用）"""
    id: int
    title: str | None
    slug: str | None
    excerpt: str | None
    content: str | None
    keywords: str | None  # TEXT 类型，LumoraCite 侧自行解析 JSON
    meta_description: str | None
    original_keyword: str | None
    published_at: datetime | None

@dataclass(frozen=True)
class DistributionChannelDTO:
    """distribution_channels 表中 LumoraCite 实际消费的字段"""
    id: int
    name: str | None
    domain: str | None

@dataclass(frozen=True)
class DistributionWithArticleDTO:
    """三表 join 查询的复合 DTO（不含 IndexResult——那是 LumoraCite 自己的表）"""
    distribution: DistributionDTO
    article: ArticleDTO | None
    channel: DistributionChannelDTO | None
```

DTO 只暴露 LumoraCite 实际使用的字段——GEOFlow 加新字段不影响，删/改字段才触发契约测试失败。

**边界澄清**：`distribution_query.py` 当前的 join 还拉了 `IndexResult`（monitor schema 的表）。防腐层只负责 GEOFlow 三表，`IndexResult` 的 join 留在调用方——仓储方法返回 `DistributionWithArticleDTO` 后，调用方自行决定如何再 join `IndexResult`。这保持了"GEOFlow schema 知识在防腐层内，LumoraCite 自身 schema 知识在调用方"的边界清晰。

### 3. 仓储接口方法清单

| 仓储方法 | 对应当前代码 | 业务语义 |
|---------|-------------|---------|
| `get_synced_distribution_urls()` | `citation_checker.py:130-134`, `index_checker.py:29-33` | 取所有 `status='synced'` 且 `action!='delete'` 的 `remote_url` |
| `get_distributions_with_article(channel_id?, date_range?, page?)` | `distribution_query.py:85-93` | 三表 join 查询，带过滤和分页 |
| `get_distributions_for_archive()` | `archive_service.py:69-79` | join 查询用于归档对比（检查已删除的 GEOFlow 分发） |
| `get_distribution_by_ids(ids)` | `admin_routes.py:605-607` | 按 id 批量查分发记录 |
| `get_distribution_trend(start_date)` | `trend_routes.py:108-111` | 按天聚合 created_at 统计趋势 |
| `get_deleted_distribution_domains()` | `scheduler.py:134` | 查 `action='delete'` 的 domain |

### 4. 契约测试形态

**两层测试**：

1. **结构契约**（schema structure）：
   - 三张表存在
   - LumoraCite 用到的字段存在（只查 DTO 里暴露的字段，非全部字段）
   - 字段类型兼容（如 `id` 是整数、`remote_url` 是字符串、`created_at` 是时间戳）
   - 关键索引存在（`status`、`remote_url` 等 LumoraCite 查询过滤用的索引）

2. **查询契约**（query behavior）：
   - 仓储的每个方法能正常执行（返回 DTO，不抛异常）
   - 对固定测试数据，返回结果符合预期
   - 用 seed 脚本插入少量已知记录，测完自动清理

**文件结构**：

```
tests/contract/geoflow_schema/
├── conftest.py              # 连接真实 GEOFlow DB（从 .env 读连接串）
├── test_table_structure.py  # 结构契约：表/字段/类型/索引
├── test_repository_queries.py  # 查询契约：每个仓储方法
└── seed_contract_data.py    # 插入测试数据（带清理）
```

**关键设计**：
- `conftest.py` 读 `DATABASE_URL` 或 `GEOFLOW_DATABASE_URL` 环境变量，连真实 GEOFlow DB
- 结构契约测试只读 `information_schema`，不依赖业务数据，可对空库跑
- 查询契约测试用 `seed_contract_data.py` 插入固定数据（1 篇文章 + 2 条分发 + 1 个渠道），测完自动清理
- 测试文件头部标注："升级 GEOFlow 前执行 `pytest tests/contract/ -v`"
- 失败时打印"哪个字段缺失/类型不匹配/哪个索引消失"，直接指向问题

### 5. 迁移策略

渐进迁移，每步独立可 commit、可回滚：

| 步骤 | 改动 | 验证 |
|------|------|------|
| 1 | 新建 `app/integration/geoflow/` 四个文件 + DTO + 仓储骨架 | 仓储单元测试（mock reader） |
| 2 | 迁移 `trend_routes.py`（单表聚合，最简单） | 趋势 API 返回不变 |
| 3 | 迁移 `admin_routes.py`（单表点查） | 管理 API 返回不变 |
| 4 | 迁移 `index_checker.py`（单表过滤） | 收录检测跑通 |
| 5 | 迁移 `citation_checker.py`（单表过滤） | 采信检测跑通 |
| 6 | 迁移 `scheduler.py`（单表过滤 + domain 聚合） | 定时任务跑通 |
| 7 | 迁移 `archive_service.py`（三表 join） | 归档功能跑通 |
| 8 | 迁移 `distribution_query.py`（三表 join + 分页） | 分发查询跑通 |
| 9 | 删除 `app/models/geoflow_models.py` | 全量测试通过 |
| 10 | 新增 `tests/contract/geoflow_schema/` 契约测试 | 对真实 DB 跑通过 |

**每步的迁移模式**（统一操作）：
1. 调用方把 `select(GeoflowArticleDistribution)...` 换成 `repo.get_xxx(...)`
2. 调用方操作 DTO 而非 ORM 对象（DTO 是 dataclass，`.remote_url` 等属性访问方式不变）
3. 跑该调用方的测试确认行为不变
4. commit

join 查询（步骤 7、8）最复杂，放最后——此时仓储已稳定，join 逻辑搬进 reader 时有前面的简单查询做参照。

## 跨文件依赖关系

```
调用方（7 个文件）
    ↓ 只依赖
repository.py（业务方法）
    ↓ 调用
reader.py（SQLAlchemy 查询）→ mappers.py（row → DTO）→ dto.py
                                                        ↑
                                            契约测试也依赖 dto.py
```

GEOFlow schema 变化时的影响范围：只波及 `reader.py` + `mappers.py`，调用方和 `repository.py` 零改动（除非业务方法签名要调整）。

## 测试策略

| 层次 | 测试 | 目的 |
|------|------|------|
| 仓储单元测试 | `tests/unit/test_geoflow_repository.py`，mock reader | 验证仓储方法逻辑、DTO 映射 |
| 契约测试 | `tests/contract/geoflow_schema/`，连真实 DB | 验证 GEOFlow schema 与 DTO 定义一致 |
| 回归测试 | 现有业务测试（tests/unit/、tests/integration/） | 验证迁移无行为变化 |

## 后续（不在本规格范围）

- **GEOFlow HTTP API 化**：把 DB 直读改为 API 调用，彻底解耦（后续子项目）
- **登录体验优化**：当前 SSO 链路有 4 处割裂感，单独立项设计
- **CI/CD 接入**：契约测试套件未来直接接入 CI 作为升级门禁
