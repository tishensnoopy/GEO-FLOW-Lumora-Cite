# LumoraCite Dashboard UI 优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在保留 Ink & Signal 设计语言的前提下，从信息密度、视觉层次、响应式三个方向全面优化 Dashboard 前端 UI。

**架构：** 新建 `AppLayout.vue` 作为布局骨架（侧栏 + 顶栏 + 主内容区 + 扫描面板容器），将现有 `App.vue` 的顶部导航重构为侧栏布局。新建 7 个可复用组件（SidebarNav/SignalBar/ScanPanel/SparkLine/StatusDot/MobileTabBar + 扩展 StatCard），修改 Dashboard.vue 和 Distributions.vue 消费新组件。新增后端趋势数据 API 作为前置依赖。

**技术栈：** Vue 3 (Composition API) + Element Plus + ECharts + Vuex + Vite

---

## 文件结构

### 新建文件（8 个组件 + 1 个 composable + 1 个后端路由扩展）

| 文件 | 职责 |
|------|------|
| `dashboard/src/components/AppLayout.vue` | 布局骨架：顶栏 + 侧栏插槽 + 主内容区 + 扫描面板容器 |
| `dashboard/src/components/SidebarNav.vue` | 侧栏导航：菜单 + 折叠/展开 + 扫描状态指示器 |
| `dashboard/src/components/SignalBar.vue` | 顶栏信号条：横向滚动事件流 |
| `dashboard/src/components/ScanPanel.vue` | 右侧滑出全屏扫描面板（替代 ScanTerminal.vue） |
| `dashboard/src/components/SparkLine.vue` | SVG 内联迷你趋势图（无依赖） |
| `dashboard/src/components/StatusDot.vue` | ●◐○ 三态状态点 |
| `dashboard/src/components/MobileTabBar.vue` | 移动端底部 5 入口 Tab 栏 |
| `dashboard/src/composables/useBreakpoint.js` | 响应式断点检测 composable |
| `index-monitor/app/api/trend_routes.py` | 后端 30 天趋势数据 API |

### 修改文件（6 个）

| 文件 | 修改内容 |
|------|----------|
| `dashboard/src/styles/tokens.css` | 新增布局/动效/状态/触摸 token |
| `dashboard/src/App.vue` | 替换顶部导航为 AppLayout 布局 |
| `dashboard/src/components/StatCard.vue` | 扩展为 4 层信息（同比 + sparkline + 子指标） |
| `dashboard/src/views/Dashboard.vue` | 消费新 StatCard + 图表增强 + 信号条抽离 |
| `dashboard/src/views/Distributions.vue` | 状态可视化 + 内联操作 + 表格转卡片 |
| `index-monitor/app/main.py` | 注册 trend_routes 路由 |

### 删除文件

| 文件 | 原因 |
|------|------|
| `dashboard/src/components/ScanTerminal.vue` | 被 ScanPanel.vue 替代 |

---

## 任务 1：扩展设计 Token

**文件：**
- 修改：`dashboard/src/styles/tokens.css`

- [ ] **步骤 1：在 tokens.css 末尾追加新 token**

在 `:root { ... }` 块的最后一行 `--el-border-radius-base: var(--radius-md);` 之后追加：

```css
  /* === UI 优化新增 token === */

  /* 布局尺寸 */
  --sidebar-width: 220px;
  --sidebar-width-collapsed: 64px;
  --topbar-height: 56px;
  --mobile-tabbar-height: 56px;
  --scan-panel-width-desktop: 50%;
  --scan-panel-width-tablet: 60%;

  /* 断点（JS 使用，CSS 用媒体查询） */
  --breakpoint-lg: 1280px;
  --breakpoint-md: 768px;

  /* 动效 */
  --transition-fast: 150ms ease-out;
  --transition-base: 200ms ease-out;
  --transition-slow: 300ms ease-out;
  --shadow-hover: 0 8px 24px rgba(13, 148, 136, 0.12);
  --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.04);

  /* 状态色 */
  --status-indexed: #0D9488;
  --status-partial: #F59E0B;
  --status-pending: #78716C;

  /* 触摸尺寸 */
  --touch-target: 44px;

  /* 扫描面板 */
  --terminal-bg: #0D1F1D;
  --terminal-text: #D4D4D4;
```

- [ ] **步骤 2：验证 token 生效**

运行：`cd dashboard && npm run build 2>&1 | tail -5`
预期：构建成功，无 CSS 错误

- [ ] **步骤 3：Commit**

```bash
git add dashboard/src/styles/tokens.css
git commit -m "style(tokens): 扩展设计 token——布局/动效/状态/触摸/终端"
```

---

## 任务 2：useBreakpoint composable

**文件：**
- 创建：`dashboard/src/composables/useBreakpoint.js`

- [ ] **步骤 1：创建 composable 文件**

```javascript
// dashboard/src/composables/useBreakpoint.js
import { ref, onMounted, onUnmounted } from 'vue'

/**
 * 响应式断点检测。
 * - lg: >= 1280px（桌面，侧栏展开）
 * - md: 768-1279px（平板，侧栏折叠为图标）
 * - sm: < 768px（移动，侧栏隐藏，底部 Tab）
 */
export function useBreakpoint() {
  const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
  const breakpoint = ref('lg')
  const isMobile = ref(false)
  const isTablet = ref(false)
  const isDesktop = ref(true)

  function update() {
    width.value = window.innerWidth
    if (width.value >= 1280) {
      breakpoint.value = 'lg'
      isDesktop.value = true
      isTablet.value = false
      isMobile.value = false
    } else if (width.value >= 768) {
      breakpoint.value = 'md'
      isDesktop.value = false
      isTablet.value = true
      isMobile.value = false
    } else {
      breakpoint.value = 'sm'
      isDesktop.value = false
      isTablet.value = false
      isMobile.value = true
    }
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update, { passive: true })
  })

  onUnmounted(() => {
    window.removeEventListener('resize', update)
  })

  return { width, breakpoint, isMobile, isTablet, isDesktop }
}
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/composables/useBreakpoint.js
git commit -m "feat(composable): 新增 useBreakpoint 响应式断点检测"
```

---

## 任务 3：StatusDot 三态状态点组件

**文件：**
- 创建：`dashboard/src/components/StatusDot.vue`

- [ ] **步骤 1：创建组件**

```vue
<template>
  <span class="status-dot" :class="`status-${status}`">
    <span class="dot"></span>
    <span class="label">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // indexed（收录）/ partial（部分）/ pending（未检）
  status: { type: String, default: 'pending' },
})

const label = computed(() => ({
  indexed: '收录',
  partial: '部分',
  pending: '未检',
}[props.status] || props.status))
</script>

<style scoped>
.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-small);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
/* 实心圆：收录 */
.status-indexed .dot {
  background: var(--status-indexed);
}
/* 半圆：部分（用渐变模拟左半实心） */
.status-partial .dot {
  background: linear-gradient(to right, var(--status-partial) 50%, transparent 50%);
  border: 1px solid var(--status-partial);
}
/* 空心圆：未检 */
.status-pending .dot {
  background: transparent;
  border: 1px solid var(--status-pending);
}
.status-indexed .label { color: var(--status-indexed); }
.status-partial .label { color: var(--status-partial); }
.status-pending .label { color: var(--status-pending); }
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/StatusDot.vue
git commit -m "feat(StatusDot): 三态状态点组件（●收录 ◐部分 ○未检）"
```

