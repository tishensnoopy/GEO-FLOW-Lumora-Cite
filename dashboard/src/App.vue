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
import { ref, computed, provide } from 'vue'
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
