<template>
  <div class="app-container">
    <div v-if="showNav" class="nav-bar">
      <div class="logo">知氪AI全链路监测平台</div>
      <el-menu :default-active="activeMenu" mode="horizontal" router class="nav-menu">
        <el-menu-item index="/">仪表盘</el-menu-item>
        <el-menu-item index="/articles">文章列表</el-menu-item>
        <el-menu-item index="/exports">导出报告</el-menu-item>
        <el-menu-item index="/settings">系统设置</el-menu-item>
      </el-menu>
      <el-button text type="primary" @click="logout">退出登录</el-button>
    </div>
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

// 仅在非登录页显示导航栏
const showNav = computed(() => route.path !== '/login')
// 当前激活的菜单项（基于路由路径）
const activeMenu = computed(() => route.path)

// 退出登录：清除 token 并跳转登录页
const logout = () => {
  localStorage.removeItem('token')
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
</style>
