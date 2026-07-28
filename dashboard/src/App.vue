<template>
  <div class="app-container">
    <div v-if="showNav" class="nav-bar">
      <div class="logo">知<span class="accent">氪</span>AI 全链路监测平台</div>
      <el-menu :default-active="activeMenu" mode="horizontal" router class="nav-menu">
        <el-menu-item index="/"><el-icon><DataLine /></el-icon>仪表盘</el-menu-item>
        <el-menu-item index="/articles"><el-icon><Document /></el-icon>文章列表</el-menu-item>
        <el-menu-item index="/distributions"><el-icon><Share /></el-icon>分发记录</el-menu-item>
        <el-menu-item index="/exports"><el-icon><Download /></el-icon>导出报告</el-menu-item>
        <el-menu-item index="/clients" v-if="isAdmin"><el-icon><User /></el-icon>客户管理</el-menu-item>
        <el-menu-item index="/audit-logs" v-if="isAdmin"><el-icon><List /></el-icon>审计日志</el-menu-item>
        <el-menu-item index="/settings" v-if="isAdmin"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
      <!-- GEOFlow 后台：仅 admin 可见，点击后在新标签页打开 GEOFlow 后台 -->
      <a v-if="isAdmin"
         href="https://zkeeeai.com/geo_admin"
         target="_blank"
         rel="noopener"
         class="external-link"
         @click="handleGeoFlowClick">
        <el-icon><Link /></el-icon>GEOFlow 后台
      </a>
      <el-button text type="primary" @click="logout">退出登录</el-button>
    </div>
    <router-view />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import { DataLine, Document, Share, Download, List, Setting, Link, User } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const store = useStore()

// 仅在非登录页显示导航栏
const showNav = computed(() => route.path !== '/login')
// 当前激活的菜单项（基于路由路径）
const activeMenu = computed(() => route.path)
// 修复：改用 Vuex store 的响应式 role，而非直接读 localStorage
// localStorage 不是 Vue 响应式数据源，computed 求值一次后永久缓存
// App.vue 作为根组件永不卸载，导致退出登录后 isAdmin 不更新
const isAdmin = computed(() => store.state.role === 'admin')

// GEOFlow 后台跳转提示：点击后提示用户正在打开新窗口
const handleGeoFlowClick = () => {
  ElMessage({
    message: '正在打开 GEOFlow 后台，如需登录请使用管理员账号',
    type: 'info',
    duration: 3000
  })
}

// 退出登录：清除 token / role / client_id / user_name 并跳转登录页
// 修复：调用 Vuex logout action 清理 store 状态（响应式），并补清 user_name
const logout = () => {
  store.dispatch('logout')  // 清 Vuex state.token/role + localStorage.token/role
  localStorage.removeItem('client_id')
  localStorage.removeItem('user_name')  // 补清 SSO 写入的 user_name
  router.push('/login')
}
</script>

<style>
.app-container { min-height: 100vh; background: var(--paper); }

.nav-bar {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  padding: 0 var(--space-lg);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: 100;
}

/* Logo：衬线体 + "氪"字 signal 高亮（标志性元素） */
.logo {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  margin-right: var(--space-md);
  white-space: nowrap;
  letter-spacing: 0.02em;
}
.logo .accent {
  color: var(--signal);
}

.nav-menu {
  flex: 1;
  border-bottom: none !important;
  background: transparent !important;
}
/* 菜单项：减少默认 padding，更紧凑报告感 */
.nav-menu .el-menu-item {
  font-size: var(--fs-body);
  height: 56px;
  line-height: 56px;
}

/* 外链按钮：与 el-menu-item 视觉一致 */
.external-link {
  display: flex;
  align-items: center;
  padding: 0 var(--space-md);
  text-decoration: none;
  color: var(--mute);
  font-size: var(--fs-body);
  height: 56px;
  border-bottom: 2px solid transparent;
  transition: border-color 0.2s, color 0.2s;
  white-space: nowrap;
}
.external-link:hover {
  color: var(--signal);
  border-bottom-color: var(--signal);
}
.external-link .el-icon {
  margin-right: 6px;
}

/* 退出登录按钮：去强调，避免与 logo 抢眼 */
.nav-bar .el-button--text,
.nav-bar .el-button.is-text {
  color: var(--mute);
  font-size: var(--fs-body);
}
.nav-bar .el-button--text:hover,
.nav-bar .el-button.is-text:hover {
  color: var(--alert);
}
</style>
