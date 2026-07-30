import { describe, it, expect, vi, beforeEach } from 'vitest'
import { aiIndexApi } from '@/api/aiIndex'
import { clientQuestionApi } from '@/api/clientQuestion'
import { clientViewApi } from '@/api/clientView'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  },
}))

import api from '@/api'

describe('aiIndexApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('triggerScan 调用 POST /admin/ai-index/scan', async () => {
    await aiIndexApi.triggerScan()
    expect(api.post).toHaveBeenCalledWith('/admin/ai-index/scan')
  })
  it('listResults 带 params 调用 GET /admin/ai-index/results', async () => {
    const params = { url: 'x', model: 'doubao', index_status: 'indexed', page: 1, page_size: 20 }
    await aiIndexApi.listResults(params)
    expect(api.get).toHaveBeenCalledWith('/admin/ai-index/results', { params })
  })
  it('getStats 调用 GET /admin/ai-index/stats', async () => {
    await aiIndexApi.getStats()
    expect(api.get).toHaveBeenCalledWith('/admin/ai-index/stats', { params: {} })
  })
})

describe('clientQuestionApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('list 调用 GET /admin/clients/{id}/questions', async () => {
    await clientQuestionApi.list('DEMO001')
    expect(api.get).toHaveBeenCalledWith('/admin/clients/DEMO001/questions')
  })
  it('create 调用 POST', async () => {
    await clientQuestionApi.create('DEMO001', { question: 'test' })
    expect(api.post).toHaveBeenCalledWith('/admin/clients/DEMO001/questions', { question: 'test' })
  })
  it('reorder 调用 POST reorder', async () => {
    await clientQuestionApi.reorder('DEMO001', ['id1', 'id2'])
    expect(api.post).toHaveBeenCalledWith('/admin/clients/DEMO001/questions/reorder', { ordered_ids: ['id1', 'id2'] })
  })
  it('listOwn 调用 GET /questions（客户端只读）', async () => {
    await clientQuestionApi.listOwn()
    expect(api.get).toHaveBeenCalledWith('/questions')
  })
})

describe('clientViewApi', () => {
  beforeEach(() => vi.clearAllMocks())
  it('overview 调用 GET /ai-index/overview', async () => {
    await clientViewApi.overview()
    expect(api.get).toHaveBeenCalledWith('/ai-index/overview')
  })
  it('evidence 带 params 调用 GET /citations/evidence', async () => {
    await clientViewApi.evidence({ hit_type: 'exact' })
    expect(api.get).toHaveBeenCalledWith('/citations/evidence', { params: { hit_type: 'exact' } })
  })
})
