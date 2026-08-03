import { createRouter, createWebHistory } from 'vue-router'
import { decideRoute } from './guard.js'

// D13 修复：在 M4 主计划路由基础上保留现有 /articles + /settings，
// 追加 /distributions + /audit-logs（任务 3/6 实现具体页面）
// Phase 4 任务 1：新增 /ai-index + /client/* 4 个客户端路由，守卫调用 decideRoute 纯函数
const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/articles', name: 'Articles', component: () => import('../views/Articles.vue'), meta: { requiresAuth: true } },
  { path: '/distributions', name: 'Distributions', component: () => import('../views/Distributions.vue'), meta: { requiresAuth: true } },
  { path: '/exports', name: 'Exports', component: () => import('../views/Exports.vue'), meta: { requiresAuth: true } },
  { path: '/audit-logs', name: 'AuditLogs', component: () => import('../views/AuditLogs.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/clients', name: 'Clients', component: () => import('../views/Clients.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue'), meta: { requiresAuth: true } },
  // Phase 4 任务 1 新增路由
  { path: '/ai-index', name: 'AiIndex', component: () => import('../views/AiIndex.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/client/overview', name: 'ClientOverview', component: () => import('../views/client/ClientOverview.vue'), meta: { requiresAuth: true, requiresClient: true } },
  { path: '/client/evidence', name: 'ClientEvidence', component: () => import('../views/client/ClientEvidence.vue'), meta: { requiresAuth: true, requiresClient: true } },
  { path: '/client/rankings', name: 'ClientRankings', component: () => import('../views/client/ClientRankings.vue'), meta: { requiresAuth: true, requiresClient: true } },
  { path: '/client/articles', name: 'ClientArticles', component: () => import('../views/client/ClientArticles.vue'), meta: { requiresAuth: true, requiresClient: true } },
  { path: '/client/settings', name: 'ClientSettings', component: () => import('../views/client/ClientSettings.vue'), meta: { requiresAuth: true, requiresClient: true } }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  const role = localStorage.getItem('role')
  const redirect = decideRoute({ path: to.path, meta: to.meta, role, token })
  if (redirect) next(redirect)
  else next()
})

export default router
