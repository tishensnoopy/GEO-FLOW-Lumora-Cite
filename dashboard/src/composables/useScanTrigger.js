import { ref } from 'vue'
import api from '@/api'

export function useScanTrigger() {
  const taskIds = ref(null)
  const currentTaskId = ref(null)
  const panelVisible = ref(false)

  async function trigger(scanType, options = {}) {
    const res = await api.post('/admin/scan/trigger', { scan_type: scanType, ...options })
    if (scanType === 'all') {
      taskIds.value = res.data.task_ids
      currentTaskId.value = res.data.task_ids.index
    } else {
      currentTaskId.value = res.data.task_id
    }
    panelVisible.value = true
    return res.data
  }

  return { taskIds, currentTaskId, panelVisible, trigger }
}
