<template>
  <div class="client-evidence">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>引用证据</h2>
      <p class="page-subtitle">AI 搜索引擎对您内容的引用与命中证据</p>
    </div>

    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <span class="filter-label">命中类型</span>
        <el-select
          v-model="hitType"
          placeholder="全部"
          clearable
          @change="onFilterChange"
        >
          <el-option label="精确命中" value="exact" />
          <el-option label="域名命中" value="domain" />
          <el-option label="未命中" value="none" />
        </el-select>
      </div>
    </el-card>

    <!-- 证据列表 -->
    <el-card class="evidence-card" shadow="never" v-loading="loading">
      <h3>证据列表</h3>
      <el-table :data="evidenceItems" border style="width: 100%">
        <el-table-column prop="article_title" label="文章标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="url" label="URL" min-width="200" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" width="110" />
        <el-table-column prop="question" label="问题" min-width="180" show-overflow-tooltip />
        <el-table-column label="命中类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="hitTypeTagType(row.hit_type)">{{ hitTypeLabel(row.hit_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ai_answer" label="AI 回答摘要" min-width="240" show-overflow-tooltip />
        <el-table-column label="检测时间" width="180">
          <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="!loading && evidenceItems.length === 0" class="empty-tip">暂无引用证据</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { clientViewApi } from '@/api/clientView'

const hitType = ref('')
const evidenceItems = ref([])
const loading = ref(false)

function hitTypeLabel(type) {
  if (type === 'exact') return '精确命中'
  if (type === 'domain') return '域名命中'
  if (type === 'none') return '未命中'
  if (!type) return '—'
  return type
}

function hitTypeTagType(type) {
  if (type === 'exact') return 'success'
  if (type === 'domain') return 'warning'
  if (type === 'none') return 'info'
  return 'info'
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function fetchEvidence() {
  loading.value = true
  try {
    const params = {}
    if (hitType.value) params.hit_type = hitType.value
    const res = await clientViewApi.evidence(params)
    evidenceItems.value = res.data.items || res.data || []
  } catch (err) {
    console.error('获取引用证据失败', err)
    ElMessage.error('获取引用证据失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  fetchEvidence()
}

onMounted(fetchEvidence)
</script>

<style scoped>
.client-evidence {
  padding: var(--space-md) var(--space-lg) var(--space-lg);
  max-width: 1440px;
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

.filter-card,
.evidence-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-md);
}

.filter-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}
.filter-label {
  font-size: var(--fs-small);
  color: var(--mute);
  white-space: nowrap;
}
.filter-card :deep(.el-select) {
  width: 200px;
}

.evidence-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.evidence-card h3::before {
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
  .client-evidence { padding: var(--space-sm); }
  .filter-card :deep(.el-select) { width: 100%; }
}
</style>
