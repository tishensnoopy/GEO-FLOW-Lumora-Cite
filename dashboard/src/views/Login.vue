<template>
  <div class="login-container">
    <!-- 左侧：CSS-only 雷达脉冲动画（标志性元素） -->
    <div class="radar-section">
      <!-- 背景网格 -->
      <div class="radar-bg-grid"></div>

      <!-- 雷达主体 -->
      <div class="radar">
        <!-- 十字准线 -->
        <div class="radar-crosshair-h"></div>
        <div class="radar-crosshair-v"></div>

        <!-- 同心圆环（脉冲扩散） -->
        <div class="radar-ring r1"></div>
        <div class="radar-ring r2"></div>
        <div class="radar-ring r3"></div>
        <div class="radar-ring r4"></div>

        <!-- 扫描扇形（旋转） -->
        <div class="radar-sweep"></div>

        <!-- 信号光点（检测到的信号） -->
        <div class="radar-blip blip1"></div>
        <div class="radar-blip blip2"></div>
        <div class="radar-blip blip3"></div>

        <!-- 中心核 -->
        <div class="radar-core"></div>
      </div>

      <!-- 品牌叠加文字 -->
      <div class="radar-overlay">
        <div class="radar-brand mono">ZKEEE · AI</div>
        <div class="radar-tagline mono">CONTENT · INDEX · CITATION</div>
      </div>

      <!-- 底部状态标签 -->
      <div class="radar-caption">
        <span class="mono">SIGNAL · MONITORING</span>
      </div>
    </div>

    <!-- 右侧：登录表单（paper 背景，细线分隔，无白卡片） -->
    <div class="form-section">
      <div class="brand-header">
        <h1 class="brand-title">知<span class="accent">氪</span>AI</h1>
        <p class="brand-sub">全链路监测平台 · 内容收录与 AI 采信验证</p>
      </div>

      <div class="form-divider"></div>

      <h3 class="form-title">{{ activeTab === 'client' ? '客户登录' : '管理员登录' }}</h3>

      <el-tabs v-model="activeTab" class="login-tabs">
        <el-tab-pane label="客户登录" name="client">
          <el-form :model="clientForm" @submit.prevent="handleClientLogin">
            <el-form-item>
              <el-input v-model="clientForm.username" placeholder="用户名" prefix-icon="User" />
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

      <!-- 开发预览模式：无需后端即可预览 Dashboard 设计（仅 dev 环境显示） -->
      <div v-if="isDev" class="dev-preview">
        <div class="dev-preview-row">
          <button class="dev-preview-btn" @click="enterPreview('client')">客户预览 →</button>
          <button class="dev-preview-btn admin" @click="enterPreview('admin')">管理员预览 →</button>
        </div>
        <p class="dev-hint">跳过登录，直接预览（客户: testuser / 管理员: admin）</p>
        <p class="dev-hint">或直接登录：客户 testuser / Test@1234</p>
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
// 开发预览模式标记（仅 dev 环境显示预览按钮）
const isDev = import.meta.env.DEV

const clientForm = reactive({
  username: '',
  password: '',
})

// 开发预览：设置 token + role，跳转 Dashboard
// mode='client' 用假 token（Dashboard 显示 mock 数据）
// mode='admin' 用真实 admin JWT（可调 admin API，看真实数据）
//
// ADMIN_DEV_TOKEN 用后端 SSO_JWT_SECRET 签发，exp 设到 2027-12-31 避免频繁过期。
// 重新生成命令（在 index-monitor 容器内执行）：
//   python -c "import jwt; from datetime import datetime,timezone; from app.core.config import settings; \
//     print(jwt.encode({'sub':'1','role':'admin','type':'admin','name':'admin',\
//     'exp':datetime(2027,12,31,tzinfo=timezone.utc)}, settings.SSO_JWT_SECRET, algorithm='HS256'))"
// 注意：token 过期会导致走马灯无文字（/admin/distributions 401）+ admin API 全部失败，
// 表现为"批量删除不执行"等假性 bug。若 dev 预览模式异常，先检查此 token 是否过期。
const ADMIN_DEV_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6ImFkbWluIiwidHlwZSI6ImFkbWluIiwibmFtZSI6ImFkbWluIiwiZXhwIjoxODMwMjk3NTk5LCJpYXQiOjE3ODUzNTA0NTN9.PgNxobvz2UH5F0L1yn2W4P3AAecoRx9gfPGLwfHd0Y4'

