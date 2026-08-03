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
import { DataLine, Share, TrendCharts, ChatDotRound, Memo, Setting, Document } from '@element-plus/icons-vue'

const route = useRoute()
const store = useStore()
const role = computed(() => store.state.role)

// 按角色渲染不同 tab：
// - admin：仪表/分发/收录/采信/设置（5 个，对应 AppLayout 管理后台）
// - client：概览/证据/快照/文章/设置（5 个，对应 ClientLayout 客户端视图）
// 注：MobileTabBar 仅在 AppLayout 中使用；ClientLayout 有自己的内嵌 tabbar。
//     此处按 role 分流是双保险，避免 client 误入 AppLayout 时看到管理员入口。
const tabs = computed(() => {
  if (role.value === 'client') {
    return [
      { path: '/client/overview', label: '概览', icon: DataLine },
      { path: '/client/evidence', label: '证据', icon: ChatDotRound },
      { path: '/client/rankings', label: '快照', icon: Memo },
      { path: '/client/articles', label: '文章', icon: Document },
      { path: '/client/settings', label: '设置', icon: Setting },
    ]
  }
  return [
    { path: '/', label: '仪表', icon: DataLine },
    { path: '/distributions', label: '分发', icon: Share },
    { path: '/articles', label: '收录', icon: TrendCharts },
    { path: '/exports', label: '采信', icon: ChatDotRound },
    { path: '/settings', label: '设置', icon: Setting },
  ]
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
