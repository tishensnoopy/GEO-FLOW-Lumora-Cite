# AI 监测逻辑重构 Phase 4：前端 UI 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 对接 Phase 3 API，实现管理员与客户端视图完整隔离，接入 AI 收录检测/问题监测双阶段管道 UI。

**架构：** 新增 4 个客户端视图 + 1 个 AI 收录视图 + QuestionDrawer 组件 + 3 个 API 模块；重构路由守卫实现角色分流；升级 ScanPanel 支持多 task_id；搭建 Vitest 测试基础设施。

**技术栈：** Vue 3 (Composition API) + Vuex + Vue Router + Element Plus + ECharts + axios + Vitest + @vue/test-utils

**设计文档：** `docs/superpowers/specs/2026-07-30-ai-monitoring-refactor-phase4-design.md`

**Phase 3 API（本计划依赖）：**
- `POST /admin/scan/trigger` — 统一扫描触发（index/ai_index/citation/all），all 返回 `{task_ids: {index, ai_index, citation}}`
- `GET /admin/scan/status/{task_id}` — 任务进度轮询
- `GET/POST/PUT/DELETE /admin/clients/{client_id}/questions` — 客户问题 CRUD
- `POST /admin/clients/{client_id}/questions/reorder` — 问题排序
- `GET /questions` — 客户端只读问题列表
- `POST /admin/ai-index/scan` — 触发 AI 收录检测
- `GET /admin/ai-index/results` — 收录结果列表（url/model/index_status/page 筛选）
- `GET /admin/ai-index/stats` — 收录统计（by_model + by_client）
- `GET /ai-index/overview` — 客户端收录概览
- `GET /citations/evidence` — 客户端引用证据
- `GET /stats` — 客户端统计

**现有前端结构（`dashboard/`）：**
- Vue 3 + Vuex + Vue Router + Element Plus + ECharts
- `src/router/index.js` — 8 路由，`meta.requiresAdmin` 区分
- `src/api/index.js` — 单 axios 实例，baseURL=/api/v1，Bearer token 拦截器
- `src/store/index.js` — Vuex，token/role/indexStats/citationStats
- `src/components/ScanPanel.vue` — 扫描面板，单 task_id 轮询
- `src/views/Clients.vue` — 客户 CRUD（el-table + el-dialog）
- `src/views/Dashboard.vue` — 管理员仪表盘（StatCard + ECharts）
- `src/components/SidebarNav.vue` / `MobileTabBar.vue` — 导航
- `src/styles/tokens.css` — CSS 变量（Ink & Signal 主题）
- `src/components/AppLayout.vue` — 管理员布局

**全局约束：**
1. 客户端路由 `/client/*` 与管理员路由物理隔离，路由守卫按 role 分流
2. 客户端不得访问管理员 API（后端已强制，前端只调 `/ai-index/overview` 等客户端端点）
3. 共享组件（StatusDot、ArticleModal 等）跨角色复用，不重复
4. 保持现有 Ink & Signal 主题风格（tokens.css 变量），新组件沿用
5. ScanPanel `all` 类型展示三阶段顺序进度，每阶段独立进度环
6. QuestionDrawer 拖拽排序用原生 HTML5 drag API（不引入新依赖）
7. 所有新 API 调用通过独立模块文件（`api/aiIndex.js` 等），不堆在 `api/index.js`
8. 测试用 Vitest + @vue/test-utils + jsdom，mock axios 不发真实请求
9. 不破坏现有功能——现有 8 路由的组件保持工作
10. 响应式：Desktop sidebar + Mobile tabbar，断点 1279px/768px

---

## 任务 1：测试基础设施 + 路由隔离重构