function enterPreview(mode = 'client') {
  if (mode === 'admin') {
    localStorage.setItem('token', ADMIN_DEV_TOKEN)
    localStorage.setItem('role', 'admin')
    localStorage.setItem('user_name', 'admin')
    store.commit('SET_TOKEN', ADMIN_DEV_TOKEN)
    store.commit('SET_ROLE', 'admin')
  } else {
    localStorage.setItem('token', 'dev-preview-token')
    localStorage.setItem('role', 'client')
    store.commit('SET_TOKEN', 'dev-preview-token')
    store.commit('SET_ROLE', 'client')
  }
  router.push('/')
}

// 客户登录：用 username（或 client_id）登录，后端返回 client_id 供后续 API 筛选使用
async function handleClientLogin() {
  if (!clientForm.username || !clientForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await store.dispatch('login', {
      username: clientForm.username,
      password: clientForm.password,
    })
    // 后端返回 client_id，存到 localStorage 供后续 API 筛选使用
    if (data.client_id) {
      localStorage.setItem('client_id', data.client_id)
    }
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
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 100vh;
  background: var(--paper);
}

/* === 左侧雷达区 === */
.radar-section {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0F172A 0%, #1E1B4B 60%, #312E81 100%);
  overflow: hidden;
}
/* 背景网格：极淡 signal 色网格暗示"监测" */
.radar-bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(99, 102, 241, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(99, 102, 241, 0.07) 1px, transparent 1px);
  background-size: 40px 40px;
}
/* 径向渐变：中心微亮，边缘渐暗，增加深度 */
.radar-bg-grid::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center, rgba(99, 102, 241, 0.08) 0%, transparent 60%);
}

.radar {
  position: relative;
  width: 320px;
  height: 320px;
}

/* 十字准线：极淡 signal 色，辅助定位"监测" */
.radar-crosshair-h, .radar-crosshair-v {
  position: absolute;
  background: rgba(99, 102, 241, 0.12);
}
.radar-crosshair-h {
  top: 50%; left: 0; right: 0; height: 1px;
}
.radar-crosshair-v {
  left: 50%; top: 0; bottom: 0; width: 1px;
}

/* 同心圆环：从内到外逐层脉冲扩散 */
.radar-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  border: 1px solid var(--signal);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  opacity: 0;
  animation: radar-pulse 4s ease-out infinite;
}
.radar-ring.r1 { width: 60px;  height: 60px;  animation-delay: 0s; }
.radar-ring.r2 { width: 130px; height: 130px; animation-delay: 0.8s; }
.radar-ring.r3 { width: 210px; height: 210px; animation-delay: 1.6s; }
.radar-ring.r4 { width: 300px; height: 300px; animation-delay: 2.4s; }

@keyframes radar-pulse {
  0%   { opacity: 0.7; transform: translate(-50%, -50%) scale(0.5); }
  70%  { opacity: 0.1; }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1); }
}

/* 扫描扇形：亮前缘 + 渐隐尾迹，绕圆心旋转 */
.radar-sweep {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 300px;
  height: 300px;
  background: conic-gradient(
    from 0deg,
    rgba(99, 102, 241, 0.55) 0deg,
    rgba(99, 102, 241, 0.25) 12deg,
    rgba(99, 102, 241, 0.08) 50deg,
    transparent 90deg,
    transparent 360deg
  );
  border-radius: 50%;
  animation: radar-sweep-rotate 4s linear infinite;
}
@keyframes radar-sweep-rotate {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to   { transform: translate(-50%, -50%) rotate(360deg); }
}

/* 信号光点：模拟检测到的信号，周期性闪烁 */
.radar-blip {
  position: absolute;
  width: 6px;
  height: 6px;
  background: var(--signal);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--signal), 0 0 4px var(--signal);
  animation: blip-pulse 3s ease-in-out infinite;
}
.blip1 { top: 32%; left: 65%; animation-delay: 0.5s; }
.blip2 { top: 68%; left: 38%; animation-delay: 1.5s; }
.blip3 { top: 45%; left: 72%; animation-delay: 2.5s; }

