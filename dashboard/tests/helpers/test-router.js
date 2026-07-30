// 测试辅助：从守卫模块重新导出 decideRoute，供偏好 helpers 间接层的测试使用。
// 当前 router.test.js 直接 import '../../src/router/guard.js'，避免间接层。
export { decideRoute } from '../../src/router/guard.js'
