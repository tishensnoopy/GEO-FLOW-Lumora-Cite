# GEO 内容分发 + 收录 AI 监测系统 设计规格

**版本**: 1.0  
**日期**: 2026-07-23  
**状态**: 待审查

---

## 1. 项目概述

### 1.1 商业模式

**闭环代运营，按收录效果付费**

- 客户为"最终收录效果"买单
- 系统端到端负责：内容生成 → 推送 → 监测 → 报表展示
- 客户通过 Dashboard 查看收录数据 + AI 采信数据
- 数据准确性、可追溯性、防篡改要求极高

### 1.2 核心目标

1. **内容生成与分发**：GEOFlow 批量生成 SEO/GEO 文章，推送到客户站点 + 自己官网
2. **收录监测**：追踪文章在搜索引擎（百度/头条/搜狗/360/必应）的收录状态
3. **AI 采信检测**：追踪文章是否被 AI 引擎（ChatGPT/文心一言/通义千问等）引用
4. **客户报表**：提供可视化 Dashboard，展示收录效果 + AI 采信效果
5. **多站点管理**：支持官网（自动推送）+ 外站（手动录入 URL）

### 1.3 服务器规格

- **CPU**: 4 核
- **内存**: 4GB
- **磁盘**: 40GB
- **系统**: Ubuntu 22.04 LTS

---

## 2. 系统架构

### 2.1 组件划分

| 组件 | 职责 | 技术栈 | 端口 |
|------|------|--------|------|
| **GEOFlow** | 内容生成 + WordPress 推送 + 公司官网前端 | Laravel 11 + PostgreSQL | 8000 (API) + 80 (官网) |
| **收录检测服务** | 搜索引擎收录检测 | Python + 爬虫 + 第三方 API | 8090 |
| **lumora-cite** | AI 采信检测 | Python + 多 AI 模型 API | 8765 |
| **客户 Dashboard** | 效果展示 + 账号鉴权 | Vue 3 + Element Plus | 3000 |
| **PostgreSQL** | 统一数据库 | PostgreSQL 15 | 5432 |
| **Redis** | 缓存 + 队列 | Redis 7 | 6379 |
| **Nginx** | 反代 + 静态资源 | Nginx | 80/443 |

### 2.2 架构层次

```
┌─────────────────────────────────────────────────────────┐
│                    客户访问层                              │
├─────────────────────────────────────────────────────────┤
│  客户 Dashboard（Vue 3）                                  │
│  ├─ 收录数据（来自收录检测服务）                           │
│  └─ AI 采信数据（来自 lumora-cite）                       │
└─────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│                    数据服务层                              │
├─────────────────────────────────────────────────────────┤
│  收录检测服务（Python）         lumora-cite（Python）      │
│  ├─ 爬虫（百度/头条/搜狗/360/必应）   ├─ AI 模型 API 调用  │
│  └─ 第三方 API（5118 等）             └─ 生成采信报告       │
└─────────────────────────────────────────────────────────┘
                            ↑
┌─────────────────────────────────────────────────────────┐
│                    内容生成层                              │
├─────────────────────────────────────────────────────────┤
│  GEOFlow（Laravel）                                      │
│  ├─ 内容生成                                             │
│  ├─ 推送到客户 WordPress                                 │
│  └─ 推送到自己官网（GEOFlow Agent 渠道）                  │
└─────────────────────────────────────────────────────────┘
```

### 2.3 数据流向

**阶段 1：文章生成与分发**
1. GEOFlow 生成文章（status: published）
2. POST 到客户 WordPress（`/wp-json/wp/v2/posts`）
3. WordPress 返回 remote_url
4. 存入 `article_distributions` 表（article_id, remote_url, status='synced'）
5. **外站文章手动录入**：客户通过 Dashboard 录入外站 URL → 调用 `/api/articles/external` 接口 → 抓取内容快照 → 存入 `index_results` 表（site_type='external'）