@keyframes blip-pulse {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  20%      { opacity: 1; transform: scale(1.3); }
  60%      { opacity: 0.6; transform: scale(1); }
}

/* 中心核：signal 实心点 + 发光 */
.radar-core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 10px;
  height: 10px;
  background: var(--signal);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 12px var(--signal), 0 0 4px var(--signal);
}

/* 品牌叠加文字（左上角） */
.radar-overlay {
  position: absolute;
  top: var(--space-lg);
  left: var(--space-lg);
  z-index: 2;
}
.radar-brand {
  color: var(--signal);
  font-size: 14px;
  letter-spacing: 0.25em;
  font-weight: 500;
}
.radar-tagline {
  color: var(--mute);
  font-size: 11px;
  letter-spacing: 0.15em;
  margin-top: 4px;
  opacity: 0.7;
}

/* 底部状态标签 */
.radar-caption {
  position: absolute;
  bottom: var(--space-lg);
  left: 0;
  right: 0;
  text-align: center;
  color: var(--mute);
  letter-spacing: 0.3em;
  font-size: var(--fs-mono);
  z-index: 2;
}

/* === 右侧表单区 === */
.form-section {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: var(--space-xl) var(--space-xl);
  max-width: 520px;
  margin: 0 auto;
  width: 100%;
}

.brand-header { margin-bottom: var(--space-lg); }
.brand-title {
  font-family: var(--font-display);
  font-size: var(--fs-display);
  font-weight: 900;
  color: var(--ink);
  letter-spacing: -0.03em;
  line-height: 1;
}
/* "氪"字品牌渐变 */
.brand-title .accent {
  background: var(--grad-brand);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-sub {
  margin-top: var(--space-sm);
  color: var(--mute);
  font-size: var(--fs-body);
}

.form-divider {
  height: 1px;
  background: var(--ink-line);
  margin: var(--space-lg) 0;
}

.form-title {
  font-size: var(--fs-h2);
  margin-bottom: var(--space-md);
  color: var(--ink);
}

.login-btn {
  width: 100%;
  margin-top: var(--space-sm);
}

.sso-login-section {
  text-align: center;
  padding: var(--space-md) 0;
}
.sso-desc {
  color: var(--mute);
  margin-bottom: var(--space-md);
  font-size: var(--fs-body);
}

.form-footer {
  margin-top: var(--space-lg);
  font-size: var(--fs-small);
  text-align: center;
  color: var(--mute);
}
.form-footer a {
  color: var(--signal);
  text-decoration: none;
}
.form-footer a:hover { text-decoration: underline; }
.divider { margin: 0 var(--space-sm); color: var(--ink-line); }

/* === 开发预览模式 === */
.dev-preview {
  margin-top: var(--space-lg);
  padding-top: var(--space-md);
  border-top: 1px dashed var(--ink-line);
  text-align: center;
}
.dev-preview-row {
  display: flex;
  gap: var(--space-sm);
  justify-content: center;
}
.dev-preview-btn {
  background: transparent;
  border: 1px solid var(--signal);
  color: var(--signal);
  padding: 8px 16px;
  border-radius: var(--radius-md);
  font-size: var(--fs-small);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
  font-family: var(--font-body);
  flex: 1;
}
.dev-preview-btn:hover {
  background: var(--signal);
  color: var(--paper);
}
.dev-preview-btn.admin {
  border-color: var(--depth);
  color: var(--depth);
}
.dev-preview-btn.admin:hover {
  background: var(--depth);
  color: var(--paper);
}
.dev-hint {
  margin: var(--space-xs) 0 0 0;
  font-size: var(--fs-small);
  color: var(--mute);
}

/* === 响应式：窄屏隐藏雷达，表单居中 === */
@media (max-width: 900px) {
  .login-container { grid-template-columns: 1fr; }
  .radar-section { display: none; }
  .form-section { padding: var(--space-lg); }
}
</style>
