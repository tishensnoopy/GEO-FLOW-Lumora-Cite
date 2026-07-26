import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 登录请求的 401 不跳转（让 Login.vue 显示错误提示），其他 API 401 才跳转
      const isLoginRequest = error.config?.url?.includes('/auth/login') || error.config?.url?.includes('/sso/')
      const isLoginPage = window.location.pathname === '/login'
      if (!isLoginRequest && !isLoginPage) {
        // 修复：只清除鉴权相关的键，不要 localStorage.clear()
        // localStorage.clear() 会无差别清掉所有键，可能误清 SSO callback 刚写入的 token（竞态）
        localStorage.removeItem('token')
        localStorage.removeItem('role')
        localStorage.removeItem('user_name')
        // 注意：不清 client_id，避免客户登录后 401 丢失 client_id
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// 同时提供命名导出（M4 新组件使用 `import { api } from '@/api'`）
// 与默认导出（M1 既有组件使用 `import api from '@/api'`），保持向后兼容。
export { api }
export default api
