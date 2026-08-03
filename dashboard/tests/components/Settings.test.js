import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// mock element-plus 的服务式 API（ElMessage），避免 jsdom 弹窗
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

// mock @/api：覆盖 Settings.vue 的 /config 加载 + useScanTrigger 的 /admin/scan/trigger
vi.mock('@/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({
      data: { task_ids: { index: 't1' }, message: '已触发 index 扫描' },
    })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
  },
}))

import Settings from '@/views/Settings.vue'
import api from '@/api'
import { ElMessage } from 'element-plus'

// 自定义 stub：渲染默认插槽以便断言按钮文本；data-* 暴露 props 便于断言绑定
const stubs = {
  'el-card': { name: 'ElCard', template: '<div class="el-card-stub"><slot /></div>' },
  'el-form': { name: 'ElForm', template: '<form class="el-form-stub"><slot /></form>' },
  'el-form-item': {
    name: 'ElFormItem',
    props: ['label'],
    template: '<div class="el-form-item-stub"><slot /></div>',
  },
  'el-input-number': { name: 'ElInputNumber', template: '<input class="el-input-number-stub" />' },
  'el-input': {
    name: 'ElInput',
    props: ['modelValue', 'placeholder', 'showPassword'],
    emits: ['update:modelValue'],
    template: '<input class="el-input-stub" />',
  },
  'el-checkbox-group': {
    name: 'ElCheckboxGroup',
    props: ['modelValue'],
    template: '<div class="el-checkbox-group-stub"><slot /></div>',
  },
  'el-checkbox': { name: 'ElCheckbox', props: ['label'], template: '<label class="el-checkbox-stub"><slot /></label>' },
  'el-tag': { name: 'ElTag', props: ['size', 'type', 'effect'], template: '<span class="el-tag-stub"><slot /></span>' },
  'el-alert': { name: 'ElAlert', template: '<div class="el-alert-stub"><slot /></div>' },
  'el-button': {
    name: 'ElButton',
    props: ['type'],
    template: '<button class="el-button-stub" :data-type="type"><slot /></button>',
  },
  'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
  // 扫描按钮已包裹在 el-tooltip 中，需 stub 以渲染按钮内容
  'el-tooltip': { name: 'ElTooltip', props: ['content', 'placement', 'effect'], template: '<div class="el-tooltip-stub"><slot /></div>' },
  'el-collapse-transition': {
    name: 'ElCollapseTransition',
    template: '<div class="el-collapse-transition-stub"><slot /></div>',
  },
  // ScanPanel stub：把 taskId / taskIds props 写到 data-* 属性便于断言绑定
  ScanPanel: {
    name: 'ScanPanel',
    props: ['modelValue', 'taskId', 'taskIds'],
    template: '<div class="scan-panel-stub" :data-task-id="taskId" :data-has-task-ids="taskIds ? \'yes\' : \'no\'" />',
  },
}

const mountOptions = () => ({ global: { stubs } })

let wrapper
beforeEach(() => vi.clearAllMocks())
afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
})

describe('Settings.vue 扫描触发（I1+I3+I4）', () => {
  it('渲染 4 个扫描按钮：收录/AI 采信/AI 收录/全量', async () => {
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const buttons = wrapper.findAll('.el-button-stub').map(b => b.text())
    expect(buttons).toContain('① 搜索引擎收录检测')
    expect(buttons).toContain('③ AI 引用检测')
    expect(buttons).toContain('② AI 收录检测')
    expect(buttons).toContain('④ 全量检测（三合一）')
  })

  it('点击"立即收录扫描"调 /admin/scan/trigger scan_type=index', async () => {
    api.post.mockResolvedValueOnce({
      data: { task_ids: { index: 't-idx' }, message: '已触发 index 扫描' },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '① 搜索引擎收录检测')
    await btn.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'index' })
    // 不应再调用已废弃的路径参数式端点
    expect(api.post).not.toHaveBeenCalledWith('/scan/trigger/index', expect.anything())
  })

  it('点击"立即 AI 采信扫描"调 /admin/scan/trigger scan_type=citation', async () => {
    api.post.mockResolvedValueOnce({
      data: { task_ids: { citation: 't-cit' }, message: '已触发 citation 扫描' },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '③ AI 引用检测')
    await btn.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'citation' })
  })

  it('点击"AI 收录扫描"调 /admin/scan/trigger scan_type=ai_index（I3 新增按钮）', async () => {
    api.post.mockResolvedValueOnce({
      data: { task_ids: { ai_index: 't-ai' }, message: '已触发 ai_index 扫描' },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '② AI 收录检测')
    await btn.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'ai_index' })
    // 成功提示
    expect(ElMessage.success).toHaveBeenCalled()
  })

  it('点击"全量扫描"调 /admin/scan/trigger scan_type=all（I3 新增按钮）', async () => {
    api.post.mockResolvedValueOnce({
      data: {
        task_ids: { index: 't1', ai_index: 't2', citation: 't3' },
        message: '已触发 all 扫描',
      },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '④ 全量检测（三合一）')
    await btn.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/admin/scan/trigger', { scan_type: 'all' })
  })

  it('全量扫描后 ScanPanel 收到 task-id 与 task-ids 绑定（I1+I2）', async () => {
    api.post.mockResolvedValueOnce({
      data: {
        task_ids: { index: 't1', ai_index: 't2', citation: 't3' },
        message: '已触发 all 扫描',
      },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '④ 全量检测（三合一）')
    await btn.trigger('click')
    await flushPromises()
    const panel = wrapper.find('.scan-panel-stub')
    expect(panel.exists()).toBe(true)
    // currentTaskId = task_ids.index
    expect(panel.attributes('data-task-id')).toBe('t1')
    // taskIds = 完整 dict，驱动三阶段进度环
    expect(panel.attributes('data-has-task-ids')).toBe('yes')
  })

  it('单类型扫描后 ScanPanel 收到 task-id 但 task-ids 为 null', async () => {
    api.post.mockResolvedValueOnce({
      data: { task_ids: { index: 't-idx' }, message: '已触发 index 扫描' },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '① 搜索引擎收录检测')
    await btn.trigger('click')
    await flushPromises()
    const panel = wrapper.find('.scan-panel-stub')
    expect(panel.attributes('data-task-id')).toBe('t-idx')
    expect(panel.attributes('data-has-task-ids')).toBe('no')
  })

  it('扫描触发失败时显示错误提示（不抛错）', async () => {
    api.post.mockRejectedValueOnce({
      response: { data: { detail: '已有扫描在运行' } },
    })
    wrapper = mount(Settings, mountOptions())
    await flushPromises()
    const btn = wrapper.findAll('.el-button-stub').find(b => b.text() === '① 搜索引擎收录检测')
    await btn.trigger('click')
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('已有扫描在运行')
  })
})
