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
