# AI 监测逻辑重构 Phase 4：前端 UI 设计规格

> **关联：** Phase 3 API 层设计 `docs/superpowers/specs/2026-07-30-ai-monitoring-refactor-phase3-design.md`
> **影响层：** 前端 Dashboard（Vue 3 + Element Plus + ECharts）
> **目标：** 对接 Phase 3 新增 API，实现管理员与客户端视图完整隔离，接入 AI 收录检测/问题监测双阶段管道 UI

---

## 1. 架构决策

### 1.1 客户端视图隔离方案：独立路由前缀 `/client/*`

**决策：** 客户端专属页面使用独立路由前缀 `/client/*`，与管理员路由物理隔离。路由守卫按 `role` 分流：admin 登录后进 `/`，client 登录后进 `/client/overview`。

**理由：**
- P3 设计约束 #1 要求"管理员与客户端完整隔离"——独立路由是最彻底的隔离
- 避免组件内 `v-if="role==='client'"` 条件渲染导致的逻辑耦合
- 后续客户端功能扩展清晰，不污染管理员路由
- 共享组件（如 ArticleModal、StatusDot）仍可跨角色复用，不重复造轮子

### 1.2 路由结构（重构后）

```
管理员路由（role==='admin' 可访问）：
  /                 → Dashboard（管理员总览）
  /articles         → Articles（文章列表）
  /distributions    → Distributions（分发记录）
  /ai-index         → AiIndex（AI 收录检测视图）★新增
  /exports          → Exports（导出报告）
  /clients          → Clients（客户管理，含问题管理抽屉）★增强
  /audit-logs       → AuditLogs（审计日志）
  /settings         → Settings（系统设置）

客户端路由（role==='client' 可访问，前缀 /client）：
  /client/overview  → ClientOverview（客户端概览）★新增
  /client/evidence  → ClientEvidence（引用证据）★新增
  /client/articles  → ClientArticles（我的文章）★新增
  /client/settings  → ClientSettings（客户端设置）★新增

公共路由：
  /login            → Login（登录页）
```

**路由守卫逻辑：**
```js
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const role = localStorage.getItem('role')
  if (to.meta.requiresAuth && !token) return next('/login')
  // admin 专用路由
  if (to.meta.requiresAdmin && role !== 'admin') return next('/client/overview')
  // client 专用路由
  if (to.meta.requiresClient && role !== 'client' && role !== 'admin') return next('/login')
  // 角色分流：admin 访问 /client/* 跳回 /，client 访问 admin 路由跳 /client/overview
  if (to.path.startsWith('/client') && role === 'admin' && !to.meta.allowAdminPreview) {
    return next('/')
  }
  if (!to.path.startsWith('/client') && to.meta.requiresAuth && role === 'client' && to.path !== '/login') {
    return next('/client/overview')
  }
  next()
})
```

### 1.3 客户问题管理入口：Clients.vue 内嵌抽屉

**决策：** 在 Clients.vue 客户列表操作列新增"问题管理"按钮，点击弹出右侧抽屉（el-drawer），内含问题 CRUD + 拖拽排序。

**理由：**
- 不新增路由，操作流畅，与客户上下文紧密
- 抽屉空间足够展示问题列表 + 编辑表单
- 问题集与客户强绑定，不应脱离客户上下文

### 1.4 AI 收录检测视图：独立页面 `/ai-index`

**决策：** 新增独立路由 `/ai-index`，展示：顶部统计卡片（收录率/已收录/未收录/pending）+ by_model 柱状图 + by_client 表格 + 结果列表（含 url/model/status 筛选）。

### 1.5 测试策略

**现状：** 前端无测试基础设施。

**P4 策略：**
- 任务 1 搭建 Vitest + @vue/test-utils + jsdom 测试基础设施
- 关键业务逻辑（API 封装、数据转换、计算属性）→ Vitest 单元测试
- 关键组件渲染和交互（QuestionDrawer、ScanPanel、ClientOverview）→ @vue/test-utils 组件测试
- 现有 Playwright 用于最终 E2E 验证（已在 index-monitor 测试中用）

---

## 2. 新增/修改文件清单

### 2.1 新增文件

