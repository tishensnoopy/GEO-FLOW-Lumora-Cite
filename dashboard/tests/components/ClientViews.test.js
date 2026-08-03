import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createStore } from 'vuex'

// mock element-plus 的服务式 API，避免 ElMessage 在 jsdom 弹窗
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

// mock clientViewApi（任务 2 已实现）
// mock 形状与后端 GET /ai-index/overview 真实响应一致：
//   indexed_urls / not_indexed_urls / index_rate / articles
vi.mock('@/api/clientView', () => ({
  clientViewApi: {
    overview: vi.fn(() => Promise.resolve({
      data: {
        indexed_urls: ['https://x.com'],
        not_indexed_urls: ['https://y.com'],
        index_rate: 0.5,
        articles: [
          {
            url: 'https://x.com',
            title: '文章A',
            model: 'doubao',
            index_status: 'indexed',
            checked_at: '2026-07-30T10:00:00Z',
          },
        ],
      },
    })),
    evidence: vi.fn(() => Promise.resolve({
      data: {
        items: [
          {
            article_title: '文章A',
            url: 'https://x.com',
            model: 'doubao',
            question: '示例问题?',
            hit_type: 'exact',
            ai_answer: '示例回答摘要',
            checked_at: '2026-07-30T10:00:00Z',
          },
        ],
      },
    })),
    stats: vi.fn(() => Promise.resolve({ data: {} })),
    // ClientOverview onMounted 还会调 workReport / visibility，补充 mock 避免报错
    workReport: vi.fn(() => Promise.resolve({ data: { summary: {}, items: [] } })),
    visibility: vi.fn(() => Promise.resolve({ data: { overall_score: 0, platform_scores: [], radar_data: { labels: [], values: [] } } })),
  },
}))

// mock clientQuestionApi.listOwn（任务 2 已实现）
vi.mock('@/api/clientQuestion', () => ({
  clientQuestionApi: {
    listOwn: vi.fn(() => Promise.resolve({
      data: [
        { id: 'q1', question: '监测问题1', sort_order: 0, status: 'active' },
      ],
    })),
  },
}))

import ClientOverview from '@/views/client/ClientOverview.vue'
import ClientEvidence from '@/views/client/ClientEvidence.vue'
import ClientArticles from '@/views/client/ClientArticles.vue'
import ClientSettings from '@/views/client/ClientSettings.vue'
import ClientLayout from '@/components/ClientLayout.vue'
import { clientViewApi } from '@/api/clientView'
import { clientQuestionApi } from '@/api/clientQuestion'

