import api from './index'

export const clientViewApi = {
  overview: () => api.get('/ai-index/overview'),
  evidence: (params) => api.get('/citations/evidence', { params }),
  stats: () => api.get('/stats'),
}
