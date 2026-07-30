import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ScanPanel from '@/components/ScanPanel.vue'

// mock @/api，避免轮询触发真实网络请求
vi.mock('@/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({
      data: {
        task_id: 't1', scan_type: 'all', status: 'running',
        total: 0, processed: 0, success: 0, failed: 0,
        logs: [], citation_models: [],
      },
    })),
  },
}))

import api from '@/api'

// teleport 内容默认渲染到 document.body，stub 后内联渲染便于断言
const mountOptions = () => ({
  global: {
    stubs: { teleport: true },
  },
})

beforeEach(() => vi.clearAllMocks())

describe('ScanPanel', () => {
  it('all 类型展示三阶段进度环', async () => {
    const wrapper = mount(ScanPanel, {
      props: {
        modelValue: true,
        taskId: 't1',
        taskIds: { index: 't1', ai_index: 't2', citation: 't3' },
      },
      ...mountOptions(),
    })
    // .phase-rings 区域存在
    expect(wrapper.find('.phase-rings').exists()).toBe(true)
    // 三阶段标签存在
    expect(wrapper.text()).toContain('收录')
    expect(wrapper.text()).toContain('AI 收录')
    expect(wrapper.text()).toContain('采信')
    // 三个 .phase-ring 子元素
    expect(wrapper.findAll('.phase-ring').length).toBe(3)
  })

  it('单类型不展示三阶段', () => {
    const wrapper = mount(ScanPanel, {
      props: { modelValue: true, taskId: 't1', taskIds: null },
      ...mountOptions(),
    })
    expect(wrapper.find('.phase-rings').exists()).toBe(false)
    expect(wrapper.findAll('.phase-ring').length).toBe(0)
  })
})
