<template>
  <div class="client-overview">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>概览</h2>
      <p class="page-subtitle">本账号内容在 AI 搜索引擎中的收录情况</p>
    </div>

    <!-- 统计卡片：已收录 / 未收录 / 收录率 -->
    <div class="stats-grid">
      <div class="stat-card stat-success">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">01 / 03</span>
            <span class="card-label">已收录</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ indexedCount }}</span>
          </div>
        </div>
      </div>
      <div class="stat-card stat-danger">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">02 / 03</span>
            <span class="card-label">未收录</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ notIndexedCount }}</span>
          </div>
        </div>
      </div>
      <div class="stat-card stat-featured">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">03 / 03</span>
            <span class="card-label">收录率</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ ratePercent }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 已收录文章列表 -->
    <el-card class="articles-card" shadow="never" v-loading="loading">
      <h3>已收录文章</h3>
      <el-table :data="articles" border style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="url" label="URL" min-width="220" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" width="120" />
        <el-table-column label="收录状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.index_status)">{{ statusLabel(row.index_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检测时间" width="180">
          <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="!loading && articles.length === 0" class="empty-tip">暂无已收录文章</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { clientViewApi } from '@/api/clientView'

const overview = ref({
  indexed_urls: [],
  not_indexed_urls: [],
  index_rate: 0,
  articles: [],
})
const loading = ref(false)

const indexedCount = computed(() => (overview.value.indexed_urls || []).length)
const notIndexedCount = computed(() => (overview.value.not_indexed_urls || []).length)
// 收录率：后端返回 0~1 浮点数，渲染为百分比
// 整数百分比不带小数（0.5 → 50%），非整数保留 1 位（0.625 → 62.5%）
const ratePercent = computed(() => {
  const rate = Number(overview.value.index_rate) || 0
  const pct = Math.round(rate * 1000) / 10
  return Number.isInteger(pct) ? String(pct) : pct.toFixed(1)
})
const articles = computed(() => overview.value.articles || [])

function statusType(status) {
  if (status === 'indexed') return 'success'
  if (status === 'not_indexed') return 'danger'
  return 'info'
}

function statusLabel(status) {
  if (status === 'indexed') return '已收录'
  if (status === 'not_indexed') return '未收录'
  if (status === 'pending') return '待检测'
  if (!status) return '—'
  return status
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await clientViewApi.overview()
    overview.value = { ...overview.value, ...res.data }
  } catch (err) {
    console.error('获取概览失败', err)
    ElMessage.error('获取概览失败，请稍后重试')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.client-overview {
  padding: var(--space-md) var(--space-lg) var(--space-lg);
  max-width: 1280px;
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

/* === 统计卡片 === */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}

.stat-card {
  position: relative;
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  display: flex;
  overflow: hidden;
  transition: transform var(--transition-base), box-shadow var(--transition-base);
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
}
.color-bar {
  width: 4px;
  flex-shrink: 0;
}
.stat-success .color-bar { background: linear-gradient(180deg, #10B981, #34D399); }
.stat-danger  .color-bar { background: linear-gradient(180deg, #EF4444, #F59E0B); }
.stat-featured .color-bar { background: linear-gradient(180deg, #6366F1, #8B5CF6); }

.card-body {
  padding: var(--space-md);
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.index-label {
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.12em;
  font-weight: 600;
}
.card-label {
  font-size: var(--fs-small);
  color: var(--mute);
  font-weight: 500;
}
.card-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-xs);
}
.card-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--ink);
  letter-spacing: -0.02em;
  font-variant-numeric: lining-nums;
}
.stat-featured .card-value { font-size: 36px; }

/* === 文章卡片 === */
.articles-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.articles-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.articles-card h3::before {
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

.empty-tip {
  text-align: center;
  color: var(--mute);
  padding: var(--space-lg);
  font-size: var(--fs-small);
}

@media (max-width: 768px) {
  .client-overview { padding: var(--space-sm); }
  .stats-grid { grid-template-columns: 1fr; }
}
</style>
