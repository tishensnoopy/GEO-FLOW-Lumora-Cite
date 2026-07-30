<template>
  <div class="client-layout">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="topbar-brand">
        <span class="brand-text">知<span class="accent">氪</span>AI</span>
        <span class="brand-sub" v-if="!isMobile">· 客户端</span>
      </div>
    </header>

    <!-- 主体：侧栏 + 内容区 -->
    <div class="layout-body">
      <aside class="client-sidebar">
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
            <span class="nav-label">{{ item.label }}</span>
          </router-link>
        </nav>

        <!-- 退出登录 -->
        <button class="nav-item logout-btn" @click="logout" title="退出登录">
          <el-icon class="nav-icon"><SwitchButton /></el-icon>
          <span class="nav-label">退出登录</span>
        </button>
      </aside>

      <main class="main-content">
        <slot></slot>
      </main>
    </div>

    <!-- 移动端底部 Tab -->
    <nav class="client-tabbar">
      <router-link
        v-for="tab in menuItems"
        :key="tab.path"
        :to="tab.path"
        class="tab-item"
        :class="{ active: isActive(tab.path) }"
      >
        <el-icon class="tab-icon"><component :is="tab.icon" /></el-icon>
        <span class="tab-label">{{ tab.label }}</span>
      </router-link>
    </nav>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { DataLine, Document, ChatDotRound, Setting, SwitchButton } from '@element-plus/icons-vue'
import { useBreakpoint } from '@/composables/useBreakpoint'

const route = useRoute()
const router = useRouter()
const store = useStore()
const { isMobile } = useBreakpoint()

// 客户端菜单：仅概览 / 引用证据 / 我的文章 / 设置（不含任何管理员入口）
const menuItems = computed(() => [
  { path: '/client/overview', label: '概览', icon: DataLine },
  { path: '/client/evidence', label: '引用证据', icon: ChatDotRound },
  { path: '/client/articles', label: '我的文章', icon: Document },
  { path: '/client/settings', label: '设置', icon: Setting },
])

function isActive(path) {
  return route.path === path
}

function logout() {
  store.dispatch('logout')
  localStorage.removeItem('client_id')
  localStorage.removeItem('user_name')
  router.push('/login')
}
</script>

<style scoped>
.client-layout {
  min-height: 100vh;
  background: var(--grad-bg);
  display: flex;
  flex-direction: column;
}

/* 顶栏：玻璃态 */
.topbar {
  height: var(--topbar-height);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: saturate(180%) blur(14px);
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  border-bottom: 1px solid var(--ink-line);
  box-shadow: 0 1px 0 rgba(99, 102, 241, 0.04);
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
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  flex-shrink: 0;
  border-right: 1px solid var(--ink-line);
  padding-right: var(--space-md);
  box-sizing: border-box;
}
.brand-text {
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 800;
  color: var(--ink);
  white-space: nowrap;
  letter-spacing: -0.02em;
}
.brand-text .accent {
  background: var(--grad-brand-2);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-sub {
  font-size: var(--fs-small);
  color: var(--mute);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

/* 主体 */
.layout-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* 侧栏 */
.client-sidebar {
  width: var(--sidebar-width);
  background: var(--surface);
  border-right: 1px solid var(--ink-line);
  display: flex;
  flex-direction: column;
  padding: var(--space-sm) 0;
  flex-shrink: 0;
  height: calc(100vh - var(--topbar-height));
  position: sticky;
  top: var(--topbar-height);
  overflow-y: auto;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--space-xs);
  flex: 1;
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

.logout-btn {
  margin: var(--space-xs) var(--space-xs);
  color: var(--mute);
}
.logout-btn:hover {
  color: var(--alert);
  background: var(--alert-soft);
}

.main-content {
  flex: 1;
  min-width: 0;
  overflow-x: hidden;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

/* 移动端 Tab */
.client-tabbar {
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

/* 移动端：顶栏精简，侧栏隐藏 */
@media (max-width: 768px) {
  .topbar {
    padding: 0 var(--space-sm);
  }
  .topbar-brand {
    width: auto;
    min-width: 0;
    border-right: none;
    padding-right: 0;
  }
  .brand-sub { display: none; }
  .client-sidebar { display: none; }
  .client-tabbar { display: flex; }
  .main-content {
    padding-bottom: var(--mobile-tabbar-height);
  }
}
</style>
