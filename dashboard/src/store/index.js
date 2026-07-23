import { createStore } from 'vuex'
import api from '../api'

export default createStore({
  state: {
    user: null,
    token: localStorage.getItem('token') || null,
    indexStats: { total: 0, indexed: 0, rate: 0 },
    citationStats: { total: 0, cited: 0, rate: 0 }
  },
  mutations: {
    SET_TOKEN(state, token) {
      state.token = token
      if (token) localStorage.setItem('token', token)
      else localStorage.removeItem('token')
    },
    SET_INDEX_STATS(state, stats) { state.indexStats = stats },
    SET_CITATION_STATS(state, stats) { state.citationStats = stats }
  },
  actions: {
    async login({ commit }, credentials) {
      const res = await api.post('/auth/login', credentials)
      commit('SET_TOKEN', res.data.access_token)
      return res.data
    },
    async logout({ commit }) { commit('SET_TOKEN', null) },
    async fetchIndexStats({ commit }) {
      const res = await api.get('/stats/index')
      commit('SET_INDEX_STATS', res.data)
    },
    async fetchCitationStats({ commit }) {
      const res = await api.get('/stats/citation')
      commit('SET_CITATION_STATS', res.data)
    }
  },
  getters: {
    isAuthenticated: state => !!state.token
  }
})
