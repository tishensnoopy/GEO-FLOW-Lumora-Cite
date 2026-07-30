import { describe, it, expect, vi } from 'vitest'
import { useScanTrigger } from '@/composables/useScanTrigger'
import api from '@/api'

vi.mock('@/api', () => ({ default: { post: vi.fn() } }))

describe('useScanTrigger', () => {
  it('trigger 单类型返回 task_ids[scanType] 作为 currentTaskId，taskIds 为 null', async () => {
    // 后端 /admin/scan/trigger 对单类型也返回 task_ids dict（非顶层 task_id）
    api.post.mockResolvedValue({ data: { task_ids: { index: 't1' }, message: '已触发 index 扫描' } })
    const { trigger, currentTaskId, taskIds, panelVisible } = useScanTrigger()
    await trigger('index')
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'index' })
    expect(currentTaskId.value).toBe('t1')
    expect(taskIds.value).toBeNull()
    expect(panelVisible.value).toBe(true)
  })

  it('trigger ai_index 类型返回 task_ids.ai_index 作为 currentTaskId', async () => {
    api.post.mockResolvedValue({ data: { task_ids: { ai_index: 't-ai' }, message: '已触发 ai_index 扫描' } })
    const { trigger, currentTaskId, taskIds } = useScanTrigger()
    await trigger('ai_index')
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'ai_index' })
    expect(currentTaskId.value).toBe('t-ai')
    expect(taskIds.value).toBeNull()
  })

  it('trigger all 返回 task_ids dict，currentTaskId 取 index 阶段任务 ID', async () => {
    api.post.mockResolvedValue({
      data: {
        task_ids: { index: 't1', ai_index: 't2', citation: 't3' },
        message: '已触发 all 扫描',
      },
    })
    const { trigger, taskIds, currentTaskId, panelVisible } = useScanTrigger()
    await trigger('all')
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'all' })
    expect(taskIds.value).toEqual({ index: 't1', ai_index: 't2', citation: 't3' })
    expect(currentTaskId.value).toBe('t1')
    expect(panelVisible.value).toBe(true)
  })

  it('trigger 单类型后端返回 task_ids[scanType]=null（无待检测）时 currentTaskId 为 null', async () => {
    api.post.mockResolvedValue({ data: { task_ids: { index: null }, message: '已触发 index 扫描' } })
    const { trigger, currentTaskId, panelVisible } = useScanTrigger()
    await trigger('index')
    expect(currentTaskId.value).toBeNull()
    // 仍打开面板，让用户看到"无待检测"的反馈（由调用方决定是否提示）
    expect(panelVisible.value).toBe(true)
  })
})
