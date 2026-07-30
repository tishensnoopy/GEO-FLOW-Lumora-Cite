// 路由守卫纯函数：从 router.beforeEach 提取，便于单元测试。
// 输入：to.path / to.meta / 角色 / token；输出：重定向路径字符串 或 null（放行）
// 注：startsWith('/client/') 带尾斜杠，避免误匹配 /clients（admin 路由）；
// 现有客户端路由均为 /client/overview 等带斜杠形式。
export function decideRoute({ path, meta, role, token }) {
  if (meta.requiresAuth && !token) return '/login'
  if (meta.requiresAdmin && role !== 'admin') return '/client/overview'
  if (path.startsWith('/client/') && role === 'admin' && !meta.allowAdminPreview) return '/'
  if (!path.startsWith('/client/') && meta.requiresAuth && role === 'client' && path !== '/login') return '/client/overview'
  return null  // 放行
}
