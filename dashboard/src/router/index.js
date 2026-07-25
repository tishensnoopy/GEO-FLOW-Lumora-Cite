import { createRouter, createWebHistory } from 'vue-router'

// D13 修复：在 M4 主计划路由基础上保留现有 /articles + /settings，
// 追加 /distributions + /audit-logs（任务 3/6 实现具体页面）
const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/articles', name: 'Articles', component: () => import('../views/Articles.vue'), meta: { requiresAuth: true } },
  { path: '/distributions', name: 'Distributions', component: () => import('../views/Distributions.vue'), meta: { requiresAuth: true } },
  { path: '/exports', name: 'Exports', component: () => import('../views/Exports.vue'), meta: { requiresAuth: true } },
  { path: '/audit-logs', name: 'AuditLogs', component: () => import('../views/AuditLogs.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue'), meta: { requiresAuth: true } }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else if (to.meta.requiresAdmin && localStorage.getItem('role') !== 'admin') {
    // 非管理员访问 admin 专用路由 → 跳转根路径（即 Dashboard）
    next('/')
  } else {
    next()
  }
})

export default router
