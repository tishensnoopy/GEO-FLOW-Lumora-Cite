import { createStore } from 'vuex'
import api from '../api'

export default createStore({
  state: {
    user: null,
    token: localStorage.getItem('token') || null,
    role: localStorage.getItem('role') || null,
    indexStats: { total: 0, indexed: 0, rate: 0 },
    citationStats: { total: 0, cited: 0, rate: 0 },
    // Phase 4 任务 8：AI 收录检测统计（管理员视图 AiIndex 消费）
    // 形状对齐后端 GET /admin/ai-index/stats 真实响应
    aiIndexStats: {
      total_combinations: 0,
      indexed: 0,
      not_indexed: 0,
      pending: 0,
      index_rate: 0,
      by_model: [],
      by_client: []
    }
  },
  mutations: {
    SET_TOKEN(state, token) {
      state.token = token
      if (token) localStorage.setItem('token', token)
      else localStorage.removeItem('token')
    },
    SET_ROLE(state, role) {
      state.role = role
      if (role) localStorage.setItem('role', role)
      else localStorage.removeItem('role')
    },
    SET_INDEX_STATS(state, stats) { state.indexStats = stats },
    SET_CITATION_STATS(state, stats) { state.citationStats = stats },
    SET_AI_INDEX_STATS(state, stats) { state.aiIndexStats = stats }
  },
  actions: {
    // D12 修复：保留 store login action，credentials 透传（Login.vue 传 client_id）
    // 后端 /auth/login 接收 { client_id, password }，返回 { access_token, role, ... }
    async login({ commit }, credentials) {
      const res = await api.post('/auth/login', credentials)
      commit('SET_TOKEN', res.data.access_token)
      commit('SET_ROLE', res.data.role || 'client')
      return res.data
    },
    async logout({ commit }) {
      commit('SET_TOKEN', null)
      commit('SET_ROLE', null)
    },
    async fetchIndexStats({ commit }) {
      const res = await api.get('/stats/index')
      commit('SET_INDEX_STATS', res.data)
    },
    async fetchCitationStats({ commit }) {
      const res = await api.get('/stats/citation')
      commit('SET_CITATION_STATS', res.data)
    },
    // Phase 4 任务 8：拉取 AI 收录检测统计；失败时抛错给调用方处理（不静默吞，
    // 由 AiIndex 视图决定是否回退到本地缓存或显示错误态）
    async fetchAiIndexStats({ commit }) {
      const res = await api.get('/admin/ai-index/stats')
      commit('SET_AI_INDEX_STATS', res.data)
    }
  },
  getters: {
    isAuthenticated: state => !!state.token
  }
})
