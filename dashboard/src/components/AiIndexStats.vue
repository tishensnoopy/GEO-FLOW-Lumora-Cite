<template>
  <div class="ai-index-stats">
    <!-- 4 个统计卡片：收录率/已收录/未收录/待检测 -->
    <div class="stats-grid">
      <div class="stat-card stat-featured">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">01 / 04</span>
            <span class="card-label">收录率</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ ratePercent }}%</span>
          </div>
        </div>
      </div>
      <div class="stat-card stat-success">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">02 / 04</span>
            <span class="card-label">已收录</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ stats.indexed }}</span>
          </div>
        </div>
      </div>
      <div class="stat-card stat-danger">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">03 / 04</span>
            <span class="card-label">未收录</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ stats.not_indexed }}</span>
          </div>
        </div>
      </div>
      <div class="stat-card stat-info">
        <div class="color-bar"></div>
        <div class="card-body">
          <div class="card-header">
            <span class="index-label mono">04 / 04</span>
            <span class="card-label">待检测</span>
          </div>
          <div class="card-main">
            <span class="card-value">{{ stats.pending }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- by_model 柱状图：各模型 indexed/not_indexed 对比 -->
    <el-card class="chart-card" shadow="never">
      <h3>各模型收录对比</h3>
      <div ref="chartRef" class="chart-body"></div>
    </el-card>

    <!-- by_client 表格：client_id/indexed/not_indexed/pending/rate -->
    <el-card class="client-card" shadow="never">
      <h3>客户收录分布</h3>
      <el-table :data="stats.by_client" border style="width: 100%">
        <el-table-column prop="client_id" label="客户 ID" width="160" />
        <el-table-column prop="indexed" label="已收录" width="100" align="center" />
        <el-table-column prop="not_indexed" label="未收录" width="100" align="center" />
        <el-table-column prop="pending" label="待检测" width="100" align="center" />
        <el-table-column label="收录率" align="center">
          <template #default="{ row }">
            <span :class="rateClass(row.rate)">{{ (row.rate * 100).toFixed(1) }}%</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  stats: {
    type: Object,
    default: () => ({
      indexed: 0, not_indexed: 0, pending: 0, index_rate: 0,
      by_model: [], by_client: [],
    }),
  },
})

const chartRef = ref(null)
let chartInstance = null

// 顶层收录率字段名与后端 GET /admin/ai-index/stats 契约一致（index_rate）
// 注意：by_model / by_client 项内的 rate 字段名不变（后端项内字段就是 rate）
const ratePercent = computed(() => (props.stats.index_rate * 100).toFixed(1))

function rateClass(rate) {
  if (rate >= 0.8) return 'rate-high'
  if (rate >= 0.5) return 'rate-mid'
  return 'rate-low'
}

function buildOption() {
  const byModel = props.stats.by_model || []
  const models = byModel.map(m => m.model)
  const indexedSeries = byModel.map(m => m.indexed)
  const notIndexedSeries = byModel.map(m => m.not_indexed)
  const pendingSeries = byModel.map(m => m.pending)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['已收录', '未收录', '待检测'], bottom: 0 },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: models },
    yAxis: { type: 'value' },
    series: [
      { name: '已收录', type: 'bar', data: indexedSeries, itemStyle: { color: '#10B981', borderRadius: [4, 4, 0, 0] } },
      { name: '未收录', type: 'bar', data: notIndexedSeries, itemStyle: { color: '#EF4444', borderRadius: [4, 4, 0, 0] } },
      { name: '待检测', type: 'bar', data: pendingSeries, itemStyle: { color: '#94A3B8', borderRadius: [4, 4, 0, 0] } },
    ],
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  chartInstance.setOption(buildOption(), true)
}

function handleResize() {
  if (chartInstance) chartInstance.resize()
}

onMounted(() => {
  nextTick(renderChart)
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

watch(() => props.stats, () => nextTick(renderChart), { deep: true })
</script>

<style scoped>
.ai-index-stats {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

/* === 统计卡片网格 === */
.stats-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr 1fr;
  gap: var(--space-md);
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
.stat-featured::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--grad-brand);
  z-index: 1;
}
.color-bar {
  width: 4px;
  flex-shrink: 0;
}
.stat-featured .color-bar { background: linear-gradient(180deg, #0F172A, #475569); }
.stat-success .color-bar { background: linear-gradient(180deg, #10B981, #34D399); }
.stat-danger  .color-bar { background: linear-gradient(180deg, #EF4444, #F59E0B); }
.stat-info    .color-bar { background: linear-gradient(180deg, #6366F1, #8B5CF6); }

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

/* === 图表卡片 === */
.chart-card,
.client-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-card);
}
.chart-card h3,
.client-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.chart-card h3::before,
.client-card h3::before {
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
.chart-body {
  width: 100%;
  height: 320px;
}

/* === 收录率颜色 === */
.rate-high { color: #059669; font-weight: 700; }
.rate-mid  { color: #92400E; font-weight: 700; }
.rate-low  { color: #DC2626; font-weight: 700; }

/* === 响应式 === */
@media (max-width: 1199px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .stats-grid > :first-child { grid-column: span 2; }
}
@media (max-width: 768px) {
  .stats-grid { grid-template-columns: 1fr; }
  .stats-grid > :first-child { grid-column: span 1; }
  .chart-body { height: 260px; }
}
</style>
