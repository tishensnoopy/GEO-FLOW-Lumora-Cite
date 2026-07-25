# Plan 2：监测系统能力增强 实现计划（主索引）

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 Plan 1 已统一数据库 + SSO 基础设施之上，实现客户全生命周期管理、跨 schema 分发查询、批量检测、PDF/Excel 导出、Dashboard 改造、官网入口与端到端验证。

**架构：** 监测系统（FastAPI）跨 schema 读 GEOFlow 的 `public.*`（只读）+ 读写 `monitor.*`；admin 通过 SSO 登录，client 独立登录；导出走 Playwright（PDF）+ openpyxl（Excel）；前端 Vue 3 风格 A 数据中台。

**技术栈：** FastAPI + SQLAlchemy 2.0 async + PyJWT + Playwright + openpyxl + APScheduler + Vue 3 + Element Plus + ECharts

**实现分支：** `feat/unified-db-and-monitoring`（基于 `feat/rebrand-dual-domain`）

**设计文档：** [2026-07-25-geoflow-monitor-db-sync-design.md](../specs/2026-07-25-geoflow-monitor-db-sync-design.md)

---

## 里程碑分解

| 里程碑 | 范围 | 任务数 | 详细计划文档 |
|--------|------|--------|-------------|
| **M1** | 数据模型 + 鉴权地基 | 7 | [2026-07-25-plan2-m1-data-models-auth.md](./2026-07-25-plan2-m1-data-models-auth.md) |
| **M2** | 核心查询 + 检测改造 + admin 端点 | 13 | [2026-07-25-plan2-m2-query-services-admin.md](./2026-07-25-plan2-m2-query-services-admin.md) |
| **M3** | 监测结果导出（PDF + Excel）| 4 | [2026-07-25-plan2-m3-export-features.md](./2026-07-25-plan2-m3-export-features.md) |
| **M4** | Dashboard 前端 + 官网入口 + E2E | 11 | [2026-07-25-plan2-m4-frontend-website-e2e.md](./2026-07-25-plan2-m4-frontend-website-e2e.md) |

**执行顺序**：M1 → M2 → M3 → M4（严格顺序，每个里程碑完成后做两阶段审查再进入下一个）

---

## 文件结构总览

### 后端新建文件

```
index-monitor/
├── alembic/versions/
│   ├── 003_create_manual_distributions.py          # M1-任务1
│   ├── 004_create_admin_audit_logs.py              # M1-任务2
│   ├── 005_create_export_tasks.py                  # M1-任务3
│   ├── 006_create_archived_distributions.py        # M1-任务4
│   └── 007_extend_clients_and_client_sites.py      # M1-任务5+6
├── app/
│   ├── models/
│   │   ├── manual_distribution.py                  # M1-任务1
│   │   ├── admin_audit_log.py                      # M1-任务2
│   │   ├── export_task.py                          # M1-任务3
│   │   └── archived_distribution.py                # M1-任务4
│   ├── api/
│   │   ├── admin_routes.py                         # M2-任务6+7+8
│   │   ├── client_auth_routes.py                   # M2-任务9（客户改密码/资料）
│   │   └── export_routes.py                        # M3-任务3
│   ├── services/
│   │   ├── distribution_query.py                   # M2-任务1-5
│   │   ├── audit_log.py                            # M2-任务8
│   │   ├── pdf_export_service.py                   # M3-任务1
│   │   ├── excel_export_service.py                 # M3-任务2
│   │   ├── export_service.py                       # M3-任务4
│   │   ├── archive_service.py                      # M4-任务8
│   │   └── scan_rate_limiter.py                    # M2-任务10
│   ├── utils/
│   │   └── validators.py                           # M1-任务7 + M2-任务4
│   └── templates/
│       └── report.html                             # M3-任务1（PDF 模板）
├── templates/
│   └── report.html                                 # M3 PDF 报告模板
└── tests/
    ├── unit/
    │   ├── test_manual_distribution.py             # M1-任务1
    │   ├── test_admin_audit_log.py                 # M1-任务2
    │   ├── test_export_task.py                     # M1-任务3
    │   ├── test_archived_distribution.py           # M1-任务4
    │   ├── test_client_lifecycle_fields.py         # M1-任务5
    │   ├── test_client_site_domain_unique.py       # M1-任务6
    │   ├── test_auth_deps.py                       # M1-任务7
    │   ├── test_validators.py                      # M1-任务7
    │   ├── test_distribution_query_service.py      # M2-任务1-5
    │   ├── test_domain_normalizer.py               # M2-任务4
    │   ├── test_audit_log_service.py               # M2-任务8
    │   ├── test_batch_scan.py                      # M2-任务11
    │   ├── test_client_lifecycle.py                # M2-任务6
    │   ├── test_change_password.py                 # M2-任务9
    │   ├── test_scan_rate_limiter.py               # M2-任务10
    │   ├── test_pdf_export.py                      # M3-任务1
    │   ├── test_excel_export.py                    # M3-任务2
    │   └── test_export_service.py                  # M3-任务4
    ├── integration/
    │   ├── test_admin_endpoints.py                 # M2-任务7
    │   ├── test_manual_distribution_endpoint.py    # M2-任务8
    │   ├── test_export_endpoints.py                # M3-任务3
    │   └── test_cross_schema_query.py              # M2-任务2
    └── e2e/
        └── test_unified_db_flow.py                 # M4-任务10
```

