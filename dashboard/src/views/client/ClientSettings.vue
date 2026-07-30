<template>
  <div class="client-settings">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>设置</h2>
      <p class="page-subtitle">账户信息与密码修改</p>
    </div>

    <!-- 账户信息（只读） -->
    <el-card class="section-card" shadow="never">
      <h3>账户信息</h3>
      <div class="info-grid">
        <div class="info-item">
          <span class="info-label">客户 ID</span>
          <span class="info-value mono">{{ clientId || '—' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">用户名</span>
          <span class="info-value">{{ userName || '—' }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">角色</span>
          <span class="info-value">客户端</span>
        </div>
      </div>
    </el-card>

    <!-- 修改密码 -->
    <el-card class="section-card" shadow="never">
      <h3>修改密码</h3>
      <el-form :model="form" label-width="100px" class="password-form">
        <el-form-item label="新密码">
          <el-input
            v-model="form.new_password"
            type="password"
            placeholder="请输入新密码"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="form.confirm_password"
            type="password"
            placeholder="请再次输入新密码"
            show-password
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submitPassword">提交修改</el-button>
        </el-form-item>
      </el-form>
      <div v-if="fallbackTip" class="fallback-tip">{{ fallbackTip }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const clientId = ref('')
const userName = ref('')
const submitting = ref(false)
const fallbackTip = ref('')

const form = reactive({
  new_password: '',
  confirm_password: '',
})

onMounted(() => {
  clientId.value = localStorage.getItem('client_id') || ''
  userName.value = localStorage.getItem('user_name') || ''
})

async function submitPassword() {
  fallbackTip.value = ''
  if (!form.new_password) {
    ElMessage.warning('请输入新密码')
    return
  }
  if (form.new_password.length < 6) {
    ElMessage.warning('密码长度至少 6 位')
    return
  }
  if (form.new_password !== form.confirm_password) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }

  submitting.value = true
  try {
    // 优先尝试调用 /auth/change-password；后端若无此端点则降级提示
    await api.put('/auth/change-password', { new_password: form.new_password })
    ElMessage.success('密码修改成功，请重新登录')
    form.new_password = ''
    form.confirm_password = ''
  } catch (err) {
    const status = err?.response?.status
    if (status === 404) {
      // 端点不存在：降级提示
      fallbackTip.value = '当前系统未开放在线修改密码，请联系管理员修改密码'
      ElMessage.warning('请联系管理员修改密码')
    } else {
      console.error('修改密码失败', err)
      ElMessage.error(err?.response?.data?.detail || '修改密码失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.client-settings {
  padding: var(--space-md) var(--space-lg) var(--space-lg);
  max-width: 880px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-lg);
}
.page-header h2 {
  margin: 0;
  font-size: var(--fs-h1);
  color: var(--ink);
  letter-spacing: -0.02em;
}
.page-subtitle {
  margin: 4px 0 0;
  color: var(--mute);
  font-size: var(--fs-small);
}

.section-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-md);
}

.section-card h3 {
  margin: 0 0 var(--space-md) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.section-card h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 20px;
  background: var(--grad-brand);
  border-radius: var(--radius-pill);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-md);
}
.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.info-label {
  font-size: var(--fs-small);
  color: var(--mute);
}
.info-value {
  font-size: var(--fs-body);
  color: var(--ink);
  font-weight: 500;
  word-break: break-all;
}

.password-form {
  max-width: 480px;
}

.fallback-tip {
  margin-top: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--signal-soft);
  border-radius: var(--radius-md);
  color: var(--signal);
  font-size: var(--fs-small);
}

@media (max-width: 768px) {
  .client-settings { padding: var(--space-sm); }
  .password-form { max-width: 100%; }
}
</style>