**阶段 2：收录检测（每天 1-2 次，定时任务）**
1. Cron 触发（每天 2:00 / 14:00）
2. 查询待检测文章（`SELECT remote_url FROM article_distributions WHERE status='synced'`）
3. 爬虫检测（site: URL 查询）
4. 第三方 API 确认（5118 / 站长工具）
5. 存入 `index_results` 表（url, baidu, toutiao, sogou, so360, bing, checked_at）

**触发机制**：收录检测服务采用**轮询模式**，定时任务每 6 小时扫描一次 `article_distributions` 表中 status='synced' 的文章，与 `index_results` 表对比，找出未检测的新文章加入检测队列。

**阶段 3：AI 采信检测（每周 1-2 次，定时任务）**
1. Cron 触发（每周一/四 3:00）
2. 抽样查询文章（20 篇）
3. 抓取文章内容（`fetch_public_content`）
4. 生成 10 个自然问题
5. 调用多个 AI 模型（GPT/Claude/Gemini/文心）
6. 检查引用（精确/同域/未命中）
7. 存入 `citation_results` 表（url, model, hit_type, sources, checked_at）

**阶段 4：客户查看（随时）**
1. 客户登录（账号密码）
2. 查询收录数据（`SELECT index_results`）
3. 查询采信数据（`SELECT citation_results`）
4. 聚合展示 Dashboard

---

## 3. 数据模型

### 3.1 核心表设计

#### article_distributions（GEOFlow 分发记录）

```sql
CREATE TABLE article_distributions (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    distribution_channel_id INTEGER NOT NULL REFERENCES distribution_channels(id),
    action VARCHAR(32) NOT NULL DEFAULT 'publish',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    remote_id VARCHAR(128),
    remote_url VARCHAR(512),
    remote_meta JSONB,
    idempotency_key VARCHAR(128) UNIQUE,
    attempt_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP,
    last_attempt_at TIMESTAMP,
    last_error_message TEXT,
    payload_hash VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_article_distributions_status ON article_distributions(status);
CREATE INDEX idx_article_distributions_remote_url ON article_distributions(remote_url);
```

**说明**：
- `status`: queued / synced / failed
- `remote_url`: 客户站点的文章 URL
- `remote_meta`: 远程元数据（如 WordPress post_id）

#### index_results（搜索引擎收录状态）

```sql
CREATE TABLE index_results (
    id SERIAL PRIMARY KEY,
    url VARCHAR(512) NOT NULL,
    client_id VARCHAR(64) NOT NULL,
    site_type VARCHAR(32) NOT NULL, -- 'official' / 'external'
    baidu_status VARCHAR(32) DEFAULT 'pending', -- 'pending' / 'indexed' / 'not_indexed'
    toutiao_status VARCHAR(32) DEFAULT 'pending',
    sogou_status VARCHAR(32) DEFAULT 'pending',
    so360_status VARCHAR(32) DEFAULT 'pending',
    bing_status VARCHAR(32) DEFAULT 'pending',
    baidu_checked_at TIMESTAMP,
    toutiao_checked_at TIMESTAMP,
    sogou_checked_at TIMESTAMP,
    so360_checked_at TIMESTAMP,
    bing_checked_at TIMESTAMP,
    content_snapshot TEXT, -- 入库时抓取的原文快照
    content_title VARCHAR(512),
    content_keywords TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url)
);

CREATE INDEX idx_index_results_client_id ON index_results(client_id);
CREATE INDEX idx_index_results_site_type ON index_results(site_type);
CREATE INDEX idx_index_results_baidu_status ON index_results(baidu_status);
```

**说明**：
- `site_type`: official（官网，自动推送）/ external（外站，手动录入）
- `content_snapshot`: 入库时抓取的原文内容快照
- `content_keywords`: 文章关键词（从 GEOFlow 的 `articles.keywords` 字段同步）

#### index_history（收录状态历史记录）

