import { describe, it, expect, vi, beforeEach } from 'vitest'

// 每个用例 resetModules + 重新动态 import，拿到全新的 store 实例与 api mock，
// 避免 state 在用例间互相污染。
let api
let store

beforeEach(async () => {
  vi.resetModules()
  vi.doMock('@/api', () => ({
    default: {
      get: vi.fn(() => Promise.resolve({ data: {} })),
      post: vi.fn(() => Promise.resolve({ data: {} })),
    },
  }))
  api = (await import('@/api')).default
  store = (await import('@/store/index.js')).default
})

describe('store aiIndexStats 扩展', () => {
  it('初始 state 含 aiIndexStats（零值占位，避免 undefined）', () => {
    expect(store.state.aiIndexStats).toBeDefined()
    expect(store.state.aiIndexStats.indexed).toBe(0)
    expect(store.state.aiIndexStats.not_indexed).toBe(0)
    expect(store.state.aiIndexStats.pending).toBe(0)
    expect(store.state.aiIndexStats.index_rate).toBe(0)
    expect(Array.isArray(store.state.aiIndexStats.by_model)).toBe(true)
    expect(Array.isArray(store.state.aiIndexStats.by_client)).toBe(true)
  })

  it('fetchAiIndexStats 调用 GET /admin/ai-index/stats 并写入 state', async () => {
    const payload = {
      total_combinations: 10,
      indexed: 7, not_indexed: 2, pending: 1, index_rate: 0.7,
      by_model: [{ model: 'doubao', indexed: 7, rate: 0.7 }],
      by_client: [{ client_id: 'DEMO001', indexed: 7, rate: 0.7 }],
    }
    api.get.mockResolvedValueOnce({ data: payload })
    await store.dispatch('fetchAiIndexStats')
    expect(api.get).toHaveBeenCalledWith('/admin/ai-index/stats')
    expect(store.state.aiIndexStats).toEqual(payload)
  })

  it('fetchAiIndexStats 失败时不污染既有 state（保留上次值）', async () => {
    api.get.mockRejectedValueOnce(new Error('network'))
    // 先写入一个值
    store.commit('SET_AI_INDEX_STATS', {
      indexed: 5, not_indexed: 0, pending: 0, index_rate: 0.5,
      by_model: [], by_client: [],
    })
    // 失败时不 commit，state 保持上次值
    await expect(store.dispatch('fetchAiIndexStats')).rejects.toThrow('network')
    expect(store.state.aiIndexStats.indexed).toBe(5)
    expect(store.state.aiIndexStats.index_rate).toBe(0.5)
  })

  it('不影响既有 state/mutations/actions（indexStats/citationStats 仍可用）', () => {
    expect(store.state.indexStats).toEqual({ total: 0, indexed: 0, rate: 0 })
    expect(store.state.citationStats).toEqual({ total: 0, cited: 0, rate: 0 })
    store.commit('SET_INDEX_STATS', { total: 10 })
    expect(store.state.indexStats.total).toBe(10)
    expect(store.getters.isAuthenticated).toBe(false)
  })
})