### 后端修改文件

```
index-monitor/
├── app/
│   ├── models/
│   │   ├── client.py                               # M1-任务5+6（扩展字段）
│   │   └── __init__.py                             # M1（注册新模型）
│   ├── api/
│   │   ├── deps.py                                 # M1-任务7（补 super_admin + unified user）
│   │   └── routes.py                               # M2-任务12（注册 admin router）
│   ├── core/
│   │   └── config.py                               # M2-任务10（SCAN_* 配置）
│   ├── services/
│   │   ├── index_checker.py                        # M2-任务13（改 get_pending_urls）
│   │   ├── citation_checker.py                     # M2-任务13（改 get_pending_urls）
│   │   └── scheduler.py                            # M4-任务8（加归档任务）
│   └── main.py                                     # M2-任务12（注册新 router）
├── deploy/scripts/
│   ├── init-db.sh                                  # M1（同步新表/字段）
│   └── test-unified-db-e2e.sh                      # M4-任务10（新建）
└── requirements.txt                                # M3（确认依赖）
```

### 前端新建/修改文件

```
dashboard/
├── src/
│   ├── views/
│   │   ├── Login.vue                               # M4-任务1（改造）
│   │   ├── Dashboard.vue                           # M4-任务2（改造）
│   │   ├── Distributions.vue                       # M4-任务3（新建）
│   │   ├── Exports.vue                             # M4-任务4（新建）
│   │   └── AuditLogs.vue                           # M4-任务6（新建）
│   ├── components/
│   │   ├── StatCard.vue                            # M4-任务2（新建）
│   │   ├── SiteFilter.vue                          # M4-任务5（新建）
│   │   └── ExportDialog.vue                        # M4-任务4（新建）
│   ├── router/index.js                             # M4（注册新路由）
│   ├── store/index.js                              # M4（admin/client 状态）
│   └── api/index.js                                # M4（admin/client API 封装）
```

### GEOFlow 侧修改文件

```
GEOFlow-main/
├── resources/views/
│   ├── layouts/admin.blade.php                     # M4-任务9（加监测系统菜单）
│   └── homepage.blade.php（或对应首页模板）          # M4-任务7（加监测平台入口）
```

---

## 依赖关系图

```
M1（数据模型 + 鉴权）
  │
  ├─► M2（查询服务 + admin 端点）
  │     │
  │     ├─► M3（导出功能）—— 依赖 M2 的 DistributionQueryService
  │     │     │
  │     │     └─► M4（前端 + E2E）—— 依赖 M2 端点 + M3 导出 API
  │     │
  │     └─► M4（前端调用 admin 端点）
  │
  └─► M4（前端登录用 M1 的鉴权依赖）
```