```sql
CREATE TABLE index_history (
    id SERIAL PRIMARY KEY,
    url VARCHAR(512) NOT NULL REFERENCES index_results(url),
    check_date DATE NOT NULL,
    baidu_status VARCHAR(32) NOT NULL,
    toutiao_status VARCHAR(32) NOT NULL,
    sogou_status VARCHAR(32) NOT NULL,
    so360_status VARCHAR(32) NOT NULL,
    bing_status VARCHAR(32) NOT NULL,
    total_indexed INTEGER NOT NULL, -- 当天收录的搜索引擎数量
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, check_date)
);

CREATE INDEX idx_index_history_url ON index_history(url);
CREATE INDEX idx_index_history_check_date ON index_history(check_date);
```

**说明**：
- 每天收录检测后，将当天各搜索引擎的状态写入历史记录
- 用于生成 Dashboard 的趋势图（最近 30 天收录数量变化）
- `total_indexed`：当天收录的搜索引擎数量（0-5）

#### citation_results（AI 采信检测结果）

```sql
CREATE TABLE citation_results (
    id SERIAL PRIMARY KEY,
    url VARCHAR(512) NOT NULL REFERENCES index_results(url),
    model VARCHAR(64) NOT NULL, -- 'chatgpt' / 'wenxin' / 'tongyi' / 'gemini' / 'claude'
    hit_type VARCHAR(32) NOT NULL, -- 'exact' / 'domain' / 'none' / 'unverifiable'
    sources JSONB, -- AI 回答中引用的来源 URL 列表
    question TEXT NOT NULL, -- 检测问题
    answer TEXT, -- AI 回答内容
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, model, question)
);

CREATE INDEX idx_citation_results_url ON citation_results(url);
CREATE INDEX idx_citation_results_model ON citation_results(model);
CREATE INDEX idx_citation_results_hit_type ON citation_results(hit_type);
```

**说明**：
- `hit_type`: exact（精确引用）/ domain（同域名引用）/ none（未命中）/ unverifiable（不可验证）
- `sources`: JSON 数组，存储 AI 回答中引用的所有来源 URL
- `question`: 检测时使用的自然问题

#### clients（客户信息）

```sql
CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    username VARCHAR(128) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(32),
    company_name VARCHAR(255),
    status VARCHAR(32) DEFAULT 'active', -- 'active' / 'inactive'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### client_sites（客户站点）

```sql
CREATE TABLE client_sites (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES clients(client_id),
    site_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    site_type VARCHAR(32) NOT NULL, -- 'official' / 'external'
    wordpress_api_url VARCHAR(512), -- 官网的 WordPress API 地址
    wordpress_api_token VARCHAR(255), -- 官网的 WordPress API Token
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(client_id, domain)
);

CREATE INDEX idx_client_sites_client_id ON client_sites(client_id);
```

#### system_config（系统配置）

```sql
CREATE TABLE system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(128) UNIQUE NOT NULL,
    config_value TEXT NOT NULL,
    config_type VARCHAR(32) NOT NULL, -- 'string' / 'number' / 'boolean' / 'json'
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 初始化默认配置
INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
('index_scan_frequency', '1', 'number', '收录检测频率（天/次），默认每天 1 次'),
('index_scan_time', '02:00', 'string', '收录检测执行时间，默认凌晨 2:00'),
('citation_scan_frequency', '7', 'number', 'AI 采信检测频率（天/次），默认每 7 天 1 次'),
('citation_scan_time', '03:00', 'string', 'AI 采信检测执行时间，默认凌晨 3:00'),
('citation_sample_size', '20', 'number', 'AI 采信检测抽样数量，默认 20 篇'),
('spider_concurrent', '3', 'number', '爬虫并发数，默认 3'),
('spider_interval_min', '2', 'number', '爬虫最小间隔（秒），默认 2 秒'),
('spider_interval_max', '5', 'number', '爬虫最大间隔（秒），默认 5 秒');
```

**说明**：
- 管理后台提供配置界面，可动态调整扫描频率、时间、并发数等参数
- 配置修改后，定时任务自动生效（无需重启服务）
- 支持立即执行按钮，手动触发扫描任务

### 3.2 数据关系

```
clients (1) ──< client_sites (N)
                    │
                    │ (client_id, domain)
                    ↓
            index_results (N)
                    │
                    │ (url)
                    ↓
            citation_results (N)
