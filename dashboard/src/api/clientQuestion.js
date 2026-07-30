import api from './index'

export const clientQuestionApi = {
  list: (clientId) => api.get(`/admin/clients/${clientId}/questions`),
  create: (clientId, data) => api.post(`/admin/clients/${clientId}/questions`, data),
  update: (clientId, qid, data) => api.put(`/admin/clients/${clientId}/questions/${qid}`, data),
  delete: (clientId, qid) => api.delete(`/admin/clients/${clientId}/questions/${qid}`),
  reorder: (clientId, orderedIds) => api.post(`/admin/clients/${clientId}/questions/reorder`, { ordered_ids: orderedIds }),
  listOwn: () => api.get('/questions'),
}