// 自定义 stub：el-table 直接迭代 data 把每行 stringify 成文本，便于断言行内容
const stubs = {
  'el-card': { name: 'ElCard', template: '<div class="el-card-stub"><slot /></div>' },
  'el-table': {
    name: 'ElTable',
    props: ['data'],
    template: `
      <div class="el-table-stub">
        <div v-for="(row, i) in (data || [])" :key="i" class="el-table-row">
          <slot :row="row" />
          <span class="el-table-row-text">{{ JSON.stringify(row) }}</span>
        </div>
      </div>
    `,
  },
  'el-table-column': {
    name: 'ElTableColumn',
    props: ['prop', 'label'],
    template: '<div class="el-table-column-stub"><slot :row="{}" /></div>',
  },
  'el-tag': {
    name: 'ElTag',
    props: ['type'],
    template: '<span class="el-tag-stub"><slot /></span>',
  },
  'el-button': {
    name: 'ElButton',
    props: ['type'],
    template: '<button class="el-button-stub"><slot /></button>',
  },
  'el-input': {
    name: 'ElInput',
    props: ['modelValue', 'placeholder', 'type'],
    emits: ['update:modelValue'],
    template: '<input class="el-input-stub" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-select': {
    name: 'ElSelect',
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: '<select class="el-select-stub"><slot /></select>',
  },
  'el-option': { name: 'ElOption', props: ['label', 'value'], template: '<option class="el-option-stub" />' },
  'el-form': { name: 'ElForm', template: '<form class="el-form-stub"><slot /></form>' },
  'el-form-item': { name: 'ElFormItem', props: ['label'], template: '<div class="el-form-item-stub"><span class="el-form-item-label">{{ label }}</span><slot /></div>' },
  'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
  // el-progress 默认插槽传递 percentage，组件模板用 <template #default="{ percentage }"> 解构
  'el-progress': {
    name: 'ElProgress',
    props: ['percentage', 'type', 'width', 'strokeWidth', 'color', 'showText'],
    template: '<div class="el-progress-stub"><slot :percentage="percentage" /></div>',
  },
}

const directives = {
  loading: { mounted() {}, updated() {}, unmounted() {} },
}

const mountOptions = () => ({ global: { stubs, directives } })

// 为 ClientLayout 提供最小化的 router + store（其 useRoute/useRouter/useStore 需要注入）
function buildClientRouterStore() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/client/overview', component: { template: '<div/>' } },
      { path: '/client/evidence', component: { template: '<div/>' } },
      { path: '/client/rankings', component: { template: '<div/>' } },
      { path: '/client/articles', component: { template: '<div/>' } },
      { path: '/client/settings', component: { template: '<div/>' } },
      { path: '/login', component: { template: '<div/>' } },
    ],
  })
  const store = createStore({
    state: { role: 'client', token: 't', user: null },
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

describe('ClientOverview', () => {
  it('加载 overview 并渲染统计 + 文章列表', async () => {
    wrapper = mount(ClientOverview, mountOptions())
    await flushPromises()
    expect(clientViewApi.overview).toHaveBeenCalled()
    // 收录率 0.5 → 50%
    expect(wrapper.text()).toContain('50%')
    // 文章列表包含 articles[0].title
    expect(wrapper.text()).toContain('文章A')
  })

  it('渲染 3 个统计卡片（已收录/未收录/收录率）', async () => {
    wrapper = mount(ClientOverview, mountOptions())
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('已收录')
    expect(text).toContain('未收录')
    expect(text).toContain('收录率')
    // 数值：indexed_urls.length=1, not_indexed_urls.length=1
    expect(text).toContain('1')
  })

  it('文章列表展示 url + title + model', async () => {
    wrapper = mount(ClientOverview, mountOptions())
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('https://x.com')
    expect(text).toContain('文章A')
    expect(text).toContain('doubao')
  })
})

describe('ClientEvidence', () => {
  it('加载 evidence 并渲染证据列表', async () => {
    wrapper = mount(ClientEvidence, mountOptions())
    await flushPromises()
    expect(clientViewApi.evidence).toHaveBeenCalled()
    // 证据项文本：文章标题 + URL + 模型 + 问题 + 命中类型
    const text = wrapper.text()
    expect(text).toContain('文章A')
    expect(text).toContain('https://x.com')
    expect(text).toContain('doubao')
    expect(text).toContain('示例问题?')
  })

  it('展示 hit_type 筛选下拉', async () => {
    wrapper = mount(ClientEvidence, mountOptions())
    await flushPromises()
    // 筛选标签存在
    const text = wrapper.text()
    expect(text).toContain('命中类型')
  })
})

describe('ClientArticles', () => {
  it('加载监测问题集 + 文章收录情况', async () => {
    wrapper = mount(ClientArticles, mountOptions())
    await flushPromises()
    expect(clientQuestionApi.listOwn).toHaveBeenCalled()
    expect(clientViewApi.overview).toHaveBeenCalled()
    const text = wrapper.text()
    // 监测问题（只读）
    expect(text).toContain('监测问题1')
    // 文章收录情况
    expect(text).toContain('文章A')
  })
})

describe('ClientSettings', () => {
  it('展示账户信息 + 修改密码表单', async () => {
    localStorage.setItem('client_id', 'DEMO001')
    localStorage.setItem('user_name', 'clientuser')
    wrapper = mount(ClientSettings, mountOptions())
    await flushPromises()
    const text = wrapper.text()
    // 账户信息
    expect(text).toContain('DEMO001')
    expect(text).toContain('clientuser')
    // 修改密码表单
    expect(text).toContain('修改密码')
    expect(text).toContain('新密码')
    expect(text).toContain('确认密码')
    localStorage.removeItem('client_id')
    localStorage.removeItem('user_name')
  })
})

describe('ClientLayout', () => {
  it('渲染客户端导航入口（概览/证据/文章/设置）', async () => {
    const { router, store } = buildClientRouterStore()
    await router.push('/client/overview')
    await router.isReady()
    wrapper = mount(ClientLayout, {
      global: {
        plugins: [router, store],
        stubs: {
          'router-view': true,
          'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
        },
      },
    })
    const text = wrapper.text()
    expect(text).toContain('概览')
    expect(text).toContain('引用证据')
    expect(text).toContain('我的文章')
    expect(text).toContain('设置')
    expect(text).toContain('退出登录')
  })

  it('不显示管理员专属入口', async () => {
    const { router, store } = buildClientRouterStore()
    await router.push('/client/overview')
    await router.isReady()
    wrapper = mount(ClientLayout, {
      global: {
        plugins: [router, store],
        stubs: {
          'router-view': true,
          'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
        },
      },
    })
    const text = wrapper.text()
    // 不应包含管理员专属菜单
    expect(text).not.toContain('客户管理')
    expect(text).not.toContain('审计日志')
    expect(text).not.toContain('AI 收录检测')
    expect(text).not.toContain('系统设置')
  })
})
