# 更新记录

## [2026-07-26] 客户报告体验增强 + 文章标题抓取修复 + 前端性能优化

### 问题背景

用户反馈 4 个核心问题：
1. 客户下载的 PDF 报告不含截图/快照，AI 采信部分缺失，搜索引擎部分过于简陋
2. 文章列表中所有文章标题为空
3. 点击「分发记录」和「导出报告」标签页经常卡住
4. 客户无法从数据总览页导出含图表的报告

### 修复内容

#### 1. 文章标题抓取修复（根因修复）

**文件**: `index-monitor/app/services/article_fetcher.py`

**根因**: 原 User-Agent `"Mozilla/5.0 (compatible; ZkeeeAIMonitor/1.0)"` 被多数网站识别为爬虫，返回 403 或空页面，导致 `content_title` 始终为空。

**修复**:
- 替换为真实 Chrome 浏览器 UA（`Chrome/120.0.0.0 Safari/537.36`）
- 添加 `Accept` 和 `Accept-Language` 请求头，模拟真实浏览器行为
- 添加详细日志（HTTP 状态码、内容长度、解析过程），便于诊断
- 支持 lxml 解析失败时自动回退到 html.parser

**验证**: 回填脚本成功抓取生产环境 2/3 篇文章标题（第 1 篇为测试 URL，返回 404 符合预期）

#### 2. PDF 报告内容大幅增强

**文件**: `index-monitor/app/templates/report.html`, `index-monitor/app/services/export_service.py`

**新增章节**:
- **五、AI 采信详情**: 从简表升级为卡片式展示，包含 AI 模型标签、命中类型彩色标签、检测问题、**完整 AI 回答原文**（前 500 字）、文章 URL
- **六、文章原文快照**: 新增章节，每篇文章展示标题 + URL + 内容快照前 300 字

**数据流修复**:
- `export_service.py` 新增 `content_snapshot` 字段传入模板
- `export_service.py` 新增 `answer` 和 `sources` 字段到采信检测结果

#### 3. 前端分页性能优化

**文件**: `index-monitor/app/api/admin_routes.py`, `index-monitor/app/api/export_routes.py`, `dashboard/src/views/Exports.vue`

**根因**: 后端 `/distributions` 和 `/admin/distributions` 端点未实现真正的分页，返回全量数据导致前端渲染卡顿。

**修复**:
- 两个分发记录端点新增 `page`/`page_size` 参数，后端切片返回
- `/exports` 端点新增 `total` 计数，支持前端分页组件
- `Exports.vue` 添加分页 UI 组件（el-pagination）

#### 4. 客户导出入口修复

**文件**: `dashboard/src/views/Dashboard.vue`, `dashboard/src/components/ExportDialog.vue`

**根因**: Dashboard 的「导出报告（含图表）」按钮有 `v-if="isAdmin"` 限制，客户角色看不到，只能从「导出报告」页面触发（不含图表）。

**修复**:
- 移除 `v-if="isAdmin"` 限制，所有用户均可从数据总览页导出含图表的报告
- 优化 ExportDialog 提示文案，从 warning 改为 info，引导用户前往数据总览页

#### 5. 文章标题回填脚本（新增）

**文件**: `index-monitor/scripts/backfill_article_titles.py`

新增回填脚本，用于为已有 `index_results` 记录中 `content_title` 为空的行重新抓取标题。修复 UA 后可一键回填历史数据。

**使用方法**:
```bash
docker exec geo-index-monitor python -m scripts.backfill_article_titles
```

---

## [2026-07-26] 客户管理增强 + 登录体验优化

### 客户服务期管理

**文件**: `index-monitor/app/models/client.py`, `index-monitor/app/api/admin_routes.py`, `dashboard/src/views/Clients.vue`

- Client 模型新增 `service_start_date` 和 `service_end_date` 字段
- 创建/编辑客户 API 支持服务期设置
- 前端客户管理页展示服务期 + 自动计算状态标签（🟢服务中 / 🟡X天后到期 / 🔴已过期 / ⚪未设置）

### 客户登录体验优化

**文件**: `index-monitor/app/api/client_auth_routes.py`, `dashboard/src/views/Login.vue`, `dashboard/src/api/index.js`

- 支持用户名登录（替代 client_id，更友好的客户分发体验）
- 修复登录错误无提示问题：axios 拦截器跳过登录请求的 401 重定向，允许错误提示显示
- 修复客户登录后 Dashboard 闪退问题：角色特定 API 调用（admin 用 `/admin/distributions`，client 用 `/distributions`）

### 文章列表数据增强

**文件**: `dashboard/src/views/Articles.vue`, `dashboard/src/components/ArticleModal.vue`

- 文章列表 AI 采信列显示命中次数（如 "3/5 次命中"）
- 文章详情弹窗新增 AI 采信详情区域：AI 模型、检测问题、命中类型、AI 回答原文（可展开）

---

## [2026-07-26] SSO 集成 + 基础设施修复

### SSO 单点登录

- GEOFlow 作为 IdP，监测系统通过 OAuth 2.0 接入
- CSRF state 参数防重放攻击
- Redis 存储 state，支持分布式验证
- SSO 登录后自动跳转回监测系统 Dashboard

### 认证修复

- GEOFlow 登录 500 错误：PHP 8.4 解析 `$2b$` 哈希失败，重新生成 `$2y$` 前缀哈希
- SSO `invalid_state` 错误：浏览器缓存旧 state，清缓存 + 无痕模式解决
- 客户登录重定向循环：axios 拦截器对登录请求跳过 401 重定向

### 导航增强

- Dashboard 顶部导航新增「GEOFlow 后台」菜单项，支持 SSO 自动登录跳转
- 修正菜单链接从 `/geoflow-admin` 改为外部链接 `https://zkeeeai.com/geo_admin`

---

## 部署清单

### 本次部署涉及的容器重建

```bash
# 重建 index-monitor + dashboard 镜像
docker compose --env-file .env.prod -f docker-compose.prod.yml build index-monitor dashboard

# 重启容器
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d index-monitor dashboard

# 回填文章标题（修复 UA 后重新抓取）
docker exec geo-index-monitor python -m scripts.backfill_article_titles
```

### 验证清单

- [x] 前端 monitor.zkeeeai.com 返回 200
- [x] 前端 zkeeeai.com 返回 200
- [x] index-monitor 健康检查通过
- [x] 文章标题回填成功（2/3 篇，1 篇测试 URL 预期 404）
- [x] 服务器资源充足（2.4G 内存 / 24G 磁盘）
- [x] 无错误日志
