# GEO FLOW + Lumora Cite

> GEO 内容分发 + 收录 AI 监测系统 —— 面向生成式引擎优化（GEO）的全链路内容分发与收录/采信监测平台

## 项目简介

本系统为 **GEO（Generative Engine Optimization，生成式引擎优化）** 场景下的内容分发与监测平台，整合三大子系统：

| 子系统 | 角色 | 技术栈 |
|--------|------|--------|
| **GEOFlow** | 内容管理 + 分发引擎（IdP） | Laravel + PostgreSQL |
| **Lumora Cite** | AI 采信检测服务 | Python |
| **index-monitor** | 收录/采信监测平台（本仓库核心） | FastAPI + Vue 3 |

**核心能力：**
- 📤 **内容分发**：GEOFlow 将文章分发到多渠道（官网、自媒体、第三方平台）
- 🔍 **收录检测**：定期扫描搜索引擎收录状态（百度/Google/Bing/360/搜狗）
- 🤖 **AI 采信检测**：检测内容是否被 AI 模型（DeepSeek/通义千问等）引用
- 📊 **数据看板**：多维度统计可视化（收录趋势/采信分布/引擎对比/来源分布）
- 📄 **报告导出**：PDF（Playwright 渲染）+ Excel（openpyxl 4 工作表）
- 🔐 **SSO 单点登录**：GEOFlow 作为 IdP，监测系统作为 SP
- 🗄️ **统一数据库**：PostgreSQL schema 隔离（public=GEOFlow，monitor=监测系统）

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     用户浏览器                                │
│                   monitor.zkeeeai.com                        │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
        ┌──────▼──────┐              ┌────────▼────────┐
        │   Nginx     │              │   GEOFlow 官网   │
        │  (443 SSL)  │              │  zkeeeai.com     │
        └──────┬──────┘              └────────┬────────┘
               │                              │
    ┌──────────┼──────────┐                   │ SSO
    │          │          │                   │
