import api from './index'

export const aiIndexApi = {
  triggerScan: () => api.post('/admin/ai-index/scan'),
  triggerRescan: (url) => api.post('/admin/ai-index/rescan', { url }),
  listResults: (params) => api.get('/admin/ai-index/results', { params }),
  getStats: (clientId) => api.get('/admin/ai-index/stats', { params: clientId ? { client_id: clientId } : {} }),
}