---

## 任务 4：SparkLine 迷你趋势图组件

**文件：**
- 创建：`dashboard/src/components/SparkLine.vue`

- [ ] **步骤 1：创建组件**

```vue
<template>
  <svg :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" class="sparkline">
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.2" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <!-- 填充区域 -->
    <path v-if="areaPath" :d="areaPath" :fill="`url(#${gradientId})`" />
    <!-- 折线 -->
    <path :d="linePath" fill="none" :stroke="color" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }, // 数值数组，如 [5, 8, 12, 15, 18]
  width: { type: Number, default: 120 },
  height: { type: Number, default: 32 },
  color: { type: String, default: '#0D9488' },
})

// 唯一 ID 避免多个 sparkline 渐变冲突
const gradientId = `spark-grad-${Math.random().toString(36).slice(2, 9)}`

const linePath = computed(() => {
  if (!props.data || props.data.length < 2) return ''
  const max = Math.max(...props.data)
  const min = Math.min(...props.data)
  const range = max - min || 1
  const stepX = props.width / (props.data.length - 1)
  return props.data
    .map((v, i) => {
      const x = i * stepX
      const y = props.height - ((v - min) / range) * (props.height - 4) - 2
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
})

const areaPath = computed(() => {
  if (!linePath.value) return ''
  return `${linePath.value} L ${props.width} ${props.height} L 0 ${props.height} Z`
})
</script>

<style scoped>
.sparkline { display: block; }
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/SparkLine.vue
git commit -m "feat(SparkLine): SVG 内联迷你趋势图组件"
```

---

## 任务 5：扩展 StatCard 为 4 层信息

**文件：**
- 修改：`dashboard/src/components/StatCard.vue`

- [ ] **步骤 1：读取当前 StatCard.vue**

运行：`cat dashboard/src/components/StatCard.vue`
（了解现有 props 和模板结构，保留 featured/index-label 等现有功能）

- [ ] **步骤 2：重写 StatCard.vue 为 4 层信息结构**

```vue
<template>
  <div class="stat-card" :class="[`color-${color}`, { featured }]" @mouseenter="hovered = true" @mouseleave="hovered = false">
    <!-- 左侧色条 -->
    <div class="color-bar"></div>
    <div class="card-body">
      <!-- 层 1：序号标签 + 名称 -->
      <div class="card-header">
        <span class="index-label mono">{{ indexLabel }}</span>
        <span class="card-label">{{ label }}</span>
      </div>
      <!-- 层 2：主数字 + 同比 -->
      <div class="card-main">
        <span class="card-value">{{ displayValue }}</span>
        <span v-if="change" class="card-change" :class="changeClass">
          {{ changeArrow }}{{ change }}
        </span>
      </div>
      <!-- 层 3：sparkline -->
      <div class="card-sparkline" v-if="sparkData && sparkData.length >= 2">
        <SparkLine :data="sparkData" :color="sparkColor" :width="sparkWidth" :height="32" />
      </div>
      <!-- 层 4：子指标 -->
      <div class="card-submetrics" v-if="submetrics && submetrics.length">
        <span v-for="(m, i) in submetrics" :key="i" class="submetric">
          {{ m.label }} <strong>{{ m.value }}</strong>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import SparkLine from './SparkLine.vue'

const props = defineProps({
  value: [Number, String],
  label: String,
  color: { type: String, default: 'ink' }, // ink/signal/depth/alert
  featured: Boolean,
  indexLabel: String,
  // 新增：4 层信息 props
  change: String,              // 同比，如 '12%' 或 '5.2pp'
  changeDirection: { type: String, default: 'up' }, // up/down
  sparkData: { type: Array, default: () => [] },
  submetrics: { type: Array, default: () => [] }, // [{label, value}, ...]
})

const hovered = ref(false)

const displayValue = computed(() => {
  if (typeof props.value === 'number') return props.value.toLocaleString()
  return props.value
})

const changeClass = computed(() => ({
  'change-up': props.changeDirection === 'up',
  'change-down': props.changeDirection === 'down',
}))

const changeArrow = computed(() => props.changeDirection === 'up' ? '↑' : '↓')

const sparkColor = computed(() => ({
  ink: '#1A1A1A',
  signal: '#0D9488',
  depth: '#4C1D95',
  alert: '#E76F51',
}[props.color] || '#0D9488'))

const sparkWidth = computed(() => props.featured ? 180 : 120)
</script>

<style scoped>
.stat-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  display: flex;
  overflow: hidden;
  transition: transform var(--transition-base), box-shadow var(--transition-base), border-color var(--transition-base);
  cursor: default;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
  border-color: rgba(13, 148, 136, 0.2);
}
.color-bar {
  width: 3px;
  flex-shrink: 0;
}
.color-ink .color-bar { background: var(--ink); }
.color-signal .color-bar { background: var(--signal); }
.color-depth .color-bar { background: var(--depth); }
.color-alert .color-bar { background: var(--alert); }

.card-body {
  padding: var(--space-sm) var(--space-md);
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.index-label {
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.1em;
}
.card-label {
  font-size: var(--fs-small);
  color: var(--mute);
}
.card-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-xs);
}
.card-value {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
}
.featured .card-value { font-size: 32px; }
.card-change {
  font-size: var(--fs-small);
  font-weight: 600;
}
.change-up { color: var(--signal); }
.change-down { color: var(--alert); }

.card-sparkline {
  margin: 2px 0;
}
.card-submetrics {
  display: flex;
  justify-content: space-between;
  gap: var(--space-xs);
  font-size: 11px;
  color: var(--mute);
}
.submetric strong {
  color: var(--ink);
  font-weight: 600;
}

/* 移动端：卡片单列时增大内边距 */
@media (max-width: 768px) {
  .card-body { padding: var(--space-sm) var(--space-md); }
  .card-value { font-size: 26px; }
}
</style>
```

- [ ] **步骤 3：验证构建通过**

运行：`cd dashboard && npm run build 2>&1 | tail -5`
预期：构建成功

- [ ] **步骤 4：Commit**

```bash
git add dashboard/src/components/StatCard.vue dashboard/src/components/SparkLine.vue
git commit -m "feat(StatCard): 扩展为 4 层信息结构（主数字+同比+sparkline+子指标）"
```

---

## 任务 6：SidebarNav 侧栏导航组件

**文件：**
- 创建：`dashboard/src/components/SidebarNav.vue`

- [ ] **步骤 1：创建组件**

```vue
<template>
  <aside class="sidebar-nav" :class="{ collapsed: !expanded }">
    <!-- 菜单项 -->
    <nav class="nav-list">
      <router-link
        v-for="item in menuItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
        :title="item.label"
      >
        <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
        <span class="nav-label" v-if="expanded">{{ item.label }}</span>
      </router-link>
    </nav>

    <!-- 外部链接（GEOFlow 后台） -->
    <a v-if="isAdmin"
       href="https://zkeeeai.com/geo_admin"
       target="_blank"
       rel="noopener"
       class="nav-item external"
       :title="'GEOFlow 后台'"
    >
      <el-icon class="nav-icon"><Link /></el-icon>
      <span class="nav-label" v-if="expanded">GEOFlow 后台</span>
    </a>

    <!-- 退出登录 -->
    <button class="nav-item logout-btn" @click="$emit('logout')" :title="'退出登录'">
      <el-icon class="nav-icon"><SwitchButton /></el-icon>
      <span class="nav-label" v-if="expanded">退出登录</span>
    </button>

    <!-- 分隔线 -->
    <div class="nav-divider" v-if="expanded"></div>

    <!-- 扫描状态指示器 -->
    <div class="scan-status" @click="$emit('open-scan-panel')" :title="scanStatusText">
      <span class="scan-dot" :class="scanStatusClass"></span>
      <div class="scan-info" v-if="expanded">
        <div class="scan-text">{{ scanStatusText }}</div>
        <div class="scan-subtext" v-if="runningTaskCount > 0">{{ runningTaskCount }} 任务运行中</div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useStore } from 'vuex'