```

---

## 4. 功能模块

### 4.1 GEOFlow（内容生成 + 分发）

**职责**：
- 批量生成 SEO/GEO 文章
- 推送到客户 WordPress 站点
- 推送到自己官网（GEOFlow Agent 渠道）
- 存储分发记录到 `article_distributions` 表

**关键功能**：
- 文章生成：支持多模型（OpenAI / Gemini / 文心等）
- 任务管理：创建任务、生成数量、审核开关、发布节奏
- 分发渠道：WordPress REST API、通用 HTTP API、GEOFlow Agent
- 分发日志：记录每次分发的状态、错误信息、重试次数

**集成点**：
- 分发成功后，写入 `article_distributions` 表（remote_url, status='synced'）
- 收录检测服务定期读取该表，获取待检测文章

### 4.2 收录检测服务

**职责**：
- 定时检测文章在搜索引擎的收录状态
- 支持 5 个搜索引擎：百度、头条、搜狗、360、必应
- 混合方案：自有爬虫 + 第三方 API

**技术方案**：

**爬虫检测**：
- 使用 `site:客户域名/文章URL` 查询
- UA 轮换 + 随机间隔（2-5 秒）+ 代理池
- 并发数：3-5（适配 4 核 4G）

**第三方 API**：
- 5118 API（百度收录查询）
- 站长工具 API（多引擎收录查询）
- 用于权威确认，避免爬虫误判

**定时任务**：
- 每天 2:00 执行（错峰）
- 增量检测：只检测新增文章（status='pending'）
- 全量巡检：每周日凌晨 2:00 全量检测
- **频率可配置**：管理后台提供扫描频率配置入口（默认每天 1 次）
- **立即扫描**：管理后台提供"立即扫描"按钮，手动触发收录检测任务

**数据存储**：
- 检测结果存入 `index_results` 表
- 更新各搜索引擎的状态和检测时间

### 4.3 lumora-cite（AI 采信检测）

**职责**：
- 定时检测文章是否被 AI 引擎引用
- 支持多个 AI 模型：ChatGPT、Claude、Gemini、文心一言、通义千问
- 生成 Markdown 证据报告

**技术方案**：

**检测流程**：
1. 抓取文章内容（`fetch_public_content`）
2. 分析发布目的，生成 10 个自然问题
3. 调用多个 AI 模型，验证联网搜索能力
4. 检查目标 URL 是否出现在 AI 回答的引用来源中
5. 分类：精确引用 / 同域名引用 / 未命中 / 不可验证

**定时任务**：
- 每 7 天执行一次（默认周一 3:00）
- 抽样检测：每次最多 20 篇文章
- 避免 API 成本过高
- **频率可配置**：管理后台提供扫描频率配置入口（默认每 7 天 1 次）
- **立即扫描**：管理后台提供"立即扫描"按钮，手动触发 AI 采信检测任务

**数据存储**：
- 检测结果存入 `citation_results` 表
- 记录：url, model, hit_type, sources, question, answer

**集成方式**：
- 作为独立服务运行（Python）
- 定时任务调用
- 结果存入 PostgreSQL

### 4.4 客户 Dashboard

**职责**：
- 客户账号密码登录
- 展示收录数据 + AI 采信数据
- 支持多站点切换

**界面设计**：

**登录页**：
- 用户名 + 密码
- 登录后跳转到 Dashboard

**Dashboard 主页**：
- 站点选择器（全部站点 / 单个站点）
- 基础汇总卡片（4 个）：
  - 总文章数
  - 已收录数
  - 收录率（百分比）
  - AI 采信数
- 趋势图（折线图）：最近 30 天收录数量变化
- 各搜索引擎收录分布（柱状图/圆形图标）
- 关键词维度统计（表格）
- 文章列表（可筛选/搜索/排序）

**文章详情弹窗**：
- 文章标题 + 元信息（发布时间、作者、关键词）
- 收录状态（5 个搜索引擎的收录情况，带收录时间）
- AI 采信状态（3 个 AI 引擎的引用情况，带引用时间）
- 原文快照（入库时抓取的内容，可滚动查看）
- 操作按钮（关闭 / 查看原文）

**技术栈**：
- 前端：Vue 3 + Element Plus + ECharts
- 后端：Node.js + Express（或直接调用 PostgreSQL）
- 鉴权：JWT Token

### 4.5 公司官网

**职责**：
- 展示公司服务、案例、吸引客户咨询
- 使用 GEOFlow 的 Blade 主题渲染

**界面设计**：
- 导航栏：Logo + 首页/服务/案例/关于/联系
- Hero 区域：核心价值主张 + 搜索框 + 立即咨询按钮
- 服务亮点：3 个核心卖点（收录保障、AI 采信、多平台分发）
- 精选案例：展示成功案例
- 最新文章：展示最新内容
- 线索表单：收集潜在客户信息
- Footer：版权和备案信息

**技术栈**：
- GEOFlow 自带的 Blade 主题
- 支持主题切换

---

## 5. 部署方案

### 5.1 资源分配（4 核 4G）

| 组件 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| GEOFlow（Laravel + PHP-FPM + 队列） | 1 核 | 1.5GB | 5GB |
| 收录检测服务 | 0.5 核 | 500MB | 2GB |
| lumora-cite | 0.5 核 | 300MB | 2GB |
| 客户 Dashboard（Vue + Node.js） | 0.5 核 | 500MB | 3GB |
| PostgreSQL + Redis | 1 核 | 1GB | 10GB |
| Nginx + 系统 | 0.5 核 | 200MB | 5GB |
| **总计** | **4 核** | **4GB** | **27GB** |

**说明**：
- 剩余 13GB 磁盘用于日志、备份、临时文件
- 内存刚好够，需要严格限流，避免 OOM

### 5.2 部署顺序

1. **基础环境**：系统更新、Docker、Nginx、PostgreSQL、Redis
2. **GEOFlow**：内容生成 + 官网前端
3. **收录检测服务**：定时任务 + 爬虫
4. **lumora-cite**：AI 采信检测
5. **客户 Dashboard**：前端 + 后端

### 5.3 域名规划

- `example.com`：公司官网（GEOFlow 前端）
- `admin.example.com`：GEOFlow 管理后台
- `data.example.com`：客户 Dashboard
- 收录检测服务、lumora-cite：仅内网访问，不暴露公网

---

## 6. 定时任务配置

### 6.1 收录检测

```bash
# 每天 2:00 / 14:00 增量检测
0 2,14 * * * /opt/monitor-service/check_index.sh