| 文件 | 职责 |
|------|------|
| `dashboard/src/views/AiIndex.vue` | AI 收录检测视图（统计+图表+列表） |
| `dashboard/src/views/client/ClientOverview.vue` | 客户端概览（收录概览+统计卡片） |
| `dashboard/src/views/client/ClientEvidence.vue` | 客户端引用证据列表 |
| `dashboard/src/views/client/ClientArticles.vue` | 客户端我的文章 |
| `dashboard/src/views/client/ClientSettings.vue` | 客户端设置 |
| `dashboard/src/components/QuestionDrawer.vue` | 客户问题管理抽屉（CRUD+排序） |
| `dashboard/src/components/AiIndexStats.vue` | AI 收录统计卡片+图表 |
| `dashboard/src/components/AiIndexTable.vue` | AI 收录结果列表（筛选+分页） |
| `dashboard/src/components/ClientLayout.vue` | 客户端布局（独立 sidebar/tabbar） |
| `dashboard/src/api/aiIndex.js` | AI 收录检测 API 模块 |
| `dashboard/src/api/clientQuestion.js` | 客户问题管理 API 模块 |
| `dashboard/src/api/clientView.js` | 客户端只读 API 模块 |
| `dashboard/src/composables/useScanTrigger.js` | 扫描触发逻辑复用（支持多 task_id） |
| `dashboard/tests/setup.js` | Vitest 测试环境 setup |
| `dashboard/tests/unit/` | 单元测试目录 |
| `dashboard/tests/components/` | 组件测试目录 |

### 2.2 修改文件