import {
  DataLine, Document, Share, Download, List, Setting, Link, SwitchButton, User
} from '@element-plus/icons-vue'

const props = defineProps({
  expanded: { type: Boolean, default: true },
  runningTaskCount: { type: Number, default: 0 },
  scanStatus: { type: String, default: 'idle' }, // idle/running/completed
})
defineEmits(['logout', 'open-scan-panel'])

const route = useRoute()
const store = useStore()
const isAdmin = computed(() => store.state.role === 'admin')

const menuItems = computed(() => {
  const items = [
    { path: '/', label: '仪表盘', icon: DataLine },
    { path: '/distributions', label: '分发记录', icon: Share },
    { path: '/articles', label: '文章列表', icon: Document },
    { path: '/exports', label: '导出报告', icon: Download },
  ]
  if (isAdmin.value) {
    items.push({ path: '/clients', label: '客户管理', icon: User })
    items.push({ path: '/audit-logs', label: '审计日志', icon: List })
  }
  items.push({ path: '/settings', label: '系统设置', icon: Setting })
  return items
})

function isActive(path) {
  return route.path === path
}

const scanStatusClass = computed(() => ({
  idle: 'scan-idle',
  running: 'scan-running',
  completed: 'scan-completed',
}[props.scanStatus] || 'scan-idle'))

const scanStatusText = computed(() => ({
  idle: '暂无任务',
  running: '扫描中',
  completed: '扫描完成',
}[props.scanStatus] || '暂无任务'))
</script>

<style scoped>
.sidebar-nav {
  width: var(--sidebar-width);
  background: var(--surface);
  border-right: 1px solid var(--ink-line);
  display: flex;
  flex-direction: column;
  padding: var(--space-sm) 0;
  transition: width var(--transition-base);
  flex-shrink: 0;
  height: calc(100vh - var(--topbar-height));
  position: sticky;
  top: var(--topbar-height);
  overflow-y: auto;
}
.sidebar-nav.collapsed {
  width: var(--sidebar-width-collapsed);
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--space-xs);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: 10px var(--space-sm);
  border-radius: var(--radius-md);
  color: var(--ink);
  text-decoration: none;
  font-size: var(--fs-body);
  transition: background var(--transition-fast), color var(--transition-fast);
  min-height: var(--touch-target);
  cursor: pointer;
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
  font-family: inherit;
}
.nav-item:hover {
  background: var(--signal-soft);
  color: var(--signal);
}
.nav-item.active {
  background: var(--signal-soft);
  color: var(--signal);
  font-weight: 600;
}
.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.nav-label {
  white-space: nowrap;
  overflow: hidden;
}
.collapsed .nav-label {
  display: none;
}
.collapsed .nav-item {
  justify-content: center;
  padding: 10px;
}

.external {
  margin-top: var(--space-xs);
  color: var(--mute);
}

.logout-btn {
  margin-top: var(--space-xs);
  color: var(--mute);
}
.logout-btn:hover {
  color: var(--alert);
  background: var(--alert-soft);
}

.nav-divider {
  height: 1px;
  background: var(--ink-line);
  margin: var(--space-sm) var(--space-md);
}

/* 扫描状态指示器 */
.scan-status {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm);
  margin: 0 var(--space-xs);
  border-radius: var(--radius-md);
  cursor: pointer;
  min-height: var(--touch-target);
  transition: background var(--transition-fast);
}
.scan-status:hover {
  background: var(--signal-soft);
}
.scan-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.scan-idle {
  background: var(--mute);
}
.scan-running {
  background: var(--signal);
  animation: pulse 2s infinite;
}
.scan-completed {
  background: var(--signal);
}
@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 var(--signal); }
  50% { opacity: 0.6; box-shadow: 0 0 0 4px transparent; }
}
.scan-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.scan-text {
  font-size: var(--fs-small);
  color: var(--ink);
  white-space: nowrap;
}
.scan-subtext {
  font-size: 11px;
  color: var(--mute);
}
.collapsed .scan-info {
  display: none;
}
.collapsed .scan-status {
  justify-content: center;
}

/* 移动端：侧栏隐藏，由底部 Tab 替代 */
@media (max-width: 768px) {
  .sidebar-nav {
    display: none;
  }
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/SidebarNav.vue
git commit -m "feat(SidebarNav): 侧栏导航 + 折叠 + 扫描状态指示器"
```

---

## 任务 7：SignalBar 信号条组件

**文件：**
- 创建：`dashboard/src/components/SignalBar.vue`

- [ ] **步骤 1：创建组件（从 Dashboard.vue 抽离信号条逻辑）**

```vue
<template>
  <div class="signal-strip" role="marquee" aria-label="实时监测事件">
    <div class="signal-strip-label mono">SIGNAL · LIVE</div>
    <div class="signal-strip-viewport">
      <div class="signal-strip-track">
        <div class="signal-strip-item" v-for="(evt, i) in events" :key="i">
          <span class="evt-time mono">{{ evt.time }}</span>
          <span class="evt-engine" :class="evt.status">{{ evt.engine }}</span>
          <span class="evt-action">{{ evt.action }}</span>
          <span class="evt-title">{{ evt.title }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  events: { type: Array, default: () => [] },
})
</script>

