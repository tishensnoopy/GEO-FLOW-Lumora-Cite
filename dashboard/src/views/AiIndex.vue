<template>
  <div class="ai-index-container">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>AI 收录检测</h2>
      <p class="page-subtitle">AI 搜索引擎对站点内容的收录情况统计与明细</p>
    </div>

    <!-- 统计 + by_model 图表 + by_client 表格 -->
    <AiIndexStats :stats="stats" />

    <!-- 筛选栏 + 结果列表 + 分页 -->
    <AiIndexTable
      :items="results.items"
      :filters="filters"
      :page="results.page"
      :page-size="results.page_size"
      :total="results.total"
      :loading="loading"
      :model-options="modelOptions"
      @filter-change="onFilterChange"
      @page-change="onPageChange"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { aiIndexApi } from '@/api/aiIndex'
import AiIndexStats from '@/components/AiIndexStats.vue'
import AiIndexTable from '@/components/AiIndexTable.vue'

const stats = ref({
  indexed: 0,
  not_indexed: 0,
  pending: 0,
  rate: 0,
  by_model: [],
  by_client: [],
})

const results = ref({
  items: [],
  page: 1,
  page_size: 20,
  total: 0,
})

const filters = reactive({
  url: '',
  model: '',
  index_status: '',
})

const loading = ref(false)

// 模型下拉选项：从 by_model 推导 + 兜底常见模型
const modelOptions = computed(() => {
  const fromStats = (stats.value.by_model || []).map(m => m.model)
  const presets = ['doubao', 'deepseek', 'qwen', 'wenxin', 'kimi']
  return Array.from(new Set([...presets, ...fromStats]))
})

onMounted(async () => {
  await Promise.all([fetchStats(), fetchResults()])
})

async function fetchStats() {
  try {
    const res = await aiIndexApi.getStats()
    stats.value = res.data
  } catch (err) {
    console.error('获取 AI 收录统计失败', err)
    ElMessage.error('获取统计失败，请稍后重试')
  }
}

async function fetchResults() {
  loading.value = true
  try {
    const params = {
      ...filters,
      page: results.value.page,
      page_size: results.value.page_size,
    }
    const res = await aiIndexApi.listResults(params)
    results.value = { ...results.value, ...res.data }
  } catch (err) {
    console.error('获取 AI 收录结果失败', err)
    ElMessage.error('获取结果列表失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function onFilterChange(next) {
  Object.assign(filters, next)
  results.value.page = 1
  fetchResults()
}

function onPageChange(page) {
  results.value.page = page
  fetchResults()
}
</script>

<style scoped>
.ai-index-container {
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

@media (max-width: 768px) {
  .ai-index-container { padding: var(--space-sm); }
}
</style>
