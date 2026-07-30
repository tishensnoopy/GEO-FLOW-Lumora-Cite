import { ref } from 'vue'
import api from '@/api'

// 扫描触发逻辑复用层：统一调 POST /admin/scan/trigger（Phase 3 统一入口）。
// 后端响应契约：始终返回 { task_ids: { <scan_type>: <task_id>|null }, message }
//   - 单类型（index/ai_index/citation）：task_ids 仅含该类型一个键
//   - all 类型：task_ids 含 index/ai_index/citation 三个键（顺序执行）
// taskIds ref 仅在 all 类型时填充（驱动 ScanPanel 三阶段进度环）；
// currentTaskId 取当前阶段任务 ID（all 取 index 阶段），驱动主进度环。
export function useScanTrigger() {
  const taskIds = ref(null)
  const currentTaskId = ref(null)
  const panelVisible = ref(false)

  async function trigger(scanType, options = {}) {
    const res = await api.post('/admin/scan/trigger', { scan_type: scanType, ...options })
    const ids = res.data?.task_ids || {}
    if (scanType === 'all') {
      taskIds.value = ids
      currentTaskId.value = ids.index || null
    } else {
      // 单类型不展示三阶段进度环，taskIds 保持 null
      taskIds.value = null
      currentTaskId.value = ids[scanType] ?? null
    }
    panelVisible.value = true
    return res.data
  }

  return { taskIds, currentTaskId, panelVisible, trigger }
}