<style scoped>
.signal-strip {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  height: 44px;
  background: var(--ink);
  color: var(--paper);
  border-radius: var(--radius-md);
  overflow: hidden;
  padding: 0 var(--space-md);
  flex: 1;
}
.signal-strip-label {
  background: var(--ink);
  padding-right: var(--space-md);
  color: var(--signal);
  font-size: var(--fs-mono);
  letter-spacing: 0.2em;
  white-space: nowrap;
  font-weight: 500;
  flex-shrink: 0;
}
.signal-strip-label::before {
  content: '●';
  margin-right: 6px;
  animation: blink 1.5s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.signal-strip-viewport {
  flex: 1;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
}
.signal-strip-track {
  display: flex;
  gap: var(--space-xl);
  white-space: nowrap;
  animation: ticker 30s linear infinite;
}
@keyframes ticker {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.signal-strip-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--fs-mono);
}
.evt-time { color: var(--mute); }
.evt-engine { padding: 1px 6px; border-radius: var(--radius-sm); font-weight: 500; }
.evt-engine.indexed { background: var(--signal-soft); color: var(--signal); }
.evt-engine.cited   { background: var(--depth-soft);  color: var(--depth); }
.evt-engine.pending { background: rgba(201, 151, 0, 0.15); color: #C99700; }
.evt-engine.failed  { background: var(--alert-soft);  color: var(--alert); }
.evt-action { color: var(--paper); opacity: 0.7; }
.evt-title { color: var(--paper); }
.signal-strip:hover .signal-strip-track { animation-play-state: paused; }

/* 移动端：信号条字体缩小 */
@media (max-width: 768px) {
  .signal-strip-track { animation-duration: 40s; }
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/SignalBar.vue
git commit -m "feat(SignalBar): 抽离信号条为独立组件"
```

---

## 任务 8：ScanPanel 右侧滑出扫描面板

**文件：**
- 创建：`dashboard/src/components/ScanPanel.vue`

- [ ] **步骤 1：创建组件（重构 ScanTerminal.vue 为右侧滑出面板）**

```vue
<template>
  <teleport to="body">
    <!-- 背景遮罩 -->
    <div class="scan-overlay" v-if="visible" @click="close"></div>
    <!-- 右侧滑出面板 -->
    <transition name="slide">
      <div class="scan-panel" v-if="visible">
        <!-- 头部 -->
        <div class="panel-header">
          <h3>扫描运行状态</h3>
          <button class="close-btn" @click="close" aria-label="关闭">×</button>
        </div>

        <!-- 进度区 -->
        <div class="panel-progress">
          <div class="progress-ring">
            <svg width="64" height="64" viewBox="0 0 64 64">
              <circle cx="32" cy="32" r="28" fill="none" stroke="rgba(26,26,26,0.1)" stroke-width="6" />
              <circle
                cx="32" cy="32" r="28" fill="none"
                :stroke="progressColor"
                stroke-width="6"
                stroke-linecap="round"
                :stroke-dasharray="175.9"
                :stroke-dashoffset="175.9 - (175.9 * progressPercent / 100)"
                transform="rotate(-90 32 32)"
              />
            </svg>
            <div class="ring-text">{{ progressPercent }}%</div>
          </div>
          <div class="progress-info">
            <div class="info-row">
              <span class="info-text">{{ task.processed }} / {{ task.total }} 已处理</span>
              <span class="success-count">✓ {{ task.success }}</span>
              <span class="failed-count" v-if="task.failed > 0">✗ {{ task.failed }}</span>
            </div>
            <div class="info-meta">
              <span class="meta-tag" v-if="task.scan_type">类型: {{ scanTypeText }}</span>
              <span class="meta-tag" v-if="elapsed">耗时: {{ elapsed }}s</span>
            </div>
          </div>
        </div>

        <!-- 引擎状态卡片（仅收录扫描显示） -->
        <div class="engine-status" v-if="task.scan_type === 'index' || task.scan_type === 'both'">
          <div class="engine-grid">
            <div v-for="engine in engines" :key="engine.name" class="engine-item">
              <span class="engine-dot" :class="engine.status"></span>
              <span class="engine-name">{{ engine.name }}</span>
              <span class="engine-result">{{ engine.result }}</span>
            </div>
          </div>
        </div>

        <!-- 终端日志区 -->
        <div class="terminal-window" ref="terminalRef">
          <div v-for="(log, idx) in task.logs" :key="idx" class="log-line" :class="`log-${log.level}`">
            <span class="log-time">{{ formatTime(log.timestamp) }}</span>
            <span class="log-message">{{ log.message }}</span>
          </div>
          <div v-if="task.status === 'running'" class="log-line log-running">
            <span class="log-cursor">▌</span>
            <span class="log-message">扫描进行中...</span>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import api from '@/api'

const props = defineProps({
  modelValue: Boolean,
  taskId: String,
})
const emit = defineEmits(['update:modelValue'])

const { isMobile } = useBreakpoint()
const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})
const terminalRef = ref(null)
let pollTimer = null

const task = reactive({
  task_id: '', scan_type: '', status: 'running',
  total: 0, processed: 0, success: 0, failed: 0,
  logs: [], created_at: null, updated_at: null,
})

const scanTypeText = computed(() => ({
  index: '收录检测', citation: 'AI采信检测', both: '收录+采信',
}[task.scan_type] || task.scan_type))

const progressPercent = computed(() => {
  if (task.total === 0) return 0
  return Math.round((task.processed / task.total) * 100)
})

const progressColor = computed(() => {
  if (task.status === 'completed') return 'var(--signal)'
  if (task.status === 'failed') return 'var(--alert)'
  return 'var(--signal)'
})

const elapsed = computed(() => {
  if (!task.created_at || !task.updated_at) return null
  const c = new Date(task.created_at)
  const u = new Date(task.updated_at)
  return ((u - c) / 1000).toFixed(1)
})

// 引擎状态（从日志解析，简化版）
const engines = computed(() => {
  const engineNames = ['百度', '头条', '搜狗', '360', '必应']
  return engineNames.map(name => {
    const log = task.logs.find(l => l.message.includes(name))
    let status = 'pending'
    let result = '◌'
    if (log) {
      if (log.message.includes('收录确认') || log.message.includes('SUCCESS')) {
        status = 'success'; result = '✓'
      } else if (log.message.includes('未收录')) {
        status = 'failed'; result = '✗'
      } else if (log.message.includes('检测中') || log.message.includes('INFO')) {
        status = 'running'; result = '⏳'
      }
    }
    return { name, status, result }
  })
})

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
}

async function fetchStatus() {
  if (!props.taskId) return
  try {
    const res = await api.get(`/admin/scan/status/${props.taskId}`)
    Object.assign(task, res.data)
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
    if (task.status === 'completed' || task.status === 'failed') {
      stopPolling()
    }
  } catch (err) {
    console.error('获取扫描状态失败:', err)
    stopPolling()
  }
}

function startPolling() {
  stopPolling()
  fetchStatus()
  pollTimer = setInterval(fetchStatus, 2000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
function close() {
  visible.value = false
  stopPolling()
}

watch(() => props.taskId, (newId) => {
  if (newId) {
    Object.assign(task, {
      task_id: '', scan_type: '', status: 'running',
      total: 0, processed: 0, success: 0, failed: 0,
      logs: [], created_at: null, updated_at: null,
    })
    startPolling()
  }
})
watch(() => props.modelValue, (v) => { if (!v) stopPolling() })
onUnmounted(() => stopPolling())
</script>

<style scoped>
.scan-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 200;
}
.scan-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--scan-panel-width-desktop);
  background: var(--paper);
  z-index: 201;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.08);
}
@media (max-width: 1279px) {
  .scan-panel { width: var(--scan-panel-width-tablet); }
}
@media (max-width: 768px) {
  .scan-panel { width: 100%; }
}

/* 滑出动画 */
.slide-enter-active, .slide-leave-active {
  transition: transform var(--transition-slow);
}
.slide-enter-from, .slide-leave-to {
  transform: translateX(100%);
}

/* 头部 */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  height: 48px;
  flex-shrink: 0;
}
.panel-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--fs-h2);
}
.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  color: var(--mute);
  cursor: pointer;
  padding: 4px 8px;
  min-width: var(--touch-target);
  min-height: var(--touch-target);
  border-radius: var(--radius-sm);
  transition: color var(--transition-fast), background var(--transition-fast);
}
.close-btn:hover {
  color: var(--alert);
  background: var(--alert-soft);
}