# 每周日 2:00 全量巡检
0 2 * * 0 /opt/monitor-service/check_index.sh --full
```

### 6.2 AI 采信检测

```bash
# 每周一/四 3:00 抽样检测
0 3 * * 1,4 /opt/lumora-cite/check_citation.sh
```

### 6.3 数据库备份

```bash
# 每周日 4:00 备份
0 4 * * 0 /root/backup_db.sh
```

### 6.4 日志清理

```bash
# 每天 5:00 清理 30 天前日志
0 5 * * * find /var/log -type f -mtime +30 -delete
```

---

## 7. 安全与权限

### 7.1 客户鉴权

- 账号密码登录（bcrypt 加密）
- JWT Token 鉴权（有效期 7 天）
- 数据隔离：SQL 查询强制携带 `client_id` 过滤

### 7.2 内网隔离

- 收录检测服务、lumora-cite：仅容器内网监听，不映射宿主机端口
- GEOFlow 管理后台：限制 IP 访问（仅管理员 IP）
- 客户 Dashboard：公网访问，但只能查看自己的数据

### 7.3 密钥管理

- 所有 API 密钥存入环境变量，不写入代码
- PostgreSQL 密码、Redis 密码：使用强密码
- 定期轮换密钥（每 3 个月）

### 7.4 日志审计

- 记录所有客户登录日志
- 记录所有数据查询日志
- 记录所有分发任务日志

---

## 8. 测试方案

### 8.1 单元测试

- GEOFlow：文章生成、分发逻辑
- 收录检测服务：爬虫逻辑、API 调用
- lumora-cite：AI 模型调用、引用检查
- 客户 Dashboard：数据查询、鉴权逻辑

### 8.2 集成测试

- GEOFlow → 收录检测服务：验证分发后能正确检测
- 收录检测服务 → lumora-cite：验证数据能正确聚合
- 客户 Dashboard → 数据库：验证数据能正确展示

### 8.3 端到端测试

- 完整流程：生成文章 → 推送 → 检测 → 展示
- 压力测试：模拟 100 个客户同时登录
- 异常测试：模拟 API 失败、网络超时

---

## 9. 运维规范

### 9.1 日常运维

- 每天检查服务状态（systemctl status）
- 每天检查磁盘使用率（df -h）
- 每天检查内存使用率（free -m）
- 每周清理无效监测数据

### 9.2 告警配置

- 磁盘使用率 > 85%：触发告警
- 内存使用率 > 90%：触发告警
- 服务宕机：触发告警
- 告警方式：邮件 / 微信 / 钉钉

### 9.3 备份策略

- 数据库：每周日 4:00 全量备份，保留 30 天
- 配置文件：每次修改后备份
- 日志：保留 30 天，自动清理

---

## 10. 风险与应对

### 10.1 资源不足

**风险**：4 核 4G 资源紧张，可能 OOM

**应对**：
- 严格限流：收录检测并发 3-5，lumora-cite 并发 2-3
- 错峰执行：凌晨执行全量任务
- 监控告警：内存 > 90% 立即告警

### 10.2 爬虫被封

**风险**：搜索引擎反爬，爬虫被封 IP

**应对**：
- UA 轮换 + 随机间隔
- 代理池（至少 10 个 IP）
- 第三方 API 作为备用

### 10.3 AI API 成本

**风险**：lumora-cite 调用多个 AI 模型，API 成本高

**应对**：
- 抽样检测：每次最多 20 篇文章
- 每周 1-2 次，避免频繁调用
- 优先使用便宜的模型（文心、通义）

### 10.4 数据准确性

**风险**：收录检测误判，客户投诉

**应对**：
- 混合方案：爬虫 + 第三方 API 双重确认
- 多次检测：连续 3 次未收录才标记为"未收录"
- 人工复核：客户投诉时人工复核

---

## 11. 后续扩展

### 11.1 短期（3 个月内）

- 支持更多搜索引擎（神马、Yandex）
- 支持更多 AI 模型（豆包、DeepSeek）
- 优化 Dashboard 性能（分页、缓存）

### 11.2 中期（6 个月内）

- 支持多租户（SaaS 模式）
- 支持 API 接口（第三方集成）
- 支持数据导出（Excel / PDF）

### 11.3 长期（1 年内）

- 支持自动化优化（根据收录情况自动调整内容）
- 支持竞品分析（对比竞争对手的收录情况）
- 支持预测分析（预测收录概率）

---

## 12. 附录

### 12.1 术语表

- **GEO**：Generative Engine Optimization，生成式引擎优化
- **SEO**：Search Engine Optimization，搜索引擎优化
- **收录**：文章被搜索引擎索引
- **采信**：文章被 AI 引擎引用
- **快照**：入库时抓取的文章内容

### 12.2 参考资料

- GEOFlow 文档：`/home/tishensnoopy/GEO FLOW+LUMORA CITE/GEOFlow-main/README.md`
- lumora-cite 文档：`/home/tishensnoopy/GEO FLOW+LUMORA CITE/lumora-cite-main/README.md`
- 部署清单：`/home/tishensnoopy/GEO FLOW+LUMORA CITE/GEO内容分发+收录AI监测系统 分步落地部署清单（可直接执行）.md`
- 核心脚本：`/home/tishensnoopy/GEO FLOW+LUMORA CITE/系统落地核心脚本（备份脚本+Webhook接收脚本）.md`

---

**文档结束**
