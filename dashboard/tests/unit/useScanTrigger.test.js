import { describe, it, expect, vi } from 'vitest'
import { useScanTrigger } from '@/composables/useScanTrigger'
import api from '@/api'

vi.mock('@/api', () => ({ default: { post: vi.fn() } }))

describe('useScanTrigger', () => {
  it('trigger 单类型返回 task_id', async () => {
    api.post.mockResolvedValue({ data: { task_id: 't1' } })
    const { trigger, currentTaskId, panelVisible } = useScanTrigger()
    await trigger('index')
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'index' })
    expect(currentTaskId.value).toBe('t1')
    expect(panelVisible.value).toBe(true)
  })
  it('trigger all 返回 task_ids，currentTaskId 取 index', async () => {
    api.post.mockResolvedValue({ data: { task_ids: { index: 't1', ai_index: 't2', citation: 't3' } } })
    const { trigger, taskIds, currentTaskId } = useScanTrigger()
    await trigger('all')
    expect(taskIds.value).toEqual({ index: 't1', ai_index: 't2', citation: 't3' })
    expect(currentTaskId.value).toBe('t1')
  })
})
