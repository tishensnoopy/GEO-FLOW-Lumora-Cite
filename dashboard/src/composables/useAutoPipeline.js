import { reactive } from 'vue'
import { aiIndexApi } from '@/api/aiIndex'
import api from '@/api'

// 模块级单例：多组件共享同一份联动状态。
// 手动添加文章后，前端无法预知后端何时完成收录检测，故用轮询驱动 UI 徽章。
// statuses 保留所有曾追踪 URL 的最新状态（含终态），trackedUrls 仅保存待轮询的 URL。
const statuses = reactive({})
// trackedUrls 改为 Map：value 记录当前轮询阶段（ai_index | citation）与开始时间，
// 用于实现"双阶段管道 + 5 分钟最大轮询超时"。
//   phase: 'ai_index'   — 收录检测中，轮询 aiIndexApi.listResults
//   phase: 'citation'   — 已收录，进入问题监测阶段，轮询 GET /admin/citation/results
const trackedUrls = new Map()
let pollTimer = null

const POLL_INTERVAL = 3000
// I6: 设计规格要求"最多 5 分钟后停止"，避免后端任务卡死时无限轮询。
const MAX_POLL_DURATION = 5 * 60 * 1000

export function useAutoPipeline() {
  // 注册 URL 追踪：初始 pending，并启动轮询（若未启动）
  function trackUrl(url) {
    if (!url) return
    statuses[url] = 'pending'
    trackedUrls.set(url, { phase: 'ai_index', startTime: Date.now() })
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

  // 拉取所有待轮询 URL 的最新结果，更新状态；
  // 双阶段管道：
  //   1. ai_index 阶段：调 aiIndexApi.listResults，indexed 后切换到 citation 阶段
  //      （状态显示"问题监测中"），not_indexed 直接终态。
  //   2. citation 阶段：调 GET /admin/citation/results，根据 hit_type 决定 cited/not_cited。
  // 6 状态：pending(黄) / indexed(蓝,监测中) / cited(绿,有引用) /
  //         not_cited(灰,无引用) / not_indexed(灰,未收录) / failed(红,失败)
  // 超时（5min）未到终态 → failed，避免无限轮询。
  async function refresh() {
    for (const url of [...trackedUrls.keys()]) {
      const track = trackedUrls.get(url)
      // I6: 超时检查（在调用 API 前判断，避免卡死任务继续消耗配额）
      if (Date.now() - track.startTime > MAX_POLL_DURATION) {
        statuses[url] = 'failed'
        trackedUrls.delete(url)
        continue
      }
      try {
        if (track.phase === 'ai_index') {
          const res = await aiIndexApi.listResults({ url })
          const items = res.data?.items || []
          if (items.length === 0) continue
          // 取最新一条判断状态（后端按时间倒序返回）
          const latest = items[0]
          if (latest.index_status === 'indexed') {
            // I5: indexed 后不立即终止，切换到 citation 阶段，状态显示"问题监测中"
            statuses[url] = 'indexed'
            track.phase = 'citation'
          } else if (latest.index_status === 'not_indexed') {
            statuses[url] = 'not_indexed'
            trackedUrls.delete(url)
          }
          // pending / checking 等中间态：保持当前 status 继续轮询
        } else if (track.phase === 'citation') {
          const res = await api.get('/admin/citation/results', { params: { url } })
          const items = res.data?.items || []
          if (items.length === 0) continue
          // 任一条 hit_type != 'none' 即视为"被引用"
          const hasHit = items.some(i => i.hit_type && i.hit_type !== 'none')
          statuses[url] = hasHit ? 'cited' : 'not_cited'
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
