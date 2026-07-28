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
