<template>
  <div class="login-container">
    <!-- 左侧品牌区 -->
    <div class="brand-section">
      <div class="brand-content">
        <h1 class="brand-title">知氪AI</h1>
        <h2 class="brand-subtitle">全链路监测平台</h2>
        <p class="brand-desc">
          实时追踪文章收录状态<br>
          AI 采信检测 · 多维度数据分析<br>
          专业级监测报告导出
        </p>
      </div>
    </div>

    <!-- 右侧表单区 -->
    <div class="form-section">
      <div class="form-card">
        <h3 class="form-title">{{ activeTab === 'client' ? '客户登录' : '管理员登录' }}</h3>

        <el-tabs v-model="activeTab" class="login-tabs">
          <el-tab-pane label="客户登录" name="client">
            <el-form :model="clientForm" @submit.prevent="handleClientLogin">
              <el-form-item>
                <el-input v-model="clientForm.client_id" placeholder="客户 ID" prefix-icon="User" />
              </el-form-item>
              <el-form-item>
                <el-input v-model="clientForm.password" type="password" placeholder="密码" prefix-icon="Lock" show-password />
              </el-form-item>
              <el-button type="primary" :loading="loading" @click="handleClientLogin" class="login-btn">
                登录
              </el-button>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="管理员登录" name="admin">
            <div class="sso-login-section">
              <p class="sso-desc">管理员通过 GEOFlow 单点登录（SSO）</p>
              <el-button type="primary" @click="handleSsoLogin" class="login-btn">
                <el-icon><Link /></el-icon>
                GEOFlow SSO 登录
              </el-button>
            </div>
          </el-tab-pane>
        </el-tabs>

        <div class="form-footer">
          <a href="/legal/terms" target="_blank">用户协议</a>
          <span class="divider">|</span>
          <a href="/legal/privacy" target="_blank">隐私政策</a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import { Link } from '@element-plus/icons-vue'

const router = useRouter()
const store = useStore()
const activeTab = ref('client')
const loading = ref(false)

const clientForm = reactive({
  client_id: '',
  password: '',
})

// D12 修复：通过 store.dispatch('login', ...) 调用 Vuex login action
// store action 内部用 api.post('/auth/login', credentials) 透传 { client_id, password }
// 并 commit SET_TOKEN + SET_ROLE，保持 store 作为认证状态单一来源
async function handleClientLogin() {
  if (!clientForm.client_id || !clientForm.password) {
    ElMessage.warning('请输入客户 ID 和密码')
    return
  }
  loading.value = true
  try {
    await store.dispatch('login', {
      client_id: clientForm.client_id,
      password: clientForm.password,
    })
    // client_id 供后续页面筛选数据使用；token/role 已由 store mutation 写入 localStorage
    localStorage.setItem('client_id', clientForm.client_id)
    router.push('/')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}

function handleSsoLogin() {
  // SSO 跳转：后端 /sso/login 会 307 重定向到 GEOFlow 授权页
  window.location.href = '/sso/login'
}
</script>

<style scoped>
.login-container {
  display: flex;
  min-height: 100vh;
  background: #f0f2f5;
}

.brand-section {
  flex: 1;
  background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.brand-content {
  text-align: center;
  padding: 40px;
}

.brand-title {
  font-size: 48px;
  font-weight: bold;
  margin-bottom: 10px;
}

.brand-subtitle {
  font-size: 24px;
  font-weight: 300;
  margin-bottom: 30px;
  opacity: 0.9;
}

.brand-desc {
  font-size: 16px;
  line-height: 2;
  opacity: 0.8;
}

.form-section {
  width: 450px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.form-card {
  width: 100%;
  max-width: 350px;
  padding: 40px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

.form-title {
  text-align: center;
  margin-bottom: 30px;
  color: #2c3e50;
}

.login-btn {
  width: 100%;
  margin-top: 10px;
}

.sso-login-section {
  text-align: center;
  padding: 20px 0;
}

.sso-desc {
  color: #666;
  margin-bottom: 20px;
  font-size: 14px;
}

.form-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 12px;
}

.form-footer a {
  color: #3498db;
  text-decoration: none;
}

.divider {
  margin: 0 10px;
  color: #ccc;
}

/* 响应式：手机端隐藏品牌区 */
@media (max-width: 768px) {
  .brand-section {
    display: none;
  }
  .form-section {
    width: 100%;
  }
  .form-card {
    max-width: 90%;
    padding: 20px;
  }
}
</style>
