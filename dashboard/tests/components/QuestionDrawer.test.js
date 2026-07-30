import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// mock clientQuestionApi（P3 已实现）
vi.mock('@/api/clientQuestion', () => ({
  clientQuestionApi: {
    list: vi.fn(() => Promise.resolve({
      data: [
        { id: 'q1', question: '问题1', sort_order: 0, status: 'active' },
        { id: 'q2', question: '问题2', sort_order: 1, status: 'active' },
      ],
    })),
    create: vi.fn(() => Promise.resolve({ data: { id: 'q3', question: '新问题', status: 'active' } })),
    update: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    reorder: vi.fn(() => Promise.resolve({})),
  },
}))

// mock element-plus 的服务式 API（ElMessageBox / ElMessage），避免 jsdom 渲染弹窗
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(() => Promise.resolve()) },
}))

import QuestionDrawer from '@/components/QuestionDrawer.vue'
import { clientQuestionApi } from '@/api/clientQuestion'
import { ElMessageBox } from 'element-plus'

// 自定义 stub：默认 stub 不渲染 slot 内容，这里显式渲染默认插槽以便断言文本/查找子元素
const stubs = {
  'el-drawer': { name: 'ElDrawer', template: '<div class="el-drawer-stub"><slot /></div>' },
  'el-button': {
    name: 'ElButton',
    props: ['type', 'size'],
    template: '<button class="el-button-stub"><slot /></button>',
  },
  'el-input': {
    name: 'ElInput',
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input class="el-input-stub" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-switch': {
    name: 'ElSwitch',
    props: ['modelValue', 'activeValue', 'inactiveValue'],
    emits: ['update:modelValue', 'change'],
    template: '<input type="checkbox" class="el-switch-stub" />',
  },
  'el-icon': { name: 'ElIcon', template: '<i class="el-icon-stub"><slot /></i>' },
}

// v-loading 指令由 Element Plus 注册，测试环境无注册，提供一个空 stub 避免告警
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

describe('QuestionDrawer', () => {
  it('打开时加载问题列表', async () => {
    wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      ...mountOptions(),
    })
    await flushPromises()
    expect(clientQuestionApi.list).toHaveBeenCalledWith('DEMO001')
    expect(wrapper.text()).toContain('问题1')
    expect(wrapper.text()).toContain('问题2')
  })

  it('输入新问题并添加 → 调用 create', async () => {
    wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      ...mountOptions(),
    })
    await flushPromises()
    await wrapper.find('.new-question-input').setValue('新问题')
    await wrapper.find('.add-question-btn').trigger('click')
    await flushPromises()
    expect(clientQuestionApi.create).toHaveBeenCalledWith('DEMO001', { question: '新问题' })
  })

  it('删除问题 → 调用 delete', async () => {
    wrapper = mount(QuestionDrawer, {
      props: { modelValue: true, clientId: 'DEMO001' },
      ...mountOptions(),
    })
    await flushPromises()
    await wrapper.find('.delete-btn').trigger('click')
    await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(clientQuestionApi.delete).toHaveBeenCalledWith('DEMO001', 'q1')
  })
})
