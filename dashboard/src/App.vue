<template>
  <div class="app-container">
    <div v-if="showNav" class="nav-bar">
      <div class="logo">知氪AI全链路监测平台</div>
      <el-menu :default-active="activeMenu" mode="horizontal" router class="nav-menu">
        <el-menu-item index="/"><el-icon><DataLine /></el-icon>仪表盘</el-menu-item>
        <el-menu-item index="/articles"><el-icon><Document /></el-icon>文章列表</el-menu-item>
        <el-menu-item index="/distributions"><el-icon><Share /></el-icon>分发记录</el-menu-item>
        <el-menu-item index="/exports"><el-icon><Download /></el-icon>导出报告</el-menu-item>
        <el-menu-item index="/clients" v-if="isAdmin"><el-icon><User /></el-icon>客户管理</el-menu-item>
        <el-menu-item index="/audit-logs" v-if="isAdmin"><el-icon><List /></el-icon>审计日志</el-menu-item>
        <el-menu-item index="/settings" v-if="isAdmin"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
      <!-- GEOFlow 后台：外链（仅 admin 可见），用 a 标签 target=_blank 新窗口打开 -->
      <a v-if="isAdmin" href="https://zkeeeai.com/geo_admin" target="_blank" rel="noopener" class="external-link">
        <el-icon><Link /></el-icon>GEOFlow 后台
      </a>
      <el-button text type="primary" @click="logout">退出登录</el-button>
    </div>
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataLine, Document, Share, Download, List, Setting, Link, User } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

// 仅在非登录页显示导航栏
const showNav = computed(() => route.path !== '/login')
// 当前激活的菜单项（基于路由路径）
const activeMenu = computed(() => route.path)
// 仅 admin 可见审计日志菜单项
const isAdmin = computed(() => localStorage.getItem('role') === 'admin')

// 退出登录：清除 token / role / client_id 并跳转登录页
const logout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('role')
  localStorage.removeItem('client_id')
  router.push('/login')
}
</script>

<style>
.app-container { min-height: 100vh; }
.nav-bar {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
  background: #fff;
}
.logo {
  font-size: 18px;
  font-weight: bold;
  color: #409eff;
  margin-right: 30px;
  white-space: nowrap;
}
.nav-menu {
  flex: 1;
  border-bottom: none !important;
}
/* 外链按钮样式：与 el-menu-item 视觉一致，避免被 vue-router 当作路由导航 */
.external-link {
  display: flex;
  align-items: center;
  padding: 0 20px;
  text-decoration: none;
  color: #606266;
  font-size: 14px;
  height: 60px;
  border-bottom: 2px solid transparent;
  transition: border-color 0.2s, color 0.2s;
  white-space: nowrap;
}
.external-link:hover {
  color: #409eff;
  border-bottom-color: #409eff;
}
.external-link .el-icon {
  margin-right: 6px;
}
</style>
