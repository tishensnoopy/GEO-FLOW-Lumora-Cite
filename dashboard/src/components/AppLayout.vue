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

    <!-- 扫描面板（全局）。I2：透传 scanTaskIds 以驱动 all 类型三阶段进度环 -->
    <ScanPanel v-model="scanPanelVisible" :task-id="scanTaskId" :task-ids="scanTaskIds" />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
import SidebarNav from './SidebarNav.vue'
import SignalBar from './SignalBar.vue'
import MobileTabBar from './MobileTabBar.vue'
import ScanPanel from './ScanPanel.vue'

const props = defineProps({
  signalEvents: { type: Array, default: () => [] },
  scanTaskId: String,
  scanTaskIds: { type: Object, default: null }, // I2: all 类型 {index, ai_index, citation} | null
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
  background: var(--grad-bg);
  display: flex;
  flex-direction: column;
}

/* 顶栏：玻璃态（半透明白 + 模糊 + 渐变细边） */
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
  /* 品牌区宽度对齐侧栏宽度，使走马灯条从侧栏右边缘开始，
     不再入侵左侧菜单区。宽度与 SidebarNav 的 --sidebar-width 一致。 */
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
/* "氪"字用品牌渐变，呼应主视觉 */
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
.main-content {
  flex: 1;
  min-width: 0;
  overflow-x: hidden;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

/* 移动端：顶栏精简，侧栏隐藏，品牌区不再固定宽度 */
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
  .main-content {
    padding-bottom: var(--mobile-tabbar-height);
  }
}
</style>
