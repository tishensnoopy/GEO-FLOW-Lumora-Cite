import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
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

let wrapper
beforeEach(() => vi.clearAllMocks())
// I2 修复：每个用例结束后 unmount 组件，触发 onUnmounted 清理 setInterval，
// 防止 phasePollTimers / pollTimer 跨用例泄漏污染后续断言
afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
})

describe('ScanPanel', () => {
  it('all 类型展示三阶段进度环', async () => {
    wrapper = mount(ScanPanel, {
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
    wrapper = mount(ScanPanel, {
      props: { modelValue: true, taskId: 't1', taskIds: null },
      ...mountOptions(),
    })
    expect(wrapper.find('.phase-rings').exists()).toBe(false)
    expect(wrapper.findAll('.phase-ring').length).toBe(0)
  })

  // S2 新增：failed 阶段显示 ✗ 并加 .failed 红色样式（联动 I1）
  it('failed 阶段显示 ✗ 并加 .failed 红色样式', async () => {
    api.get.mockImplementation(() => Promise.resolve({
      data: {
        task_id: 't1', scan_type: 'all', status: 'failed',
        total: 10, processed: 3, success: 2, failed: 0,
        logs: [], citation_models: [],
      },
    }))
    wrapper = mount(ScanPanel, {
      props: {
        modelValue: false,
        taskId: 'main-0',
        taskIds: { index: 'idx-1', ai_index: 'ai-2', citation: 'cit-3' },
      },
      ...mountOptions(),
    })
    // 触发 modelValue watch（false → true）→ startPhasePolling → 各 phase fetchPhaseStatus
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    // 三个阶段均映射为 failed（红 ✗），不再被误映射为 completed（绿 ✓）
    expect(wrapper.findAll('.phase-ring.failed').length).toBe(3)
    expect(wrapper.findAll('.phase-ring.completed').length).toBe(0)
    expect(wrapper.text()).toContain('✗')
  })

  // S2 新增：active 阶段高亮
  it('active 阶段加 .active 高亮样式', async () => {
    api.get.mockImplementation(() => Promise.resolve({
      data: {
        task_id: 't1', scan_type: 'all', status: 'running',
        total: 10, processed: 3, success: 2, failed: 0,
        logs: [], citation_models: [],
      },
    }))
    wrapper = mount(ScanPanel, {
      props: {
        modelValue: false,
        taskId: 'main-0',
        taskIds: { index: 'idx-1', ai_index: 'ai-2', citation: 'cit-3' },
      },
      ...mountOptions(),
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    expect(wrapper.findAll('.phase-ring.active').length).toBe(3)
  })

  // S2 新增：三阶段轮询启动时各 phase 的 api.get 各调用 1 次
  it('三阶段轮询启动时各 phase 的 api.get 各调用 1 次', async () => {
    api.get.mockImplementation(() => Promise.resolve({
      data: {
        task_id: 't1', scan_type: 'all', status: 'running',
        total: 0, processed: 0, success: 0, failed: 0,
        logs: [], citation_models: [],
      },
    }))
    wrapper = mount(ScanPanel, {
      props: {
        modelValue: false,
        taskId: 'main-0',
        taskIds: { index: 'idx-1', ai_index: 'ai-2', citation: 'cit-3' },
      },
      ...mountOptions(),
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    const urls = api.get.mock.calls.map(c => c[0])
    // 每个 phase task 各被轮询 1 次（共 3 次，对应 3 个独立 setInterval）
    expect(urls.filter(u => u === '/admin/scan/status/idx-1').length).toBe(1)
    expect(urls.filter(u => u === '/admin/scan/status/ai-2').length).toBe(1)
    expect(urls.filter(u => u === '/admin/scan/status/cit-3').length).toBe(1)
  })
})
