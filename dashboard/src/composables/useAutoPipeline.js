import { reactive } from 'vue'
import { aiIndexApi } from '@/api/aiIndex'

// 模块级单例：多组件共享同一份联动状态。
// 手动添加文章后，前端无法预知后端何时完成收录检测，故用轮询驱动 UI 徽章。
// statuses 保留所有曾追踪 URL 的最新状态（含终态），trackedUrls 仅保存待轮询的 URL。
const statuses = reactive({})
const trackedUrls = new Set()
let pollTimer = null

const POLL_INTERVAL = 3000

export function useAutoPipeline() {
  // 注册 URL 追踪：初始 pending，并启动轮询（若未启动）
  function trackUrl(url) {
    if (!url) return
    statuses[url] = 'pending'
    trackedUrls.add(url)
    if (!pollTimer) startPolling()
  }

  // 返回 URL 当前状态；未追踪 URL 默认 pending（便于 UI 兜底）
  function getStatus(url) {
    return statuses[url] || 'pending'
  }

  // 该 URL 是否曾被追踪（用于 UI 决定是否展示联动徽章）
  function isTracked(url) {
    return statuses[url] !== undefined
  }

  // 拉取所有待轮询 URL 的最新收录结果，更新状态；
  // 收到终态（indexed/not_indexed）后停止对该 URL 的轮询，但保留 statuses 以持续展示最终结果。
  async function refresh() {
    for (const url of [...trackedUrls]) {
      try {
        const res = await aiIndexApi.listResults({ url })
        const items = res.data?.items || []
        if (items.length === 0) continue
        // 取最新一条判断状态（后端按时间倒序返回）
        const latest = items[0]
        statuses[url] = latest.index_status
        if (latest.index_status === 'indexed' || latest.index_status === 'not_indexed') {
          trackedUrls.delete(url)
        }
      } catch {
        statuses[url] = 'failed'
        trackedUrls.delete(url)
      }
    }
    if (trackedUrls.size === 0) stopPolling()
  }

  function startPolling() {
    pollTimer = setInterval(refresh, POLL_INTERVAL)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // 清理全部状态：定时器 + trackedUrls + statuses。
  // 主要用于测试隔离；生产环境单例常驻，不主动调用。
  function stopAll() {
    stopPolling()
    trackedUrls.clear()
    for (const key of Object.keys(statuses)) {
      delete statuses[key]
    }
  }

  return { trackUrl, getStatus, isTracked, refresh, stopAll }
}
