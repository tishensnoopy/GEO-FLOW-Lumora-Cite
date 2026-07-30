import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAutoPipeline } from '@/composables/useAutoPipeline'
import { aiIndexApi } from '@/api/aiIndex'
import api from '@/api'

// mock @/api/aiIndex（ai_index 阶段轮询入口）
vi.mock('@/api/aiIndex', () => ({
  aiIndexApi: {
    listResults: vi.fn(() => Promise.resolve({ data: { items: [] } })),
  },
}))

// mock @/api（citation 阶段轮询入口：GET /admin/citation/results）
vi.mock('@/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: { items: [] } })),
  },
}))

describe('useAutoPipeline', () => {
  beforeEach(() => {
    // 模块级单例：每个测试前清理 statuses / trackedUrls / 定时器，避免跨用例污染
    const { stopAll } = useAutoPipeline()
    stopAll()
    aiIndexApi.listResults.mockReset()
    api.get.mockReset()
  })
  afterEach(() => {
    const { stopAll } = useAutoPipeline()
    stopAll()
    // 复位 fake timer，避免影响后续用例
    vi.useRealTimers()
  })

  it('trackUrl 初始状态为 pending', () => {
    const { getStatus } = useAutoPipeline()
    expect(getStatus('x')).toBe('pending')
  })

  it('refresh 后更新状态（ai_index 阶段：indexed 切换到 citation 阶段，状态为 indexed）', async () => {
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    // citation 阶段首次轮询返回空（尚未生成结果）
    api.get.mockResolvedValue({ data: { items: [] } })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    expect(getStatus('x')).toBe('pending')
    await refresh()
    expect(aiIndexApi.listResults).toHaveBeenCalledWith({ url: 'x' })
    // indexed 后不立即终止，而是切换到 citation 轮询阶段，状态显示"问题监测中"
    expect(getStatus('x')).toBe('indexed')
  })

  it('not_indexed 终态后停止轮询该 URL（ai_index 阶段即终止）', async () => {
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'y', index_status: 'not_indexed' }] },
    })
    const { trackUrl, refresh, getStatus, isTracked } = useAutoPipeline()
    trackUrl('y')
    await refresh()
    expect(getStatus('y')).toBe('not_indexed')
    // 终态后仍可见（statuses 保留），便于徽章持续展示最终结果
    expect(isTracked('y')).toBe(true)
    // not_indexed 不应进入 citation 阶段
    expect(api.get).not.toHaveBeenCalled()
  })

  it('citation 阶段：hit_type != none → 状态为 cited（监测完成，有引用）', async () => {
    // ai_index 阶段：第一次返回 indexed，切换到 citation 阶段
    aiIndexApi.listResults.mockResolvedValueOnce({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    // citation 阶段：返回有 hit_type != 'none' 的记录
    api.get.mockResolvedValue({
      data: {
        items: [
          { url: 'x', hit_type: 'exact' },
          { url: 'x', hit_type: 'none' },
        ],
      },
    })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    await refresh() // ai_index 阶段：indexed → 切换到 citation 阶段
    await refresh() // citation 阶段：检测到 hit → cited
    expect(getStatus('x')).toBe('cited')
    expect(api.get).toHaveBeenCalledWith('/admin/citation/results', { params: { url: 'x' } })
  })

  it('citation 阶段：所有 hit_type == none → 状态为 not_cited（监测完成，无引用）', async () => {
    aiIndexApi.listResults.mockResolvedValueOnce({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    api.get.mockResolvedValue({
      data: { items: [{ url: 'x', hit_type: 'none' }] },
    })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    await refresh() // 切换到 citation 阶段
    await refresh() // citation 阶段：无 hit → not_cited
    expect(getStatus('x')).toBe('not_cited')
  })

  it('citation 阶段：无结果时保持 indexed 状态继续轮询', async () => {
    aiIndexApi.listResults.mockResolvedValueOnce({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    api.get.mockResolvedValue({ data: { items: [] } })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    await refresh() // 切换到 citation 阶段
    await refresh() // citation 无结果，保持 indexed
    expect(getStatus('x')).toBe('indexed')
  })

  it('listResults 异常时状态变 failed', async () => {
    aiIndexApi.listResults.mockRejectedValue(new Error('network'))
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('z')
    await refresh()
    expect(getStatus('z')).toBe('failed')
  })

  // I6: 5 分钟最大轮询超时
  it('超过 5 分钟仍未到终态时，状态变 failed 并停止轮询', async () => {
    vi.useFakeTimers()
    // ai_index 始终返回 pending（无终态），让超时逻辑触发
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'x', index_status: 'pending' }] },
    })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    // 立即推进 5 分 1 秒（超过 MAX_POLL_DURATION = 5 * 60 * 1000 ms）
    vi.advanceTimersByTime(5 * 60 * 1000 + 100)
    await refresh()
    expect(getStatus('x')).toBe('failed')
  })

  it('未超时前正常轮询不会误判 failed', async () => {
    vi.useFakeTimers()
    aiIndexApi.listResults.mockResolvedValue({
      data: { items: [{ url: 'x', index_status: 'pending' }] },
    })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    // 推进 4 分钟（未超时）
    vi.advanceTimersByTime(4 * 60 * 1000)
    await refresh()
    // 仍未到终态，保持 pending，不应变 failed
    expect(getStatus('x')).toBe('pending')
  })

  it('citation 阶段超时也触发 failed', async () => {
    vi.useFakeTimers()
    // ai_index 立即 indexed，进入 citation 阶段
    aiIndexApi.listResults.mockResolvedValueOnce({
      data: { items: [{ url: 'x', index_status: 'indexed' }] },
    })
    // citation 始终返回空（无终态）
    api.get.mockResolvedValue({ data: { items: [] } })
    const { trackUrl, refresh, getStatus } = useAutoPipeline()
    trackUrl('x')
    await refresh() // 进入 citation 阶段
    // 推进 5 分 1 秒
    vi.advanceTimersByTime(5 * 60 * 1000 + 100)
    await refresh()
    expect(getStatus('x')).toBe('failed')
  })
})
