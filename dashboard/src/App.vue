<template>
  <AppLayout
    v-if="showLayout && !isClientRoute"
    :signal-events="signalEvents"
    :scan-task-id="scanTaskId"
    v-model:scan-panel-visible="scanPanelVisible"
    :running-task-count="runningTaskCount"
    :scan-status="scanStatus"
    @logout="logout"
  >
    <router-view />
  </AppLayout>
  <ClientLayout v-else-if="showLayout && isClientRoute" @logout="logout">
    <router-view />
  </ClientLayout>
  <router-view v-else />
</template>

<script setup>
import { ref, computed, provide, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import AppLayout from '@/components/AppLayout.vue'
import ClientLayout from '@/components/ClientLayout.vue'
import { api } from '@/api'

const route = useRoute()
const router = useRouter()
const store = useStore()

const showLayout = computed(() => route.path !== '/login')
const isAdmin = computed(() => store.state.role === 'admin')
// 客户端路由分流：role === 'client' 且路径 /client/* → ClientLayout
// - guard.js 已确保 admin 不会停留在 /client/*（重定向到 /）
// - guard.js 已确保 client 不会停留在 admin 路由（重定向到 /client/overview）
// - 此处同时检查 role + path 作为双保险：即便角色与路径不一致，也不会错误套用 Layout
// 注：startsWith('/client/') 带尾斜杠，避免误匹配 /clients（admin 路由）
const isClientRoute = computed(() =>
  route.path.startsWith('/client/') && store.state.role === 'client'
)

// 扫描面板状态（全局，由 Distributions.vue 触发）
const scanTaskId = ref('')
const scanPanelVisible = ref(false)
const runningTaskCount = ref(0)
const scanStatus = ref('idle')

// 信号条事件：从后端拉取最近的分发记录动态生成，不再写死。
// 拉取失败时回退为空数组（走马灯条不显示事件项），避免误导用户。
const signalEvents = ref([])

// 引擎中文映射 + 状态映射，用于把分发记录转成走马灯事件
const ENGINE_LABELS = { baidu: '百度', toutiao: '头条', sogou: '搜狗', so360: '360', bing: '必应' }

async function fetchSignalEvents() {
  // 未登录（如登录页）不拉取
  if (!localStorage.getItem('token')) return
  try {
    const endpoint = isAdmin.value ? '/admin/distributions' : '/distributions'
    const resp = await api.get(endpoint, { params: { page: 1, page_size: 10 } })
    const items = resp.data.items || []
    signalEvents.value = items.slice(0, 8).map(item => {
      // 从 index_status 聚合出主要引擎与状态
      const idx = item.index_status || {}
      const engines = Object.keys(idx)
      // 优先取已收录的引擎，否则取第一个
      const indexedEngine = engines.find(e => idx[e] === 'indexed')
      const engineKey = indexedEngine || engines[0] || 'baidu'
      const st = idx[engineKey]
      let action = '待检测', status = 'pending'
      if (st === 'indexed') { action = '收录'; status = 'indexed' }
      else if (st === 'not_indexed' || st === 'failed') { action = '未收录'; status = 'failed' }
      else if (st === 'checking') { action = '检测中'; status = 'pending' }
      // 若有采信记录，额外标注
      if (item.citation_status === 'cited') { action = '采信'; status = 'cited' }
      const timeStr = item.updated_at || item.created_at || ''
      return {
        time: timeStr ? new Date(timeStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '--:--',
        engine: ENGINE_LABELS[engineKey] || engineKey,
        action,
        title: item.content_title ? `《${item.content_title}》` : (item.remote_url || ''),
        status,
      }
    })
  } catch (e) {
    // 静默失败：不影响主界面，保留上次数据
    console.debug('拉取信号条事件失败', e)
  }
}

// 暴露给子组件触发扫描面板（通过 provide/inject 或事件总线）
function openScanPanel(taskId) {
  scanTaskId.value = taskId
  scanPanelVisible.value = true
  runningTaskCount.value = 1
  scanStatus.value = 'running'
}
provide('openScanPanel', openScanPanel)

let signalTimer = null
onMounted(() => {
  if (showLayout.value) fetchSignalEvents()
  // 每 60 秒刷新一次信号条事件，保持走马灯展示近期活动
  signalTimer = setInterval(fetchSignalEvents, 60000)
})
onUnmounted(() => {
  if (signalTimer) clearInterval(signalTimer)
})

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
