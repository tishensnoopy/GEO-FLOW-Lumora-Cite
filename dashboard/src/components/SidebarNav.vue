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