┌───▼───┐ ┌───▼───┐ ┌────▼────┐     ┌────────▼────────┐
│ Vue 3 │ │FastAPI│ │ FastAPI │     │    GEOFlow      │
│Dashbd │ │Monitor│ │  SSO    │◄───►│   (Laravel)     │
│ :80   │ │ :8090 │ │ /sso/*  │     │    IdP :8000    │
└───────┘ └───┬───┘ └─────────┘     └────────┬────────┘
              │                              │
              │ asyncpg                      │ Eloquent
              │                              │
        ┌─────▼──────────────────────────────▼─────┐
        │         PostgreSQL (pgvector/pg16)        │
        │  ┌──────────┐  ┌───────────────────────┐  │
        │  │ public   │  │ monitor               │  │
        │  │ (GEOFlow)│  │ (index-monitor)       │  │
        │  │ articles │  │ clients / client_sites│  │
        │  │ distrib  │  │ index_results         │  │
        │  │ channels │  │ citation_results      │  │
        │  └──────────┘  │ export_tasks          │  │
        │                │ audit_logs / archived │  │
        │                └───────────────────────┘  │
        └──────────────────┬───────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Redis     │
                    │ (限流/缓存) │
                    └─────────────┘
```

## 技术栈

### 后端（index-monitor）
- **FastAPI** 0.109 — 异步 Web 框架
- **SQLAlchemy** 2.0 + asyncpg — 异步 ORM
- **Alembic** — 数据库迁移（9 个版本）
- **APScheduler** — 定时任务（收录检测/导出处理/归档扫描）
- **PyJWT** + passlib[bcrypt] — JWT 认证 + 密码哈希
- **Playwright** — PDF 导出（Chromium 渲染）
- **openpyxl** — Excel 导出
- **Redis** — 扫描限流 + 缓存

### 前端（dashboard）
- **Vue 3** + Composition API
- **Vite** 5 — 构建工具
- **Element Plus** — UI 组件库
- **ECharts** + vue-echarts — 数据可视化
- **Axios** — HTTP 客户端
- **Pinia**（Vuex）— 状态管理

### 基础设施
- **PostgreSQL** 16 (pgvector) — 统一数据库，schema 隔离
- **Redis** 7 — 限流 + 缓存
- **Nginx** — 反向代理 + SSL 终结
- **Docker Compose** — 容器编排（本地 + 生产）
- **Let's Encrypt** — SSL 证书

## 项目结构

```
.
├── index-monitor/              # 监测系统后端（FastAPI）
│   ├── app/
│   │   ├── api/                # 路由层
│   │   │   ├── admin_routes.py     # admin 端点（客户管理/审计/统计/导出）
│   │   │   ├── client_auth_routes.py # client 认证（登录/改密/profile）
│   │   │   ├── export_routes.py    # 导出端点（PDF/Excel 创建+下载）
│   │   │   ├── routes.py           # 通用端点（健康/配置/分发/批量检测）
│   │   │   ├── sso_routes.py       # SSO 端点（authorize/callback/userinfo）
│   │   │   └── deps.py             # 依赖注入（认证/DB/权限）
│   │   ├── core/               # 核心组件
│   │   │   ├── config.py           # 配置（pydantic-settings）
│   │   │   ├── database.py         # 异步引擎
│   │   │   ├── auth.py             # JWT + 权限校验
│   │   │   └── redis.py            # Redis 连接
│   │   ├── models/             # SQLAlchemy 模型（10 张表）
│   │   ├── services/           # 业务服务
│   │   │   ├── index_checker.py    # 收录检测
│   │   │   ├── citation_checker.py # AI 采信检测
│   │   │   ├── export_service.py   # 导出编排
│   │   │   ├── pdf_export_service.py  # PDF 生成
│   │   │   ├── excel_export_service.py # Excel 生成
│   │   │   ├── archive_service.py  # 归档服务
│   │   │   ├── audit_log.py        # 审计日志
│   │   │   ├── scan_rate_limiter.py # 扫描限流
│   │   │   ├── scheduler.py        # 定时任务调度
│   │   │   ├── distribution_query.py # 分发查询
│   │   │   ├── sso_service.py      # SSO 服务
│   │   │   └── citation_check/     # AI 采信检测子模块
│   │   ├── templates/report.html  # PDF 报告模板
│   │   └── utils/              # 工具函数
│   ├── alembic/                # 数据库迁移（001-009）
│   ├── tests/                  # 测试套件（250 passed）
│   ├── Dockerfile.local        # 本地开发镜像
│   └── requirements.txt
│
├── dashboard/                  # 监测系统前端（Vue 3）
│   ├── src/
│   │   ├── views/              # 页面（Dashboard/Login/Articles/Exports...）
│   │   ├── components/         # 组件（StatCard/Charts/ExportDialog...）
│   │   ├── router/             # 路由
│   │   ├── store/              # Pinia 状态管理
│   │   ├── api/                # API 封装
│   │   └── main.js             # 入口（全局注册 Element Plus 图标）
│   ├── Dockerfile
│   └── package.json
│
├── deploy/                     # 部署配置
│   ├── nginx/                  # Nginx 配置
│   └── scripts/                # 部署脚本
│       ├── setup-db-roles.sh      # 创建 monitor_user + 权限隔离
│       ├── init-db.sh             # 初始化 monitor schema + 7 张表
│       ├── migrate-monitor-data.sh # 数据迁移
│       ├── deploy-lumora-cite.sh  # Lumora Cite 部署
│       ├── test-sso-e2e.sh        # SSO 端到端测试
│       ├── test-unified-db-e2e.sh # 统一 DB E2E 测试
│       └── backup.sh              # 数据库备份
│
├── docs/                       # 文档
│   ├── 2026-07-25-ops-manual.md      # 运维手册
│   ├── 2026-07-25-improvements-deployment.md # 改进部署
│   └── superpowers/
│       ├── plans/              # 实现计划（Plan 1/2 M1-M4）
│       └── specs/              # 设计文档
│
├── docker-compose.local.yml    # 本地开发编排
├── docker-compose.prod.yml     # 生产部署编排
├── docker-compose.yml          # 基础编排
├── .env.example                # 环境变量模板
└── .gitignore
```

## 快速开始

### 前置条件

- Docker + Docker Compose
- Node.js 18+（前端本地开发）
- Python 3.11+（后端本地开发，或直接用 Docker）
- PostgreSQL 16（或使用 Docker 容器）

### 1. 克隆仓库

```bash
git clone git@github.com:tishensnoopy/GEO-FLOW-Lumora-Cite.git
cd GEO-FLOW-Lumora-Cite
```

### 2. 配置环境变量

```bash
cp .env.example .env.local
# 编辑 .env.local，填入实际的数据库密码、API Key 等
```

### 3. 启动本地开发环境

```bash
# 前置：GEOFlow 本地栈已启动（提供 geoflow-postgres 容器）
cd GEOFlow-main && docker compose up -d && cd ..

# 启动监测系统（Redis + index-monitor）
docker compose -f docker-compose.local.yml up -d

# 初始化 monitor schema + 表结构
docker exec geo-index-monitor-local alembic upgrade head

# 创建 DB 权限隔离（可选但推荐）
MONITOR_DB_PASSWORD=<your_password> \
  PGPASSWORD=<geo_user_password> \
  bash deploy/scripts/setup-db-roles.sh

# 启动前端开发服务器
cd dashboard && npm install && npm run dev
```

### 4. 访问服务

| 服务 | 地址 |
|------|------|
| 监测系统 API | http://localhost:8090 |
| 前端 Dashboard | http://localhost:5173（dev）或 http://localhost:80（Docker） |
| API 文档（Swagger） | http://localhost:8090/docs |
| 健康检查 | http://localhost:8090/api/v1/health |

## 测试

### 后端测试

```bash
# 在 Docker 容器内运行（推荐）
docker exec geo-index-monitor-local python -m pytest

# 预期结果：250 passed, 1 skipped
```

### 前端构建

```bash
cd dashboard && npm run build
```

### E2E 测试

```bash
# 统一 DB 端到端测试（15 步核心链路）
ADMIN_TOKEN=<your_jwt> bash index-monitor/deploy/scripts/test-unified-db-e2e.sh

# SSO 端到端测试
bash deploy/scripts/test-sso-e2e.sh
```

## 部署

### 生产部署序列

```bash
# 1. 在服务器上克隆仓库
git clone git@github.com:tishensnoopy/GEO-FLOW-Lumora-Cite.git
cd GEO-FLOW-Lumora-Cite

# 2. 配置生产环境变量
cp .env.example .env.prod
# 编辑 .env.prod，填入生产配置

# 3. 创建 DB 权限隔离
MONITOR_DB_PASSWORD=<password> PGPASSWORD=<geo_user_password> \
  bash deploy/scripts/setup-db-roles.sh

# 4. 配置 .env.prod 中的 MONITOR_DB_USER / MONITOR_DB_PASSWORD

# 5. 启动生产容器
docker compose -f docker-compose.prod.yml up -d --build

# 6. 执行数据库迁移
docker exec <monitor_container> alembic upgrade head

# 7. 同步 GEOFlow 官网入口修改（rsync）
rsync -avz GEOFlow-main/ user@server:/path/to/GEOFlow-main/
```

### GEOFlow-main 同步

GEOFlow-main 是独立的外部项目（.gitignore 排除），修改后通过 rsync 同步到服务器：

```bash
rsync -avz --exclude='.git' --exclude='node_modules' \
  GEOFlow-main/ user@server:/path/to/GEOFlow-main/
```

## 数据库架构

采用 PostgreSQL schema 隔离，GEOFlow 与监测系统共享同一 PG 实例：

| Schema | 所有者 | 用途 | 表 |
|--------|--------|------|-----|
| `public` | geo_user | GEOFlow 数据 | articles, article_distributions, distribution_channels, admins |
| `monitor` | geo_user | 监测系统数据 | clients, client_sites, index_results, citation_results, export_tasks, manual_distributions, admin_audit_logs, archived_distributions, system_config |

**权限隔离（monitor_user）：**
- `public` schema：USAGE + SELECT（只读 GEOFlow 数据）
- `monitor` schema：USAGE + ALL（读写自己的数据）
- 无 CREATE 权限（DDL 留给 geo_user / alembic）

## 核心功能

### 收录检测（IndexChecker）
- 读取 GEOFlow `article_distributions` + 监测系统 `manual_distributions`
- 通过 domain 匹配 `client_sites` 获取 client_id
- 排除已检测的 URL（`index_results`）和 action='delete' 的记录
- 支持百度/Google/Bing/360/搜狗 多引擎检测

### AI 采信检测（CitationChecker）
- 对已收录的 URL 进行 AI 模型引用检测
- 支持 DeepSeek、通义千问等模型
- 生成提问 → 抓取回答 → 匹配内容 → 统计采信率

### 报告导出
- **PDF**：Playwright + Chromium 渲染 HTML 模板，含水印/Logo
- **Excel**：openpyxl 生成 4 工作表（概览/收录明细/采信明细/统计图表）
- 支持自定义图表数据（`charts` JSONB 字段）

### 定时任务（APScheduler）
- `scheduled_index_check`：定期收录检测
- `scheduled_citation_check`：定期 AI 采信检测
- `scheduled_export_processor`：处理 pending 导出任务
- `scheduled_archive_scan`：每日归档已删除的分发记录

### SSO 单点登录
- GEOFlow 作为 IdP（Identity Provider）
- 监测系统作为 SP（Service Provider）
- OAuth 2.0 授权码流程 + CSRF state 参数
- 端点：`/sso/login` → `/sso/authorize` → `/sso/callback` → `/sso/userinfo`

## 文档

- [运维手册](docs/2026-07-25-ops-manual.md) — 部署/日志/重启/健康检查
- [改进部署文档](docs/2026-07-25-improvements-deployment.md) — DB 同步/SSO/权限隔离
- [GEOFlow 监测系统设计](docs/superpowers/specs/2026-07-25-geoflow-monitor-db-sync-design.md)
- [Plan 2 M1-M4 实现计划](docs/superpowers/plans/) — 分里程碑的详细实现计划

## 生产环境

| 域名 | 用途 |
|------|------|
| `monitor.zkeeeai.com` | 监测系统 Dashboard |
| `zkeeeai.com` | GEOFlow 官网 + 后台 |
| `geo_admin/login` | GEOFlow 管理后台 |

- **服务器**：124.220.33.188
- **SSL**：Let's Encrypt（有效期至 2026-10-22）
- **容器**：index-monitor / dashboard / GEOFlow app / PostgreSQL / Redis

## 开发工作流

本项目采用 superpowers 框架驱动开发：
- **TDD**（测试驱动开发）：红-绿-重构循环
- **子智能体驱动开发**：每个任务分派独立子智能体实现 + 审查
- **分支策略**：特性分支 → 代码审查 → 合并到 master

## License

私有项目，未开源。
