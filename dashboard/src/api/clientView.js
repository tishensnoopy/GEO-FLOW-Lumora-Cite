import api from './index'

export const clientViewApi = {
  overview: () => api.get('/ai-index/overview'),
  evidence: (params) => api.get('/citations/evidence', { params }),
  stats: () => api.get('/stats'),
  // Phase 2：客户工作报告（发稿量披露）
  workReport: () => api.get('/client/work-report'),
  // Phase 2：回答快照（各平台 AI 回答全文）
  rankings: () => api.get('/client/rankings'),
  // Phase 2：AI 可见度得分
  visibility: () => api.get('/client/visibility'),
  // 阶段 4：置信度
  confidence: () => api.get('/client/confidence'),
}
