import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// mock echarts：jsdom 无真实 canvas，ECharts.init 会抛 "Cannot set properties of null (setting 'dpr')"
vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}))

// mock element-plus 的服务式 API，避免 ElMessage 在 jsdom 弹窗
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

// mock aiIndexApi（任务 2 已实现）
vi.mock('@/api/aiIndex', () => ({
  aiIndexApi: {
    getStats: vi.fn(() => Promise.resolve({
      data: {
        indexed: 5, not_indexed: 3, pending: 2, rate: 0.625,
        by_model: [{ model: 'doubao', indexed: 3, not_indexed: 1, pending: 0 }],
        by_client: [{ client_id: 'DEMO001', indexed: 5, not_indexed: 3, pending: 2, rate: 0.625 }],
      },
    })),
    listResults: vi.fn(() => Promise.resolve({
      data: {
        items: [{ url: 'https://x.com', model: 'doubao', index_status: 'indexed', checked_at: '2026-07-30T10:00:00Z' }],
        page: 1, page_size: 20,
      },
    })),
  },
}))

import AiIndex from '@/views/AiIndex.vue'
import { aiIndexApi } from '@/api/aiIndex'

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
    // 传一个空对象 row，避免用户模板 #default="{ row }" 解构出 undefined 后访问 row.xxx 报错
    template: '<div class="el-table-column-stub"><slot :row="{}" /></div>',
  },
  'el-pagination': { name: 'ElPagination', template: '<div class="el-pagination-stub" />' },
  'el-input': {
    name: 'ElInput',
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input class="el-input-stub" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-select': {
    name: 'ElSelect',
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: '<select class="el-select-stub"><slot /></select>',
  },
  'el-option': { name: 'ElOption', template: '<option class="el-option-stub" />' },
  'el-button': {
    name: 'ElButton',
    template: '<button class="el-button-stub"><slot /></button>',
  },
  'el-tag': {
    name: 'ElTag',
    props: ['type'],
    template: '<span class="el-tag-stub"><slot /></span>',
  },
  'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
}

const directives = {
  loading: { mounted() {}, updated() {}, unmounted() {} },
}

const mountOptions = () => ({ global: { stubs, directives } })

let wrapper
beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
})

describe('AiIndex', () => {
  it('加载统计与结果', async () => {
    wrapper = mount(AiIndex, mountOptions())
    await flushPromises()
    expect(aiIndexApi.getStats).toHaveBeenCalled()
    expect(aiIndexApi.listResults).toHaveBeenCalled()
    // 收录率 0.625 → 62.5%
    expect(wrapper.text()).toContain('62.5%')
  })

  it('渲染 4 个统计卡片（收录率/已收录/未收录/待检测）', async () => {
    wrapper = mount(AiIndex, mountOptions())
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('已收录')
    expect(text).toContain('未收录')
    expect(text).toContain('待检测')
    // 数值
    expect(text).toContain('5')
    expect(text).toContain('3')
    expect(text).toContain('2')
  })

  it('渲染 by_client 表格与结果列表', async () => {
    wrapper = mount(AiIndex, mountOptions())
    await flushPromises()
    // by_client 表格出现 client_id
    expect(wrapper.text()).toContain('DEMO001')
    // 结果列表出现 url
    expect(wrapper.text()).toContain('https://x.com')
  })

  it('调用 listResults 时传入分页参数', async () => {
    wrapper = mount(AiIndex, mountOptions())
    await flushPromises()
    expect(aiIndexApi.listResults).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 20 }),
    )
  })
})
