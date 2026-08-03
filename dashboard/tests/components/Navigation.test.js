import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createStore } from 'vuex'

// SidebarNav / MobileTabBar 仅依赖 useRoute + useStore + element-plus icons
// icons 是 SVG 组件，直接挂载即可（不 stub），断言走文本/属性
import SidebarNav from '@/components/SidebarNav.vue'
import MobileTabBar from '@/components/MobileTabBar.vue'

const stubs = {
  'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
  'router-link': {
    name: 'RouterLink',
    props: ['to', 'title'],
    template: '<a class="router-link-stub" :data-to="to" :title="title"><slot /></a>',
  },
}

function buildRouterStore(role) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/distributions', component: { template: '<div/>' } },
      { path: '/articles', component: { template: '<div/>' } },
      { path: '/ai-index', component: { template: '<div/>' } },
      { path: '/exports', component: { template: '<div/>' } },
      { path: '/clients', component: { template: '<div/>' } },
      { path: '/audit-logs', component: { template: '<div/>' } },
      { path: '/settings', component: { template: '<div/>' } },
      { path: '/client/overview', component: { template: '<div/>' } },
      { path: '/client/evidence', component: { template: '<div/>' } },
      { path: '/client/rankings', component: { template: '<div/>' } },
      { path: '/client/articles', component: { template: '<div/>' } },
      { path: '/client/settings', component: { template: '<div/>' } },
    ],
  })
  const store = createStore({
    state: { role, token: 't', user: null },
    actions: { logout: () => {} },
  })
  return { router, store }
}

let wrapper
beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
})

describe('SidebarNav 角色适配', () => {
  it('admin 显示 AI 收录检测菜单项', async () => {
    const { router, store } = buildRouterStore('admin')
    await router.push('/')
    await router.isReady()
    wrapper = mount(SidebarNav, {
      global: { plugins: [router, store], stubs },
      props: { expanded: true },
    })
    const text = wrapper.text()
    expect(text).toContain('AI 收录检测')
    // 链接指向 /ai-index
    const links = wrapper.findAll('.router-link-stub')
    const aiIndexLink = links.find(a => a.attributes('data-to') === '/ai-index')
    expect(aiIndexLink).toBeTruthy()
  })

  it('admin 完整菜单顺序：仪表盘/分发记录/文章列表/AI 收录检测/导出报告/客户管理/审计日志/系统设置', async () => {
    const { router, store } = buildRouterStore('admin')
    await router.push('/')
    await router.isReady()
    wrapper = mount(SidebarNav, {
      global: { plugins: [router, store], stubs },
      props: { expanded: true },
    })
    const labels = wrapper.findAll('.nav-list .router-link-stub').map(a => a.text())
    expect(labels).toEqual([
      '仪表盘', '分发记录', '文章列表', 'AI 收录检测',
      '导出报告', '客户管理', '审计日志', '系统设置',
    ])
  })

  it('client 不显示 SidebarNav（仅管理员用，客户端走 ClientLayout）', async () => {
    const { router, store } = buildRouterStore('client')
    await router.push('/')
    await router.isReady()
    wrapper = mount(SidebarNav, {
      global: { plugins: [router, store], stubs },
      props: { expanded: true },
    })
    // SidebarNav 整体不渲染：无菜单项、无退出按钮、无扫描状态
    expect(wrapper.findAll('.nav-item')).toHaveLength(0)
    expect(wrapper.findAll('.router-link-stub')).toHaveLength(0)
    const text = wrapper.text()
    expect(text).not.toContain('AI 收录检测')
    expect(text).not.toContain('客户管理')
    expect(text).not.toContain('退出登录')
  })
})

describe('MobileTabBar 角色适配', () => {
  it('admin 渲染 5 个 tab（仪表/分发/收录/采信/设置）', async () => {
    const { router, store } = buildRouterStore('admin')
    await router.push('/')
    await router.isReady()
    wrapper = mount(MobileTabBar, {
      global: { plugins: [router, store], stubs },
    })
    const tabs = wrapper.findAll('.tab-item')
    expect(tabs).toHaveLength(5)
    const labels = tabs.map(t => t.text())
    expect(labels).toEqual(['仪表', '分发', '收录', '采信', '设置'])
    // 指向 admin 路由
    const paths = tabs.map(t => t.attributes('data-to'))
    expect(paths).toEqual(['/', '/distributions', '/articles', '/exports', '/settings'])
  })

  it('client 渲染 5 个 tab（概览/证据/快照/文章/设置），指向 /client/*', async () => {
    const { router, store } = buildRouterStore('client')
    await router.push('/client/overview')
    await router.isReady()
    wrapper = mount(MobileTabBar, {
      global: { plugins: [router, store], stubs },
    })
    const tabs = wrapper.findAll('.tab-item')
    expect(tabs).toHaveLength(5)
    const labels = tabs.map(t => t.text())
    expect(labels).toEqual(['概览', '证据', '快照', '文章', '设置'])
    const paths = tabs.map(t => t.attributes('data-to'))
    expect(paths).toEqual([
      '/client/overview', '/client/evidence', '/client/rankings', '/client/articles', '/client/settings',
    ])
  })

  it('client tab 不包含 admin 入口（分发/收录/采信）', async () => {
    const { router, store } = buildRouterStore('client')
    await router.push('/client/overview')
    await router.isReady()
    wrapper = mount(MobileTabBar, {
      global: { plugins: [router, store], stubs },
    })
    const text = wrapper.text()
    expect(text).not.toContain('分发')
    expect(text).not.toContain('采信')
  })
})