**关键依赖**：
- M2 的 `DistributionQueryService` 依赖 M1 的 `ManualDistribution` 模型
- M2 的 admin 端点依赖 M1 的 `get_current_admin` / `get_current_super_admin`
- M3 的导出端点依赖 M2 的 `DistributionQueryService`（查数据）
- M4 的前端依赖 M2+M3 的所有 API 端点
- M4 的 E2E 测试依赖 M1-M3 全部完成

---

## 测试策略

### TDD 红绿循环（每个任务遵循）

1. **RED**：写失败测试（测试函数 + 断言）
2. **验证 RED**：运行测试确认失败（报错原因符合预期）
3. **GREEN**：写最少实现代码让测试通过
4. **验证 GREEN**：运行测试确认通过
5. **COMMIT**：`git add` + `git commit`（遵循 conventional commits）

### 测试分层

| 层级 | 目录 | 覆盖内容 |
|------|------|---------|
| 单元测试 | `tests/unit/` | 模型字段、服务逻辑、工具函数、鉴权 |
| 集成测试 | `tests/integration/` | API 端点、跨 schema 查询、数据库交互 |
| E2E 测试 | `tests/e2e/` + `deploy/scripts/` | 全链路：GEOFlow 分发 → 监测系统可见 → 检测 → 导出 |

### 运行测试

```bash
# 单个测试文件
cd index-monitor && pytest tests/unit/test_manual_distribution.py -v

# 整个 unit 目录
cd index-monitor && pytest tests/unit/ -v

# 全量测试（含集成）
cd index-monitor && pytest tests/ -v --tb=short

# E2E 脚本
bash deploy/scripts/test-unified-db-e2e.sh
```

---

## 执行前准备

### 1. 创建实现分支

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git checkout feat/rebrand-dual-domain
git pull origin feat/rebrand-dual-domain
git checkout -b feat/unified-db-and-monitoring
git push -u origin feat/unified-db-and-monitoring
```

### 2. 确认本地环境

```bash
# 确认本地 PG 容器运行
docker ps | grep geo-postgres-local

# 确认 alembic 当前版本
cd index-monitor && alembic current
# 期望：002 (move monitor tables from public to monitor schema)

# 确认测试基线全绿
cd index-monitor && pytest tests/ -v --tb=short
```

### 3. 依赖项确认

`requirements.txt` 应已包含（Plan 1 已加）：
- `playwright>=1.40.0`
- `openpyxl>=3.1.0`
- `apscheduler>=3.10.0`
- `bcrypt>=4.0.0`（passlib 已用）
- `httpx>=0.25.0`

**M3 额外步骤**（Playwright 浏览器安装，在 Dockerfile 或本地）：
```bash
playwright install chromium
# 中文字体（PDF 渲染必需）
sudo apt-get install -y fonts-noto-cjk fonts-noto-cjk-extra
```

---

## 验收标准映射

设计文档第 19 节的 50 条验收标准分布到里程碑：

| 里程碑 | 验收标准编号 | 数量 |
|--------|-------------|------|
| M1 | 1, 4, 5, 14, 15, 42 | 6 |
| M2 | 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 30, 43 | 15 |
| M3 | 19, 20, 21, 22, 36 | 5 |
| M4 | 23, 24, 25, 26, 27, 28, 29, 31, 32, 33, 34, 35, 38, 39, 40, 41 | 16 |
| 全系统 | 44, 45, 46, 47, 48, 49, 50 | 7（部署后冒烟）|

---

## 下一步

1. 打开 [M1 详细计划](./2026-07-25-plan2-m1-data-models-auth.md) 开始执行
2. M1 完成后做两阶段审查（自检 + 代码审查），再进入 M2
3. 依次推进 M2 → M3 → M4
4. M4 完成后执行全系统冒烟测试 + 生产部署