| 文件 | 改动 |
|------|------|
| `dashboard/src/router/index.js` | 新增 /ai-index、/client/* 路由，重构守卫逻辑 |
| `dashboard/src/components/ScanPanel.vue` | 新增 ai_index/all 扫描类型，支持多 task_id 进度 |
| `dashboard/src/views/Clients.vue` | 操作列新增"问题管理"按钮，引入 QuestionDrawer |
| `dashboard/src/views/Distributions.vue` | 手动添加文章后展示自动联动进度提示 |
| `dashboard/src/components/SidebarNav.vue` | 新增 AI 收录菜单项，按角色显示不同导航 |
| `dashboard/src/components/MobileTabBar.vue` | 按角色显示不同底部 tab |
| `dashboard/src/store/index.js` | 新增 aiIndexStats、clientQuestions 状态 |
| `dashboard/src/api/index.js` | 保持不变（新 API 模块独立文件） |
| `dashboard/src/main.js` | 注册新路由（无需改，router 自动注入） |
| `dashboard/package.json` | 新增 vitest、@vue/test-utils、jsdom 依赖 |

---

## 3. 核心组件设计

### 3.1 ScanPanel 升级

**现状：** 支持 index/citation/both，单 task_id 轮询。

**升级点：**
1. 扫描类型选项新增 `ai_index`（AI 收录检测）和 `all`（全量顺序扫描）
2. `all` 类型调用 `/admin/scan/trigger`，返回 `{task_ids: {index, ai_index, citation}}`，面板内分段展示三阶段进度
3. 新增 `_run_sequential_all_background` 的进度展示——三阶段串联，每阶段独立进度环
4. 采信模型状态卡片复用现有 `citation_models` 结构
5. AI 收录检测阶段展示 `by_model` 进度（已收录/未收录/pending）

**ScanPanel 新增 scan_type 选项：**
```js
const scanTypeOptions = [
  { label: '搜索引擎收录', value: 'index' },
  { label: 'AI 收录检测', value: 'ai_index' },      // ★新增
  { label: 'AI 采信检测', value: 'citation' },
  { label: '收录+采信', value: 'both' },
  { label: '全量扫描（顺序）', value: 'all' },       // ★新增
]
```

**多 task_id 进度展示：** `all` 类型时面板内显示 3 个进度环（index → ai_index → citation），当前活跃阶段高亮，已完成阶段打勾，未开始阶段灰色。

### 3.2 QuestionDrawer 组件

**职责：** 客户问题管理抽屉，在 Clients.vue 中通过按钮触发。

**UI 结构：**
```
el-drawer（右侧滑出，宽 480px）
  ├─ 头部：客户名称 + 问题数统计
  ├─ 问题列表（可拖拽排序）
  │   ├─ 问题项 1 [拖拽手柄] [问题文本] [状态切换] [编辑] [删除]
  │   ├─ 问题项 2 ...
  │   └─ 问题项 N ...
  ├─ 新增问题输入框 + 添加按钮
  └─ 底部：保存排序按钮 + 关闭
```

**交互：**
- 拖拽排序：使用原生 HTML5 drag API 或 Sortable.js（轻量）
- 状态切换：active ↔ inactive（el-switch）
- 编辑：行内编辑或弹出小对话框
- 删除：确认对话框
- 新增：输入框 + 回车或按钮提交

**API 对接：**
- `GET /admin/clients/{client_id}/questions` → 列表
- `POST /admin/clients/{client_id}/questions` → 新增
- `PUT /admin/clients/{client_id}/questions/{qid}` → 编辑/状态
- `DELETE /admin/clients/{client_id}/questions/{qid}` → 删除
- `POST /admin/clients/{client_id}/questions/reorder` → 排序

### 3.3 AiIndex 视图

**布局：**
```
/ai-index 页面
  ├─ 顶部统计卡片（4 个）
  │   ├─ 收录率（indexed / (indexed + not_indexed)）
  │   ├─ 已收录（distinct URL 数）
  │   ├─ 未收录（distinct URL 数）
  │   └─ 待检测（pending 数）
  ├─ 图表区（Bento 网格）
  │   ├─ by_model 柱状图（各模型的 indexed/not_indexed 对比）
  │   └─ by_client 表格（client_id → indexed/not_indexed/pending/rate）
  ├─ 筛选栏（url 搜索 + model 下拉 + status 下拉）
  └─ 结果列表（url + title + model + index_status + checked_at + 分页）
```

**API 对接：**
- `GET /admin/ai-index/stats` → 统计卡片 + by_model + by_client
- `GET /admin/ai-index/results?url=&model=&index_status=&page=&page_size=` → 结果列表

### 3.4 客户端视图

#### ClientOverview（/client/overview）

**展示：** 客户自己的收录概览（调用 `/ai-index/overview`）
```
  ├─ 统计卡片（3 个）
  │   ├─ 已收录 URL 数
  │   ├─ 未收录 URL 数
  │   └─ 收录率
  ├─ 已收录文章列表（url + title + model + checked_at）
  └─ 快捷入口（查看引用证据 → /client/evidence）
```

#### ClientEvidence（/client/evidence）

**展示：** 客户自己的引用证据（调用 `/citations/evidence`）
```
  ├─ 统计卡片（被引用次数 / 命中模型数 / 引用率）
  ├─ 证据列表
  │   ├─ 文章标题 + URL
  │   ├─ 引用该文章的模型 + 问题
  │   ├─ 命中类型（exact/domain/none）+ AI 回答摘要
  │   └─ 检测时间
  └─ 筛选（hit_type 下拉）
```

#### ClientArticles（/client/articles）

**展示：** 客户自己的文章列表（只读，调用 `/questions` 获取监测问题 + `/ai-index/overview` 的 articles）
```
  ├─ 我的监测问题集（只读列表，展示客户被监测的问题）
  └─ 我的文章收录情况（url + title + 各模型收录状态）
```

#### ClientSettings（/client/settings）

**展示：** 客户端设置（修改密码等基础功能，不含管理员配置）

### 3.5 ClientLayout 组件

**职责：** 客户端独立布局，与管理员 AppLayout 隔离。

**结构：**
- Desktop：左侧 sidebar（概览/引用证据/我的文章/设置/退出登录）
- Mobile：底部 tab bar（概览/证据/文章/设置）
- 不显示管理员专属入口（客户管理/审计日志/AI 收录检测视图/系统设置）

### 3.6 自动联动反馈

**位置：** Distributions.vue 的手动添加文章流程。

**交互：** 手动添加文章成功后，Toast 提示"文章已添加，正在自动触发 AI 收录检测..."，并在文章列表该行展示联动状态徽章：
- `收录检测中`（黄色，旋转图标）
- `已收录，问题监测中`（蓝色，旋转图标）
- `监测完成`（绿色，对勾）
- `未收录`（灰色）
- `检测失败`（红色）

**实现：** 轮询 `/admin/ai-index/results?url=xxx` 获取收录状态，收录后轮询 `/admin/citation/results` 获取采信状态。轮询间隔 3s，最多 5 分钟后停止。

---

## 4. 状态管理扩展

`store/index.js` 新增：

```js
state: {
  // 既有...
  aiIndexStats: { indexed: 0, not_indexed: 0, pending: 0, rate: 0, by_model: [], by_client: [] },
  clientQuestions: [],  // 当前抽屉打开客户的的问题列表
  autoPipelineStatus: {},  // url → { ai_index: 'pending'|'indexed'|'failed', citation: 'pending'|'done'|'failed' }
}
```

---

## 5. API 模块设计

### 5.1 `api/aiIndex.js`

```js
import api from './index'

export const aiIndexApi = {
  triggerScan: () => api.post('/admin/ai-index/scan'),
  triggerRescan: (url) => api.post('/admin/ai-index/rescan', { url }),
  listResults: (params) => api.get('/admin/ai-index/results', { params }),
  getStats: (clientId?) => api.get('/admin/ai-index/stats', { params: { client_id: clientId } }),
}
```

### 5.2 `api/clientQuestion.js`

```js
import api from './index'

export const clientQuestionApi = {
  list: (clientId) => api.get(`/admin/clients/${clientId}/questions`),
  create: (clientId, data) => api.post(`/admin/clients/${clientId}/questions`, data),
  update: (clientId, qid, data) => api.put(`/admin/clients/${clientId}/questions/${qid}`, data),
  delete: (clientId, qid) => api.delete(`/admin/clients/${clientId}/questions/${qid}`),
  reorder: (clientId, orderedIds) => api.post(`/admin/clients/${clientId}/questions/reorder`, { ordered_ids: orderedIds }),
  listOwn: () => api.get('/questions'),  // 客户端只读
}
```

### 5.3 `api/clientView.js`

```js
import api from './index'

export const clientViewApi = {
  overview: () => api.get('/ai-index/overview'),
  evidence: (params?) => api.get('/citations/evidence', { params }),
  stats: () => api.get('/stats'),
}
```

### 5.4 `composables/useScanTrigger.js`

```js
import { ref } from 'vue'
import api from '@/api'

export function useScanTrigger() {
  const taskIds = ref(null)  // all 类型时为 {index, ai_index, citation}
  const currentTaskId = ref(null)
  const panelVisible = ref(false)

  async function trigger(scanType, options = {}) {
    const res = await api.post('/admin/scan/trigger', { scan_type: scanType, ...options })
    if (scanType === 'all') {
      taskIds.value = res.data.task_ids
      currentTaskId.value = res.data.task_ids.index  // 从 index 阶段开始展示
    } else {
      currentTaskId.value = res.data.task_id
    }
    panelVisible.value = true
    return res.data
  }

  return { taskIds, currentTaskId, panelVisible, trigger }
}
```

---

## 6. 测试计划

### 6.1 单元测试（Vitest）

- `api/aiIndex.js`、`api/clientQuestion.js`、`api/clientView.js`：mock axios，验证 URL/方法/参数
- `composables/useScanTrigger.js`：验证 trigger 返回值、多 task_id 处理
- 路由守卫纯函数：验证各 role × 各 path 的分流结果

### 6.2 组件测试（@vue/test-utils）

- `QuestionDrawer`：挂载 → 渲染列表 → 新增/编辑/删除交互 → 排序触发 reorder API
- `ScanPanel`：scan_type 选项渲染 → all 类型多 task_id 进度展示
- `AiIndexStats`：统计卡片渲染 → by_model 图表数据传入
- `ClientOverview`：挂载 → 调用 overview API → 渲染统计 + 文章列表
- 路由守卫：各角色访问各路径的跳转断言

### 6.3 E2E 验证（Playwright，最终阶段）

- 管理员触发 all 扫描 → ScanPanel 展示三阶段顺序进度
- 管理员为客户配置问题 → 抽屉 CRUD + 排序
- 客户端登录 → 看到 /client/overview（非管理员 Dashboard）
- 客户端访问 /admin 路由 → 跳回 /client/overview
- 管理员访问 /client/* → 跳回 /

---

## 7. 不实现的范围（YAGNI）

- 不做问题模板库（客户问题手动输入即可）
- 不做 AI 收录检测的实时 WebSocket 推送（轮询足够）
- 不做客户端的导出功能（P3 未提供客户端导出 API）
- 不做管理员的 AI 收录检测手动重试 UI（已有 trigger_rescan API，但 UI 延后）
- 不重构现有 Dashboard 图表（保持现状，仅新增 AI 收录视图）

---

## 8. 实现顺序（Phase 4 任务分解）

1. **任务 1**：测试基础设施 + 路由隔离重构（Vitest 安装 + 路由守卫 + ClientLayout）
2. **任务 2**：API 模块 + composables（aiIndex/clientQuestion/clientView + useScanTrigger）+ 单元测试
3. **任务 3**：ScanPanel 升级（ai_index/all 扫描类型 + 多 task_id 进度）+ 组件测试
4. **任务 4**：QuestionDrawer 客户问题管理（CRUD + 排序）+ 组件测试
5. **任务 5**：AiIndex 视图（统计 + 图表 + 列表）+ 组件测试
6. **任务 6**：客户端视图（ClientOverview/ClientEvidence/ClientArticles/ClientSettings）+ 组件测试
7. **任务 7**：自动联动反馈（Distributions.vue 联动状态徽章 + 轮询）
8. **任务 8**：SidebarNav/MobileTabBar 角色适配 + 最终视觉验证
