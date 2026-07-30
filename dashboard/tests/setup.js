import { config } from '@vue/test-utils'
// 全局 mock Element Plus 组件，避免测试时注册完整库
config.global.mocks = {}
