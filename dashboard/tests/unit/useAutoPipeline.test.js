import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAutoPipeline } from '@/composables/useAutoPipeline'
import { aiIndexApi } from '@/api/aiIndex'

vi.mock('@/api/aiIndex', () => ({
  aiIndexApi: {
    listResults: vi.fn(() => Promise.resolve({ data: { items: [{ url: 'x', index_status: 'indexed' }] } })),
  },
}))

describe('useAutoPipeline', () => {
  beforeEach(() => {
    // 模块级单例：每个测试前清理 statuses / trackedUrls / 定时器，避免跨用例污染
    const { stopAll } = useAutoPipeline()
    stopAll()
    aiIndexApi.listResults.mockReset()
  })
  afterEach(() => {
    const { stopAll } = useAutoPipeline()
    stopAll()
  })

  it('trackUrl 初始状态为 pending', () => {
    const { getStatus } = useAutoPipeline()
    expect(getStatus('x')).toBe('pending')
  })

  it('refresh 后更新状态', async () => {
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    expect(getStatus('x')).toBe('pending')
    await refresh()
    expect(aiIndexApi.listResults).toHaveBeenCalledWith({ url: 'x' })
    expect(getStatus('x')).toBe('indexed')
  })

  it('not_indexed 终态后停止轮询该 URL', async () => {
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'y', index_status: 'not_indexed' }] },
    })
    const { trackUrl, refresh, getStatus, isTracked } = useAutoPipeline()
    trackUrl('y')
    await refresh()
    expect(getStatus('y')).toBe('not_indexed')
    // 终态后仍可见（statuses 保留），便于徽章持续展示最终结果
    expect(isTracked('y')).toBe(true)
  })

  it('listResults 异常时状态变 failed', async () => {
    aiIndexApi.listResults.mockRejectedValue(new Error('network'))
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('z')
    await refresh()
    expect(getStatus('z')).toBe('failed')
  })
})