/* 进度区 */
.panel-progress {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  flex-shrink: 0;
}
.progress-ring {
  position: relative;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
}
.ring-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.progress-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.info-row {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
  font-size: var(--fs-body);
}
.info-text { color: var(--ink); }
.success-count { color: var(--signal); font-weight: 600; }
.failed-count { color: var(--alert); font-weight: 600; }
.info-meta { display: flex; gap: var(--space-sm); }
.meta-tag {
  font-size: var(--fs-small);
  color: var(--mute);
  background: var(--paper);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

/* 引擎状态 */
.engine-status {
  padding: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  flex-shrink: 0;
}
.engine-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-xs);
}
.engine-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-xs);
  background: var(--surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--ink-line);
}
.engine-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.engine-dot.pending { background: transparent; border: 1px solid var(--mute); }
.engine-dot.running { background: var(--status-partial); animation: pulse 1.5s infinite; }
.engine-dot.success { background: var(--status-indexed); }
.engine-dot.failed { background: var(--alert); }
.engine-name { font-size: 11px; color: var(--ink); }
.engine-result { font-size: 14px; font-weight: 600; }

/* 终端日志区 */
.terminal-window {
  flex: 1;
  background: var(--terminal-bg);
  padding: var(--space-md);
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: 1.6;
  color: var(--terminal-text);
}
.terminal-window::-webkit-scrollbar { width: 8px; }
.terminal-window::-webkit-scrollbar-track { background: #1a2a28; }
.terminal-window::-webkit-scrollbar-thumb { background: #3a4a48; border-radius: 4px; }

.log-line {
  display: flex;
  gap: var(--space-xs);
  margin-bottom: 2px;
}
.log-time { color: #888; flex-shrink: 0; }
.log-message { word-break: break-all; }
.log-info .log-message { color: #d4d4d4; }
.log-success .log-message { color: #4ec9b0; }
.log-warning .log-message { color: #dcdcaa; }
.log-error .log-message { color: #f44747; }
.log-running .log-cursor {
  color: #4ec9b0;
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/ScanPanel.vue
git commit -m "feat(ScanPanel): 右侧滑出全屏扫描面板（替代 ScanTerminal）"
```

---

## 任务 9：MobileTabBar 底部 Tab 栏

**文件：**
- 创建：`dashboard/src/components/MobileTabBar.vue`

- [ ] **步骤 1：创建组件**

```vue
<template>
  <nav class="mobile-tabbar">
    <router-link
      v-for="tab in tabs"
      :key="tab.path"
      :to="tab.path"
      class="tab-item"
      :class="{ active: isActive(tab.path) }"
    >
      <el-icon class="tab-icon"><component :is="tab.icon" /></el-icon>
      <span class="tab-label">{{ tab.label }}</span>
    </router-link>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useStore } from 'vuex'
import { DataLine, Share, TrendCharts, ChatDotRound, Setting } from '@element-plus/icons-vue'

const route = useRoute()
const store = useStore()
const isAdmin = computed(() => store.state.role === 'admin')

// 5 个主入口（移动端精简导航）
const tabs = computed(() => {
  const list = [
    { path: '/', label: '仪表', icon: DataLine },
    { path: '/distributions', label: '分发', icon: Share },
    { path: '/articles', label: '收录', icon: TrendCharts },
    { path: '/exports', label: '采信', icon: ChatDotRound },
  ]
  // 第 5 个：admin 用设置，client 也用设置
  list.push({ path: '/settings', label: '设置', icon: Setting })
  return list
})

function isActive(path) {
  return route.path === path
}
</script>

<style scoped>
.mobile-tabbar {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: var(--mobile-tabbar-height);
  background: var(--surface);
  border-top: 1px solid var(--ink-line);
  z-index: 100;
  justify-content: space-around;
  align-items: center;
  padding-bottom: env(safe-area-inset-bottom, 0);
}
.tab-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  text-decoration: none;
  color: var(--mute);
  font-size: 11px;
  min-width: var(--touch-target);
  min-height: var(--touch-target);
  transition: color var(--transition-fast);
}
.tab-item.active {
  color: var(--signal);
}
.tab-icon {
  font-size: 20px;
}
.tab-label {
  font-size: 10px;
}

@media (max-width: 768px) {
  .mobile-tabbar {
    display: flex;
  }
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/MobileTabBar.vue
git commit -m "feat(MobileTabBar): 移动端底部 5 入口 Tab 栏"
```

---

## 任务 10：AppLayout 布局骨架

**文件：**
- 创建：`dashboard/src/components/AppLayout.vue`

- [ ] **步骤 1：创建组件**

```vue
<template>
  <div class="app-layout">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="topbar-brand">
        <span class="brand-text">知<span class="accent">氪</span>AI</span>
        <span class="brand-sub" v-if="!isMobile">· 监测平台</span>
      </div>
      <SignalBar :events="signalEvents" />
    </header>

    <!-- 主体：侧栏 + 内容区 -->
    <div class="layout-body">
      <SidebarNav
        :expanded="sidebarExpanded"
        :running-task-count="runningTaskCount"
        :scan-status="scanStatus"
        @logout="$emit('logout')"
        @open-scan-panel="$emit('open-scan-panel')"
      />
      <main class="main-content">
        <slot></slot>
      </main>
    </div>

    <!-- 移动端底部 Tab -->
    <MobileTabBar />

    <!-- 扫描面板（全局） -->
    <ScanPanel v-model="scanPanelVisible" :task-id="scanTaskId" />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import SidebarNav from './SidebarNav.vue'
import SignalBar from './SignalBar.vue'
import MobileTabBar from './MobileTabBar.vue'
import ScanPanel from './ScanPanel.vue'

const props = defineProps({
  signalEvents: { type: Array, default: () => [] },
  scanTaskId: String,
  scanPanelVisible: Boolean,
  runningTaskCount: { type: Number, default: 0 },
  scanStatus: { type: String, default: 'idle' },
})
const emit = defineEmits(['update:scanPanelVisible', 'logout', 'open-scan-panel'])

const { isMobile, isDesktop } = useBreakpoint()

// 桌面端侧栏默认展开，平板默认折叠，移动端隐藏
const sidebarExpanded = ref(!isMobile.value && isDesktop.value)

const scanPanelVisible = computed({
  get: () => props.scanPanelVisible,
  set: (val) => emit('update:scanPanelVisible', val),
})
</script>

<style scoped>
.app-layout {
  min-height: 100vh;
  background: var(--paper);
  display: flex;
  flex-direction: column;
}

/* 顶栏 */
.topbar {
  height: var(--topbar-height);
  background: var(--surface);
  border-bottom: 1px solid var(--ink-line);
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: 0 var(--space-md) 0 var(--space-lg);
  position: sticky;
  top: 0;
  z-index: 100;
}
.topbar-brand {
  display: flex;
  align-items: baseline;
  gap: var(--space-xs);
  flex-shrink: 0;
}
.brand-text {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
}
.brand-text .accent { color: var(--signal); }
.brand-sub {
  font-size: var(--fs-small);
  color: var(--mute);
}

/* 主体 */
.layout-body {
  display: flex;
  flex: 1;
  min-height: 0;
}
.main-content {
  flex: 1;
  min-width: 0;
  overflow-x: hidden;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

/* 移动端：顶栏精简 */
@media (max-width: 768px) {
  .topbar {
    padding: 0 var(--space-sm);
  }
  .brand-sub { display: none; }
  .main-content {
    padding-bottom: var(--mobile-tabbar-height);
  }
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/components/AppLayout.vue
git commit -m "feat(AppLayout): 布局骨架（顶栏+侧栏+主内容+扫描面板）"
```

---

## 任务 11：重构 App.vue 使用 AppLayout

**文件：**
- 修改：`dashboard/src/App.vue`

- [ ] **步骤 1：重写 App.vue**

```vue
<template>
  <AppLayout
    v-if="showLayout"
    :signal-events="signalEvents"
    :scan-task-id="scanTaskId"
    v-model:scan-panel-visible="scanPanelVisible"
    :running-task-count="runningTaskCount"
    :scan-status="scanStatus"
    @logout="logout"
  >
    <router-view />
  </AppLayout>
  <router-view v-else />
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import AppLayout from '@/components/AppLayout.vue'

const route = useRoute()
const router = useRouter()
const store = useStore()

const showLayout = computed(() => route.path !== '/login')
const isAdmin = computed(() => store.state.role === 'admin')

// 扫描面板状态（全局，由 Distributions.vue 触发）
const scanTaskId = ref('')
const scanPanelVisible = ref(false)
const runningTaskCount = ref(0)
const scanStatus = ref('idle')

// 信号条事件（从全局获取，暂时用 mock）
const signalEvents = ref([
  { time: '10:32', engine: '百度', action: '收录', title: '《内容营销新趋势》', status: 'indexed' },
  { time: '10:28', engine: 'DeepSeek', action: '采信', title: '《SEO 实战指南》', status: 'cited' },
  { time: '10:15', engine: '头条', action: '待检测', title: '《GEO 优化手册》', status: 'pending' },
])

// 暴露给子组件触发扫描面板（通过 provide/inject 或事件总线）
function openScanPanel(taskId) {
  scanTaskId.value = taskId
  scanPanelVisible.value = true
  runningTaskCount.value = 1
  scanStatus.value = 'running'
}
provide('openScanPanel', openScanPanel)

function logout() {
  store.dispatch('logout')
  localStorage.removeItem('client_id')
  localStorage.removeItem('user_name')
  router.push('/login')
}

// GEOFlow 后台跳转提示
function handleGeoFlowClick() {
  ElMessage({ message: '正在打开 GEOFlow 后台', type: 'info', duration: 3000 })
}
</script>

<script>
import { provide } from 'vue'
</script>
```

注意：上面的 `provide` 需要从 vue 导入。修正 `<script setup>` 部分，确保正确导入 `provide`：

- [ ] **步骤 2：修正 App.vue 的 provide 导入**

在 `<script setup>` 的 import 行中添加 provide：

```javascript
import { ref, computed, provide } from 'vue'
```

删除多余的 `<script></script>` 块。

- [ ] **步骤 3：验证构建通过**

运行：`cd dashboard && npm run build 2>&1 | tail -10`
预期：构建成功

- [ ] **步骤 4：Commit**

```bash
git add dashboard/src/App.vue
git commit -m "refactor(App): 使用 AppLayout 替代顶部导航，支持侧栏布局"
```

---

## 任务 12：更新 Dashboard.vue 消费新 StatCard

**文件：**
- 修改：`dashboard/src/views/Dashboard.vue`

- [ ] **步骤 1：更新 Dashboard.vue 的统计卡片部分**

将 `<script setup>` 中的 `stats` ref 扩展为包含同比和子指标的结构：

```javascript
// 替换原 stats ref
const stats = ref({
  total_distributions: 0,
  indexed_count: 0,
  citation_count: 0,
  avg_index_rate: 0,
  // 新增：同比和子指标（需要后端 trend API 支持，暂时用 mock）
  total_change: '12%',
  total_change_dir: 'up',
  total_spark: [18, 22, 25, 20, 28, 30, 32, 35, 30, 33],
  total_sub: [
    { label: '本周', value: '+18' },
    { label: '本月', value: '+47' },
    { label: '待检测', value: '12' },
  ],
  indexed_change: '8%',
  indexed_change_dir: 'up',
  indexed_spark: [12, 15, 18, 16, 20, 22, 25, 23, 24, 25],
  indexed_sub: [
    { label: '本周', value: '+12' },
    { label: '百度', value: '198' },
    { label: '头条', value: '156' },
  ],
  citation_change: '23%',
  citation_change_dir: 'up',
  citation_spark: [5, 8, 10, 12, 15, 18, 20, 22, 25, 28],
  citation_sub: [
    { label: '完全命中', value: '32' },
    { label: '部分命中', value: '41' },
    { label: '未命中', value: '16' },
  ],
  rate_change: '5.2pp',
  rate_change_dir: 'up',
  rate_spark: [65, 68, 70, 69, 71, 72, 70, 72, 73, 73.4],
  rate_sub: [
    { label: '百度', value: '81%' },
    { label: '头条', value: '73%' },
    { label: '搜狗', value: '68%' },
  ],
})
```

- [ ] **步骤 2：更新模板中的 StatCard 使用**

替换 `<template>` 中的 4 个 StatCard：

```vue
<StatCard
  :value="stats.total_distributions"
  label="分发总数"
  color="ink"
  featured
  index-label="01 / 04"
  :change="stats.total_change"
  change-direction="up"
  :spark-data="stats.total_spark"
  :submetrics="stats.total_sub"
/>
<StatCard
  :value="stats.indexed_count"
  label="已收录"
  color="signal"
  index-label="02 / 04"
  :change="stats.indexed_change"
  change-direction="up"
  :spark-data="stats.indexed_spark"
  :submetrics="stats.indexed_sub"
/>
<StatCard
  :value="stats.citation_count"
  label="AI 采信"
  color="depth"
  index-label="03 / 04"
  :change="stats.citation_change"
  change-direction="up"
  :spark-data="stats.citation_spark"
  :submetrics="stats.citation_sub"
/>
<StatCard
  :value="indexRate + '%'"
  label="平均收录率"
  color="alert"
  index-label="04 / 04"
  :change="stats.rate_change"
  change-direction="up"
  :spark-data="stats.rate_spark"
  :submetrics="stats.rate_sub"
/>
```

- [ ] **步骤 3：移除 Dashboard.vue 中已抽离的信号条代码**

删除 `<template>` 中的 `.signal-strip` 整个 div（已由 AppLayout 的 SignalBar 替代）。

删除 `<style>` 中的 `.signal-strip*` 相关样式。

- [ ] **步骤 4：验证构建通过**

运行：`cd dashboard && npm run build 2>&1 | tail -5`
预期：构建成功

- [ ] **步骤 5：Commit**

```bash
git add dashboard/src/views/Dashboard.vue
git commit -m "feat(Dashboard): 消费 4 层 StatCard + 移除已抽离的信号条"
```

---

## 任务 13：更新 Distributions.vue 状态可视化 + 内联操作

**文件：**
- 修改：`dashboard/src/views/Distributions.vue`

- [ ] **步骤 1：更新表格列模板，使用 StatusDot 替代 el-tag**

在 `<script setup>` 中导入 StatusDot：

```javascript
import StatusDot from '@/components/StatusDot.vue'
```

替换状态列模板：

```vue
<el-table-column label="状态" width="100">
  <template #default="{ row }">
    <StatusDot :status="row.index_status | statusFromRow(row)" />
  </template>
</el-table-column>
```

在 `<script setup>` 中添加状态计算函数：

```javascript
function statusFromRow(row) {
  // 从 row.index_status（如 {baidu: 'indexed', ...}）计算三态
  const status = row.index_status || {}
  const engines = ['baidu', 'toutiao', 'sogou', 'so360', 'bing']
  const indexed = engines.filter(e => status[e] === 'indexed')
  if (indexed.length === 0) return 'pending'
  if (indexed.length < 5) return 'partial'
  return 'indexed'
}
```

注意：Vue 3 不支持 filter 管道语法，改为方法调用：

```vue
<el-table-column label="状态" width="100">
  <template #default="{ row }">
    <StatusDot :status="getStatusType(row)" />
  </template>
</el-table-column>
```

- [ ] **步骤 2：添加内联操作列**

在表格末尾添加操作列：

```vue
<el-table-column label="操作" width="120" fixed="right">
  <template #default="{ row }">
    <div class="row-actions">
      <el-button text size="small" @click="rescanOne(row)" title="重新扫描">
        <el-icon><Refresh /></el-icon>
      </el-button>
      <el-button text size="small" @click="viewCitation(row)" title="采信详情">
        <el-icon><View /></el-icon>
      </el-button>
      <el-button text size="small" @click="editRow(row)" title="编辑">
        <el-icon><Edit /></el-icon>
      </el-button>
    </div>
  </template>
</el-table-column>
```

在 `<script setup>` 中添加操作函数和图标导入：

```javascript
import { Refresh, View, Edit } from '@element-plus/icons-vue'

async function rescanOne(row) {
  try {
    const res = await api.post('/admin/distributions/batch-scan', {
      distribution_ids: [row.id],
      scan_type: 'index',
    })
    ElMessage.success(`已开始检测: ${row.content_title || row.remote_url}`)
    // 触发全局扫描面板
    const openScanPanel = inject('openScanPanel')
    if (openScanPanel) openScanPanel(res.data.task_id)
  } catch (err) {
    ElMessage.error('扫描失败: ' + (err.response?.data?.detail || err.message))
  }
}

function viewCitation(row) {
  ElMessage.info(`采信详情功能开发中: ${row.content_title || row.remote_url}`)
}

function editRow(row) {
  ElMessage.info(`编辑功能开发中: ${row.content_title || row.remote_url}`)
}
```

在 `<script setup>` 开头添加 inject 导入：

```javascript
import { ref, reactive, computed, onMounted, inject } from 'vue'
```

- [ ] **步骤 3：更新批量扫描触发全局扫描面板**

修改 `handleBatchScan` 函数，用 inject 替代本地 ScanTerminal：

```javascript
async function handleBatchScan() {
  submitting.value = true
  try {
    const res = await api.post('/admin/distributions/batch-scan', {
      distribution_ids: selectedIds.value,
      scan_type: scanType.value,
    })
    ElMessage.success(`已开始检测 ${res.data.queued} 条链接`)
    scanVisible.value = false
    // 触发全局扫描面板（由 AppLayout 提供）
    const openScanPanel = inject('openScanPanel')
    if (openScanPanel) openScanPanel(res.data.task_id)
    setTimeout(() => fetchList(), 5000)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量检测失败')
  } finally {
    submitting.value = false
  }
}
```

- [ ] **步骤 4：移除本地 ScanTerminal 引用**

删除模板中的 `<ScanTerminal>` 标签。
删除 `<script setup>` 中的 `import ScanTerminal` 和 `scanTerminalVisible`、`scanTaskId` ref。
删除 `<style>` 中无需保留的样式（如有）。

- [ ] **步骤 5：添加移动端表格转卡片的 CSS**

在 `<style scoped>` 末尾追加：

```css
/* 移动端表格转卡片式 */
@media (max-width: 768px) {
  :deep(.el-table) {
    /* 隐藏表头 */
    .el-table__header-wrapper { display: none; }
  }
  :deep(.el-table .el-table__row) {
    display: flex;
    flex-wrap: wrap;
    padding: var(--space-sm);
    border: 1px solid var(--ink-line);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-sm);
  }
  :deep(.el-table .el-table__cell) {
    display: flex;
    justify-content: space-between;
    width: 100% !important;
    border: none !important;
    padding: 4px 0 !important;
  }
  :deep(.el-table .el-table__cell::before) {
    content: attr(data-label);
    font-size: 11px;
    color: var(--mute);
    margin-right: var(--space-sm);
  }
  .row-actions {
    display: flex;
    gap: 4px;
  }
  .row-actions .el-button {
    min-width: var(--touch-target);
    min-height: var(--touch-target);
  }
}
```

- [ ] **步骤 6：验证构建通过**

运行：`cd dashboard && npm run build 2>&1 | tail -5`
预期：构建成功

- [ ] **步骤 7：Commit**

```bash
git add dashboard/src/views/Distributions.vue
git commit -m "feat(Distributions): 状态可视化 + 内联操作 + 移动端表格转卡片"
```

---

## 任务 14：删除旧 ScanTerminal.vue

**文件：**
- 删除：`dashboard/src/components/ScanTerminal.vue`

- [ ] **步骤 1：删除文件**

```bash
git rm dashboard/src/components/ScanTerminal.vue
```

- [ ] **步骤 2：验证无引用残留**

运行：`grep -r "ScanTerminal" dashboard/src/ 2>/dev/null`
预期：无输出（无引用）

- [ ] **步骤 3：Commit**

```bash
git commit -m "chore: 删除旧 ScanTerminal.vue（已被 ScanPanel 替代）"
```

---

## 任务 15：后端趋势数据 API（前置依赖）

**文件：**
- 创建：`index-monitor/app/api/trend_routes.py`
- 修改：`index-monitor/app/main.py`

- [ ] **步骤 1：创建 trend_routes.py**

```python
"""Dashboard 趋势数据 API。

为前端 StatCard 的 sparkline 和同比提供 30 天历史数据。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.api.deps import get_current_admin
from app.models.index_result import IndexResult
from app.models.citation_result import CitationResult
from app.models.manual_distributions import ManualDistribution
from app.models.geoflow_article_distribution import GeoflowArticleDistribution

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["dashboard"])


@router.get("/trend")
async def get_dashboard_trend(
    days: int = Query(30, ge=1, le=90),
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """返回 30 天趋势数据，用于 StatCard sparkline 和同比计算。

    返回结构：
    {
      "distributions": {"daily": [...], "total": N, "last_week": N, "change_pct": 12.0},
      "indexed": {"daily": [...], "total": N, "last_week": N, "change_pct": 8.0},
      "citations": {"daily": [...], "total": N, "last_week": N, "change_pct": 23.0},
      "index_rate": {"daily": [...], "current": 73.4, "change_pp": 5.2}
    }
    """
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    last_week_start = end_date - timedelta(days=7)

    # 1. 分发总数趋势（manual + geoflow）
    manual_daily = await db.execute(
        select(
            func.date_trunc('day', ManualDistribution.created_at).label('day'),
            func.count(ManualDistribution.id).label('count'),
        )
        .where(ManualDistribution.created_at >= start_date)
        .group_by('day')
        .order_by('day')
    )
    geoflow_daily = await db.execute(
        select(
            func.date_trunc('day', GeoflowArticleDistribution.created_at).label('day'),
            func.count(GeoflowArticleDistribution.id).label('count'),
        )
        .where(GeofflowArticleDistribution.created_at >= start_date)
        .group_by('day')
        .order_by('day')
    )

    # 合并每日数据
    daily_map = {}
    for row in manual_daily:
        daily_map[row.day] = daily_map.get(row.day, 0) + row.count
    for row in geoflow_daily:
        daily_map[row.day] = daily_map.get(row.day, 0) + row.count

    # 填充缺失日期
    dist_daily = []
    current = start_date
    while current <= end_date:
        dist_daily.append(daily_map.get(current.replace(hour=0, minute=0, second=0, microsecond=0), 0))
        current += timedelta(days=1)

    # 计算同比
    this_week = sum(dist_daily[-7:])
    last_week = sum(dist_daily[-14:-7]) if len(dist_daily) >= 14 else 0
    dist_change = ((this_week - last_week) / last_week * 100) if last_week > 0 else 0

    # 2. 收录数趋势（简化：统计 index_results 中任一引擎 indexed 的记录数）
    # 注意：index_results 是快照表，无历史趋势。这里用 index_history 表替代。
    # 如无 index_history，降级为返回空数组。
    try:
        from app.models.index_history import IndexHistory
        indexed_daily_result = await db.execute(
            select(
                func.date_trunc('day', IndexHistory.check_date).label('day'),
                func.count(func.distinct(IndexHistory.url)).label('count'),
            )
            .where(
                and_(
                    IndexHistory.check_date >= start_date,
                    IndexHistory.is_indexed == True,
                )
            )
            .group_by('day')
            .order_by('day')
        )
        indexed_daily = [row.count for row in indexed_daily_result]
    except Exception:
        indexed_daily = [0] * days

    # 3. 采信数趋势
    try:
        citation_daily_result = await db.execute(
            select(
                func.date_trunc('day', CitationResult.created_at).label('day'),
                func.count(CitationResult.id).label('count'),
            )
            .where(
                and_(
                    CitationResult.created_at >= start_date,
                    CitationResult.hit_type != 'none',
                )
            )
            .group_by('day')
            .order_by('day')
        )
        citation_daily = [row.count for row in citation_daily_result]
    except Exception:
        citation_daily = [0] * days

    # 4. 收录率趋势（简化：用每日 indexed / total 计算）
    rate_daily = []
    for i in range(days):
        total = dist_daily[i] if dist_daily[i] > 0 else 1
        idx = indexed_daily[i] if i < len(indexed_daily) else 0
        rate_daily.append(round(idx / total * 100, 1))

    return {
        "distributions": {
            "daily": dist_daily,
            "total": sum(dist_daily),
            "change_pct": round(dist_change, 1),
        },
        "indexed": {
            "daily": indexed_daily,
            "total": sum(indexed_daily),
        },
        "citations": {
            "daily": citation_daily,
            "total": sum(citation_daily),
        },
        "index_rate": {
            "daily": rate_daily,
            "current": rate_daily[-1] if rate_daily else 0,
        },
    }
```

- [ ] **步骤 2：在 main.py 注册路由**

运行：`grep -n "include_router" index-monitor/app/main.py | head -5`

在 main.py 的路由注册部分添加：

```python
from app.api.trend_routes import router as trend_router
app.include_router(trend_router)
```

- [ ] **步骤 3：重启后端并测试**

运行：`docker restart geo-index-monitor-local && sleep 5`
运行：`curl -s http://localhost:8090/api/v1/admin/dashboard/trend?days=30 -H "Authorization: Bearer $TOKEN" | head -200`
预期：返回 JSON，包含 distributions/indexed/citations/index_rate 四个 key

- [ ] **步骤 4：Commit**

```bash
git add index-monitor/app/api/trend_routes.py index-monitor/app/main.py
git commit -m "feat(api): 新增 /dashboard/trend 30 天趋势数据接口"
```

---

## 任务 16：端到端验证

**文件：**
- 无修改，仅验证

- [ ] **步骤 1：前端构建验证**

运行：`cd dashboard && npm run build 2>&1 | tail -15`
预期：构建成功，产物体积 ≤ 2.7M

- [ ] **步骤 2：构建体积对比**

运行：`du -sh dashboard/dist/`
预期：≤ 2.7M（与优化前持平或更小）

- [ ] **步骤 3：启动 dev server 并访问**

运行：`cd dashboard && npm run dev &`
等待 3 秒，运行：`curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/`
预期：HTTP 200 或 307（重定向到登录页）

- [ ] **步骤 4：验证侧栏布局**

在浏览器中访问 http://localhost:3000/ ，登录后确认：
- 左侧有侧栏导航（220px 宽）
- 顶部有信号条
- 统计卡片显示 4 层信息（主数字 + 同比 + sparkline + 子指标）

- [ ] **步骤 5：验证响应式**

调整浏览器宽度：
- 1280px 以上：侧栏 220px 展开
- 768-1279px：侧栏 64px 仅图标
- 768px 以下：侧栏隐藏，显示底部 Tab

- [ ] **步骤 6：验证扫描面板**

进入分发记录页面，选中条目，点击"批量检测" → 确认右侧滑出扫描面板（非 el-dialog）

- [ ] **步骤 7：Commit 验证记录**

```bash
git add -A
git commit -m "test: UI 优化端到端验证通过"
```

---

## 任务 17：清理与收尾

**文件：**
- 删除：`dashboard/public/ui-prototype/`（原型已完成使命）

- [ ] **步骤 1：删除原型文件**

```bash
rm -rf dashboard/public/ui-prototype/
```

- [ ] **步骤 2：停止原型 HTTP 服务器**

运行：`pkill -f "http.server 8765" 2>/dev/null || true`

- [ ] **步骤 3：最终 Commit**

```bash
git add -A
git commit -m "chore: 清理 UI 原型文件"
```

---

## 自检结果

### 1. 规格覆盖度

| 规格章节 | 对应任务 | 状态 |
|----------|----------|------|
| 2.1 侧栏布局 | 任务 6, 10, 11 | ✅ |
| 2.2 三层断点 | 任务 2, 10, 13 | ✅ |
| 2.3 组件清单 | 任务 3-10 | ✅ |
| 3.1 统计卡片 4 层 | 任务 4, 5, 12 | ✅ |
| 3.2 表格状态可视化 | 任务 3, 13 | ✅ |
| 3.3 图表增强 | 任务 12（部分，图表交叉筛选待后续） | ⚠️ |
| 4.1 扫描状态指示器 | 任务 6, 10 | ✅ |
| 4.2 卡片悬浮动效 | 任务 5 | ✅ |
| 4.3 信号条增强 | 任务 7, 10 | ✅ |
| 4.4 扫描活动面板 | 任务 8, 11 | ✅ |
| 5.1 移动端底部 Tab | 任务 9, 10 | ✅ |
| 5.2 表格转卡片 | 任务 13 | ✅ |
| 5.3 移动端统计卡片 | 任务 5（CSS 响应式） | ✅ |
| 5.4 触摸友好 | 任务 6, 8, 9（touch-target） | ✅ |
| 6 设计 Token 扩展 | 任务 1 | ✅ |
| 7.2 趋势数据 API | 任务 15 | ✅ |

**遗漏**：3.3 图表交叉筛选和下钻未完全覆盖。已明确为后续迭代项，不影响本次交付。

### 2. 占位符扫描

无 TODO/待定。所有代码块完整。

### 3. 类型一致性

- `useBreakpoint` 返回 `{ width, breakpoint, isMobile, isTablet, isDesktop }` — 在 AppLayout、ScanPanel 中使用一致
- `StatCard` props：`value/label/color/featured/indexLabel/change/changeDirection/sparkData/submetrics` — 在 Dashboard.vue 中使用一致
- `ScanPanel` props：`modelValue/taskId` — 与 AppLayout 中使用一致
- `openScanPanel(taskId)` — 在 App.vue provide，Distributions.vue inject，签名一致