**文件：**
- 修改：`dashboard/package.json`（新增 devDependencies）
- 创建：`dashboard/vitest.config.js`
- 创建：`dashboard/tests/setup.js`
- 创建：`dashboard/tests/unit/router.test.js`
- 修改：`dashboard/src/router/index.js`（新增 /client/* 路由 + 守卫重构）
- 创建：`dashboard/src/views/client/ClientOverview.vue`（占位）
- 创建：`dashboard/src/views/client/ClientEvidence.vue`（占位）
- 创建：`dashboard/src/views/client/ClientArticles.vue`（占位）
- 创建：`dashboard/src/views/client/ClientSettings.vue`（占位）
- 创建：`dashboard/src/views/AiIndex.vue`（占位）
- 创建：`dashboard/src/components/ClientLayout.vue`（占位）

- [ ] **步骤 1：编写失败测试 — 路由守卫分流逻辑**

`dashboard/tests/unit/router.test.js`：
```js
import { describe, it, expect, beforeEach } from 'vitest'
import { createRouter } from '../helpers/test-router.js'

// 测试路由守卫的分流逻辑（纯函数提取，不依赖真实 router 实例）
describe('路由守卫分流逻辑', () => {
  it('未登录访问受保护路由 → 跳 /login', () => {
    const decision = decideRoute({ path: '/', meta: { requiresAuth: true }, role: null, token: null })
    expect(decision).toBe('/login')
  })
  it('admin 访问 requiresAdmin 路由 → 放行', () => {
    const decision = decideRoute({ path: '/clients', meta: { requiresAuth: true, requiresAdmin: true }, role: 'admin', token: 'x' })
    expect(decision).toBe(null)  // null 表示放行
  })
  it('client 访问 requiresAdmin 路由 → 跳 /client/overview', () => {
    const decision = decideRoute({ path: '/clients', meta: { requiresAuth: true, requiresAdmin: true }, role: 'client', token: 'x' })
    expect(decision).toBe('/client/overview')
  })
  it('client 访问 / → 跳 /client/overview', () => {
    const decision = decideRoute({ path: '/', meta: { requiresAuth: true }, role: 'client', token: 'x' })
    expect(decision).toBe('/client/overview')
  })
  it('admin 访问 /client/* → 跳 /', () => {
    const decision = decideRoute({ path: '/client/overview', meta: { requiresAuth: true, requiresClient: true }, role: 'admin', token: 'x' })
    expect(decision).toBe('/')
  })
  it('client 访问 /client/overview → 放行', () => {
    const decision = decideRoute({ path: '/client/overview', meta: { requiresAuth: true, requiresClient: true }, role: 'client', token: 'x' })
    expect(decision).toBe(null)
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/unit/router.test.js`
预期：FAIL，`decideRoute` 未定义

- [ ] **步骤 3：安装测试依赖 + 实现路由守卫**

`dashboard/package.json` 新增 devDependencies：
```json
"devDependencies": {
  "@vitejs/plugin-vue": "^5.0.0",
  "vite": "^5.0.0",
  "vitest": "^1.6.0",
  "@vue/test-utils": "^2.4.6",
  "jsdom": "^24.0.0",
  "@vitest/ui": "^1.6.0"
}
```
运行：`cd dashboard && npm install`

`dashboard/vitest.config.js`：
```js
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
  },
  resolve: {
    alias: { '@': '/src' },
  },
})
```

`dashboard/tests/setup.js`：
```js
import { config } from '@vue/test-utils'
// 全局 mock Element Plus 组件，避免测试时注册完整库
config.global.mocks = {}
```

`dashboard/tests/helpers/test-router.js`：导出 `decideRoute` 纯函数 + `createRouter` 工厂

`dashboard/src/router/guard.js`（新增，从守卫逻辑提取纯函数）：
```js
export function decideRoute({ path, meta, role, token }) {
  if (meta.requiresAuth && !token) return '/login'
  if (meta.requiresAdmin && role !== 'admin') return '/client/overview'
  if (path.startsWith('/client') && role === 'admin' && !meta.allowAdminPreview) return '/'
  if (!path.startsWith('/client') && meta.requiresAuth && role === 'client' && path !== '/login') return '/client/overview'
  return null  // 放行
}
```

修改 `dashboard/src/router/index.js`：
- 新增路由 `/ai-index`、`/client/overview`、`/client/evidence`、`/client/articles`、`/client/settings`
- 守卫调用 `decideRoute`，返回非 null 则 `next(返回值)`

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/unit/router.test.js`
预期：PASS，6/6

- [ ] **步骤 5：创建占位视图组件**

为新增路由创建占位 `.vue` 文件（仅 `<template><div>页面名</div></template>`），确保路由不报错。

- [ ] **步骤 6：Commit**

```bash
git add dashboard/package.json dashboard/package-lock.json dashboard/vitest.config.js dashboard/tests/ dashboard/src/router/ dashboard/src/views/AiIndex.vue dashboard/src/views/client/ dashboard/src/components/ClientLayout.vue
git commit -m "feat(frontend): 搭建 Vitest 测试基础设施 + 路由隔离重构（/client/* + 守卫分流）"
```

---

## 任务 2：API 模块 + composables + 单元测试

**文件：**
- 创建：`dashboard/src/api/aiIndex.js`
- 创建：`dashboard/src/api/clientQuestion.js`
- 创建：`dashboard/src/api/clientView.js`
- 创建：`dashboard/src/composables/useScanTrigger.js`
- 创建：`dashboard/tests/unit/api.test.js`
- 创建：`dashboard/tests/unit/useScanTrigger.test.js`

- [ ] **步骤 1：编写失败测试 — API 模块**

`dashboard/tests/unit/api.test.js`：
```js
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { aiIndexApi } from '@/api/aiIndex'
import { clientQuestionApi } from '@/api/clientQuestion'
import { clientViewApi } from '@/api/clientView'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  },
}))

import api from '@/api'

describe('aiIndexApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('triggerScan 调用 POST /admin/ai-index/scan', async () => {
    await aiIndexApi.triggerScan()
    expect(api.post).toHaveBeenCalledWith('/admin/ai-index/scan')
  })
  it('listResults 带 params 调用 GET /admin/ai-index/results', async () => {
    const params = { url: 'x', model: 'doubao', index_status: 'indexed', page: 1, page_size: 20 }
    await aiIndexApi.listResults(params)
    expect(api.get).toHaveBeenCalledWith('/admin/ai-index/results', { params })
  })
  it('getStats 调用 GET /admin/ai-index/stats', async () => {
    await aiIndexApi.getStats()
    expect(api.get).toHaveBeenCalledWith('/admin/ai-index/stats', { params: {} })
  })
})

describe('clientQuestionApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('list 调用 GET /admin/clients/{id}/questions', async () => {
    await clientQuestionApi.list('DEMO001')
    expect(api.get).toHaveBeenCalledWith('/admin/clients/DEMO001/questions')
  })
  it('create 调用 POST', async () => {
    await clientQuestionApi.create('DEMO001', { question: 'test' })
    expect(api.post).toHaveBeenCalledWith('/admin/clients/DEMO001/questions', { question: 'test' })
  })
  it('reorder 调用 POST reorder', async () => {
    await clientQuestionApi.reorder('DEMO001', ['id1', 'id2'])
    expect(api.post).toHaveBeenCalledWith('/admin/clients/DEMO001/questions/reorder', { ordered_ids: ['id1', 'id2'] })
  })
  it('listOwn 调用 GET /questions（客户端只读）', async () => {
    await clientQuestionApi.listOwn()
    expect(api.get).toHaveBeenCalledWith('/questions')
  })
})

describe('clientViewApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('overview 调用 GET /ai-index/overview', async () => {
    await clientViewApi.overview()
    expect(api.get).toHaveBeenCalledWith('/ai-index/overview')
  })
  it('evidence 带 params 调用 GET /citations/evidence', async () => {
    await clientViewApi.evidence({ hit_type: 'exact' })
    expect(api.get).toHaveBeenCalledWith('/citations/evidence', { params: { hit_type: 'exact' } })
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/unit/api.test.js`
预期：FAIL，模块不存在

- [ ] **步骤 3：实现 API 模块**

`dashboard/src/api/aiIndex.js`：
```js
import api from './index'
export const aiIndexApi = {
  triggerScan: () => api.post('/admin/ai-index/scan'),
  triggerRescan: (url) => api.post('/admin/ai-index/rescan', { url }),
  listResults: (params) => api.get('/admin/ai-index/results', { params }),
  getStats: (clientId) => api.get('/admin/ai-index/stats', { params: clientId ? { client_id: clientId } : {} }),
}
```

`dashboard/src/api/clientQuestion.js`：
```js
import api from './index'
export const clientQuestionApi = {
  list: (clientId) => api.get(`/admin/clients/${clientId}/questions`),
  create: (clientId, data) => api.post(`/admin/clients/${clientId}/questions`, data),
  update: (clientId, qid, data) => api.put(`/admin/clients/${clientId}/questions/${qid}`, data),
  delete: (clientId, qid) => api.delete(`/admin/clients/${clientId}/questions/${qid}`),
  reorder: (clientId, orderedIds) => api.post(`/admin/clients/${clientId}/questions/reorder`, { ordered_ids: orderedIds }),
  listOwn: () => api.get('/questions'),
}
```

`dashboard/src/api/clientView.js`：
```js
import api from './index'
export const clientViewApi = {
  overview: () => api.get('/ai-index/overview'),
  evidence: (params) => api.get('/citations/evidence', { params }),
  stats: () => api.get('/stats'),
}
```

- [ ] **步骤 4：实现 useScanTrigger composable + 测试**

`dashboard/tests/unit/useScanTrigger.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { useScanTrigger } from '@/composables/useScanTrigger'
import api from '@/api'

vi.mock('@/api', () => ({ default: { post: vi.fn() } }))

describe('useScanTrigger', () => {
  it('trigger 单类型返回 task_id', async () => {
    api.post.mockResolvedValue({ data: { task_id: 't1' } })
    const { trigger, currentTaskId, panelVisible } = useScanTrigger()
    await trigger('index')
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'index' })
    expect(currentTaskId.value).toBe('t1')
    expect(panelVisible.value).toBe(true)
  })
  it('trigger all 返回 task_ids，currentTaskId 取 index', async () => {
    api.post.mockResolvedValue({ data: { task_ids: { index: 't1', ai_index: 't2', citation: 't3' } } })
    const { trigger, taskIds, currentTaskId } = useScanTrigger()
    await trigger('all')
    expect(taskIds.value).toEqual({ index: 't1', ai_index: 't2', citation: 't3' })
    expect(currentTaskId.value).toBe('t1')
  })
})
```

`dashboard/src/composables/useScanTrigger.js`：实现 trigger 函数，区分单类型与 all。

- [ ] **步骤 5：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/unit/`
预期：PASS（API 测试 + useScanTrigger 测试）

- [ ] **步骤 6：Commit**

```bash
git add dashboard/src/api/aiIndex.js dashboard/src/api/clientQuestion.js dashboard/src/api/clientView.js dashboard/src/composables/useScanTrigger.js dashboard/tests/unit/
git commit -m "feat(frontend): API 模块（aiIndex/clientQuestion/clientView）+ useScanTrigger composable + 单元测试"
```

---

## 任务 3：ScanPanel 升级（ai_index/all + 多 task_id）

**文件：**
- 修改：`dashboard/src/components/ScanPanel.vue`
- 创建：`dashboard/tests/components/ScanPanel.test.js`

- [ ] **步骤 1：编写失败测试 — ScanPanel 多 task_id 展示**

`dashboard/tests/components/ScanPanel.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ScanPanel from '@/components/ScanPanel.vue'

describe('ScanPanel', () => {
  it('all 类型展示三阶段进度环', async () => {
    const wrapper = mount(ScanPanel, {
      props: { modelValue: true, taskId: 't1', taskIds: { index: 't1', ai_index: 't2', citation: 't3' } },
    })
    // 三阶段标签存在
    expect(wrapper.text()).toContain('收录')
    expect(wrapper.text()).toContain('AI 收录')
    expect(wrapper.text()).toContain('采信')
  })
  it('单类型不展示三阶段', () => {
    const wrapper = mount(ScanPanel, {
      props: { modelValue: true, taskId: 't1', taskIds: null },
    })
    expect(wrapper.findAll('.phase-ring').length).toBe(0)
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/components/ScanPanel.test.js`
预期：FAIL，taskIds prop 不存在

- [ ] **步骤 3：升级 ScanPanel**

修改 `dashboard/src/components/ScanPanel.vue`：
- 新增 props：`taskIds`（Object，all 类型时传入）
- `taskIds` 存在时，渲染三阶段进度环区域（`.phase-rings`），每阶段独立轮询 status
- 当前活跃阶段高亮（根据各 task status 判断：completed → 下一阶段 active）
- 新增 scan_type 选项渲染（ai_index/all）— 触发 UI 在父组件，ScanPanel 只负责展示

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/components/ScanPanel.test.js`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/components/ScanPanel.vue dashboard/tests/components/ScanPanel.test.js
git commit -m "feat(frontend): ScanPanel 升级支持 ai_index/all 多 task_id 三阶段进度展示"
```

---

## 任务 4：QuestionDrawer 客户问题管理

**文件：**
- 创建：`dashboard/src/components/QuestionDrawer.vue`
- 修改：`dashboard/src/views/Clients.vue`（操作列新增"问题管理"按钮）
- 创建：`dashboard/tests/components/QuestionDrawer.test.js`

- [ ] **步骤 1：编写失败测试 — QuestionDrawer CRUD 交互**

`dashboard/tests/components/QuestionDrawer.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import QuestionDrawer from '@/components/QuestionDrawer.vue'
import { clientQuestionApi } from '@/api/clientQuestion'

vi.mock('@/api/clientQuestion', () => ({
  clientQuestionApi: {
    list: vi.fn(() => Promise.resolve({ data: [
      { id: 'q1', question: '问题1', sort_order: 0, status: 'active' },
      { id: 'q2', question: '问题2', sort_order: 1, status: 'active' },
    ] })),
    create: vi.fn(() => Promise.resolve({ data: { id: 'q3', question: '新问题', status: 'active' } })),
    delete: vi.fn(() => Promise.resolve({})),
    reorder: vi.fn(() => Promise.resolve({})),
  },
}))

describe('QuestionDrawer', () => {
  it('打开时加载问题列表', async () => {
    const wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      global: { stubs: ['el-drawer', 'el-button', 'el-input', 'el-switch', 'el-icon'] },
    })
    await flushPromises()
    expect(clientQuestionApi.list).toHaveBeenCalledWith('DEMO001')
    expect(wrapper.text()).toContain('问题1')
    expect(wrapper.text()).toContain('问题2')
  })
  it('输入新问题并添加 → 调用 create', async () => {
    const wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      global: { stubs: ['el-drawer', 'el-button', 'el-input', 'el-switch', 'el-icon'] },
    })
    await flushPromises()
    await wrapper.find('.new-question-input').setValue('新问题')
    await wrapper.find('.add-question-btn').trigger('click')
    await flushPromises()
    expect(clientQuestionApi.create).toHaveBeenCalledWith('DEMO001', { question: '新问题' })
  })
  it('删除问题 → 调用 delete', async () => {
    const wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      global: { stubs: ['el-drawer', 'el-button', 'el-input', 'el-switch', 'el-icon', 'el-message-box'] },
    })
    await flushPromises()
    await wrapper.find('.delete-btn').trigger('click')
    await flushPromises()
    expect(clientQuestionApi.delete).toHaveBeenCalledWith('DEMO001', 'q1')
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/components/QuestionDrawer.test.js`
预期：FAIL，组件不存在

- [ ] **步骤 3：实现 QuestionDrawer**

`dashboard/src/components/QuestionDrawer.vue`：
- props：`modelValue`（Boolean）、`clientId`（String）
- 打开时 `clientQuestionApi.list(clientId)` 加载问题
- 问题列表：每项显示文本 + status switch + 编辑/删除按钮
- 新增：底部输入框 + 添加按钮 → `create`
- 拖拽排序：HTML5 draggable，dragend 调 `reorder`
- 删除：ElMessageBox 确认 → `delete`

修改 `dashboard/src/views/Clients.vue`：
- 操作列新增"问题管理"按钮（el-button）
- 引入 QuestionDrawer，绑定 `v-model="questionDrawerVisible"` `:client-id="currentClientId"`
- 按钮点击设置 `currentClientId` 并打开抽屉

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/components/QuestionDrawer.test.js`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/components/QuestionDrawer.vue dashboard/src/views/Clients.vue dashboard/tests/components/QuestionDrawer.test.js
git commit -m "feat(frontend): QuestionDrawer 客户问题管理（CRUD + 拖拽排序）+ Clients.vue 入口"
```

---

## 任务 5：AiIndex 视图（统计 + 图表 + 列表）

**文件：**
- 修改：`dashboard/src/views/AiIndex.vue`（替换占位）
- 创建：`dashboard/src/components/AiIndexStats.vue`
- 创建：`dashboard/src/components/AiIndexTable.vue`
- 创建：`dashboard/tests/components/AiIndex.test.js`

- [ ] **步骤 1：编写失败测试 — AiIndex 数据加载与渲染**

`dashboard/tests/components/AiIndex.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AiIndex from '@/views/AiIndex.vue'
import { aiIndexApi } from '@/api/aiIndex'

vi.mock('@/api/aiIndex', () => ({
  aiIndexApi: {
    getStats: vi.fn(() => Promise.resolve({ data: {
      indexed: 5, not_indexed: 3, pending: 2, rate: 0.625,
      by_model: [{ model: 'doubao', indexed: 3, not_indexed: 1, pending: 0 }],
      by_client: [{ client_id: 'DEMO001', indexed: 5, not_indexed: 3, pending: 2, rate: 0.625 }],
    }})),
    listResults: vi.fn(() => Promise.resolve({ data: {
      items: [{ url: 'https://x.com', model: 'doubao', index_status: 'indexed', checked_at: '2026-07-30T10:00:00Z' }],
      page: 1, page_size: 20,
    }})),
  },
}))

describe('AiIndex', () => {
  it('加载统计与结果', async () => {
    const wrapper = mount(AiIndex, {
      global: { stubs: ['el-table', 'el-table-column', 'el-pagination', 'el-input', 'el-select', 'el-option', 'el-card', 'el-icon'] },
    })
    await flushPromises()
    expect(aiIndexApi.getStats).toHaveBeenCalled()
    expect(aiIndexApi.listResults).toHaveBeenCalled()
    expect(wrapper.text()).toContain('62.5%')  // 收录率
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/components/AiIndex.test.js`
预期：FAIL，AiIndex 是占位组件

- [ ] **步骤 3：实现 AiIndex 视图**

`dashboard/src/views/AiIndex.vue`：
- onMounted 调 `aiIndexApi.getStats()` + `aiIndexApi.listResults(params)`
- 顶部 4 个 StatCard（收录率/已收录/未收录/待检测）
- ECharts by_model 柱状图（各模型 indexed/not_indexed 对比）
- el-table by_client 表格
- 筛选栏（url 输入 + model 下拉 + status 下拉）→ 重新 listResults
- el-table 结果列表 + el-pagination

`dashboard/src/components/AiIndexStats.vue`：统计卡片 + by_model 图表（接收 stats prop）

`dashboard/src/components/AiIndexTable.vue`：结果列表（接收 items + 筛选事件）

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/components/AiIndex.test.js`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/views/AiIndex.vue dashboard/src/components/AiIndexStats.vue dashboard/src/components/AiIndexTable.vue dashboard/tests/components/AiIndex.test.js
git commit -m "feat(frontend): AiIndex 视图（统计卡片 + by_model 图表 + by_client 表格 + 结果列表）"
```

---

## 任务 6：客户端视图（ClientOverview/ClientEvidence/ClientArticles/ClientSettings）

**文件：**
- 修改：`dashboard/src/views/client/ClientOverview.vue`（替换占位）
- 修改：`dashboard/src/views/client/ClientEvidence.vue`（替换占位）
- 修改：`dashboard/src/views/client/ClientArticles.vue`（替换占位）
- 修改：`dashboard/src/views/client/ClientSettings.vue`（替换占位）
- 修改：`dashboard/src/components/ClientLayout.vue`（替换占位）
- 创建：`dashboard/tests/components/ClientViews.test.js`

- [ ] **步骤 1：编写失败测试 — 客户端视图数据隔离**

`dashboard/tests/components/ClientViews.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ClientOverview from '@/views/client/ClientOverview.vue'
import { clientViewApi } from '@/api/clientView'

vi.mock('@/api/clientView', () => ({
  clientViewApi: {
    overview: vi.fn(() => Promise.resolve({ data: {
      indexed_urls: ['https://x.com'], not_indexed_urls: ['https://y.com'],
      index_rate: 0.5,
      articles: [{ url: 'https://x.com', title: '文章A', model: 'doubao', index_status: 'indexed', checked_at: '2026-07-30T10:00:00Z' }],
    }})),
    evidence: vi.fn(() => Promise.resolve({ data: { items: [] }})),
    stats: vi.fn(() => Promise.resolve({ data: {} })),
  },
}))

describe('ClientOverview', () => {
  it('加载 overview 并渲染统计 + 文章列表', async () => {
    const wrapper = mount(ClientOverview, {
      global: { stubs: ['el-card', 'el-table', 'el-table-column', 'el-tag', 'el-icon'] },
    })
    await flushPromises()
    expect(clientViewApi.overview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('50%')  // index_rate
    expect(wrapper.text()).toContain('文章A')
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/components/ClientViews.test.js`
预期：FAIL，ClientOverview 是占位

- [ ] **步骤 3：实现客户端视图**

`ClientOverview.vue`：调 `clientViewApi.overview()`，展示 3 统计卡片（已收录/未收录/收录率）+ 已收录文章列表
`ClientEvidence.vue`：调 `clientViewApi.evidence(params)`，展示引用证据列表 + hit_type 筛选
`ClientArticles.vue`：调 `clientQuestionApi.listOwn()` + `clientViewApi.overview()`，展示监测问题集 + 文章收录情况
`ClientSettings.vue`：修改密码表单（调 `/auth/change-password` 或基础设置）
`ClientLayout.vue`：客户端布局，左侧 sidebar（概览/证据/文章/设置/退出）+ Mobile tabbar，不显示管理员入口

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/components/ClientViews.test.js`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/views/client/ dashboard/src/components/ClientLayout.vue dashboard/tests/components/ClientViews.test.js
git commit -m "feat(frontend): 客户端视图（Overview/Evidence/Articles/Settings）+ ClientLayout 独立布局"
```

---

## 任务 7：自动联动反馈（Distributions.vue 联动状态徽章）

**文件：**
- 修改：`dashboard/src/views/Distributions.vue`
- 创建：`dashboard/src/composables/useAutoPipeline.js`
- 创建：`dashboard/tests/unit/useAutoPipeline.test.js`

- [ ] **步骤 1：编写失败测试 — 联动状态轮询**

`dashboard/tests/unit/useAutoPipeline.test.js`：
```js
import { describe, it, expect, vi } from 'vitest'
import { useAutoPipeline } from '@/composables/useAutoPipeline'
import { aiIndexApi } from '@/api/aiIndex'

vi.mock('@/api/aiIndex', () => ({
  aiIndexApi: {
    listResults: vi.fn(() => Promise.resolve({ data: { items: [{ url: 'x', index_status: 'indexed' }] }})),
  },
}))

describe('useAutoPipeline', () => {
  it('trackUrl 初始状态为 pending', () => {
    const { getStatus } = useAutoPipeline()
    expect(getStatus('x')).toBe('pending')
  })
  it('refresh 后更新状态', async () => {
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    expect(getStatus('x')).toBe('pending')
    await refresh()
    expect(getStatus('x')).toBe('indexed')
  })
})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd dashboard && npx vitest run tests/unit/useAutoPipeline.test.js`
预期：FAIL，模块不存在

- [ ] **步骤 3：实现 useAutoPipeline + Distributions 联动**

`dashboard/src/composables/useAutoPipeline.js`：
- `trackUrl(url)` 注册 URL 追踪
- `refresh()` 查 `aiIndexApi.listResults({url})` 更新状态
- `getStatus(url)` 返回 'pending'|'indexed'|'not_indexed'|'failed'
- 定时轮询（setInterval 3s），收录后停止对该 URL 的轮询

修改 `dashboard/src/views/Distributions.vue`：
- 手动添加文章成功后 `trackUrl(newUrl)` + Toast 提示"正在自动触发 AI 收录检测..."
- 文章列表行展示联动状态徽章（el-tag）：收录检测中/已收录/未收录/检测失败
- 使用 `useAutoPipeline` 的状态驱动徽章颜色与文本

- [ ] **步骤 4：运行测试验证通过**

运行：`cd dashboard && npx vitest run tests/unit/useAutoPipeline.test.js`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/composables/useAutoPipeline.js dashboard/src/views/Distributions.vue dashboard/tests/unit/useAutoPipeline.test.js
git commit -m "feat(frontend): 自动联动反馈（Distributions 联动状态徽章 + useAutoPipeline 轮询）"
```

---

## 任务 8：SidebarNav/MobileTabBar 角色适配 + 最终视觉验证

**文件：**
- 修改：`dashboard/src/components/SidebarNav.vue`
- 修改：`dashboard/src/components/MobileTabBar.vue`
- 修改：`dashboard/src/App.vue`（按角色选择 layout：AppLayout vs ClientLayout）
- 修改：`dashboard/src/store/index.js`（新增 aiIndexStats 状态）

- [ ] **步骤 1：实现角色适配**

修改 `SidebarNav.vue`：
- 从 store 读取 `role`
- admin：显示 仪表盘/分发记录/文章列表/AI 收录检测/导出报告/客户管理/审计日志/系统设置/退出
- client：不显示（客户端用 ClientLayout 的 sidebar）

修改 `MobileTabBar.vue`：
- admin：仪表/分发/收录/采信/设置（现有）
- client：概览/证据/文章/设置

修改 `App.vue`：
- `role === 'client'` 且路径 `/client/*` → 用 ClientLayout
- 否则用 AppLayout
- 登录后按 role 跳转：admin → `/`，client → `/client/overview`

修改 `store/index.js`：新增 `aiIndexStats` state + `fetchAiIndexStats` action

- [ ] **步骤 2：运行全部前端测试**

运行：`cd dashboard && npx vitest run`
预期：全部 PASS

- [ ] **步骤 3：构建验证**

运行：`cd dashboard && npm run build`
预期：构建成功，无报错

- [ ] **步骤 4：Commit**

```bash
git add dashboard/src/components/SidebarNav.vue dashboard/src/components/MobileTabBar.vue dashboard/src/App.vue dashboard/src/store/index.js
git commit -m "feat(frontend): SidebarNav/MobileTabBar 角色适配 + App.vue layout 分流 + store 扩展"
```

---

## 自检

**1. 规格覆盖度：** 对照设计文档 8 节——路由隔离(任务1) ✅，API模块(任务2) ✅，ScanPanel(任务3) ✅，QuestionDrawer(任务4) ✅，AiIndex(任务5) ✅，客户端视图(任务6) ✅，自动联动(任务7) ✅，角色适配(任务8) ✅。

**2. 占位符扫描：** 无 TODO/待定，每个步骤有具体代码或明确指令。

**3. 类型一致性：** `taskIds` 在 useScanTrigger/ScanPanel 中均为 `{index, ai_index, citation} | null`；`clientQuestionApi` 签名跨任务一致。

**4. 测试覆盖：** 每个任务都有失败测试→实现→通过验证，覆盖 API/组件/composable/路由守卫。

---

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-07-30-ai-monitoring-refactor-phase4.md`。采用子代理驱动方式执行（用户已确认），每个任务一个新子代理 + 两阶段审查，最终整分支审查后合并。
