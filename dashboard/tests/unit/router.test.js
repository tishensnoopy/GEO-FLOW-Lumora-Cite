import { describe, it, expect } from 'vitest'
import { decideRoute } from '../../src/router/guard.js'

// 测试路由守卫的分流逻辑（纯函数提取，不依赖真实 router 实例）
describe('路由守卫分流逻辑', () => {
  it('未登录访问受保护路由 → 跳 /login', () => {
    const decision = decideRoute({ path: '/', meta: { requiresAuth: true }, role: null, token: null })
    expect(decision).toBe('/login')
  })
  it('admin 访问 requiresAdmin 路由 → 放行', () => {
    const decision = decideRoute({ path: '/clients', meta: { requiresAuth: true, requiresAdmin: true }, role: 'admin', token: 'x' })
    expect(decision).toBe(null)  // null 表示放行
  })
  it('client 访问 requiresAdmin 路由 → 跳 /client/overview', () => {
    const decision = decideRoute({ path: '/clients', meta: { requiresAuth: true, requiresAdmin: true }, role: 'client', token: 'x' })
    expect(decision).toBe('/client/overview')
  })
  it('client 访问 / → 跳 /client/overview', () => {
    const decision = decideRoute({ path: '/', meta: { requiresAuth: true }, role: 'client', token: 'x' })
    expect(decision).toBe('/client/overview')
  })
  it('admin 访问 /client/* → 跳 /', () => {
    const decision = decideRoute({ path: '/client/overview', meta: { requiresAuth: true, requiresClient: true }, role: 'admin', token: 'x' })
    expect(decision).toBe('/')
  })
  it('client 访问 /client/overview → 放行', () => {
    const decision = decideRoute({ path: '/client/overview', meta: { requiresAuth: true, requiresClient: true }, role: 'client', token: 'x' })
    expect(decision).toBe(null)
  })
})
