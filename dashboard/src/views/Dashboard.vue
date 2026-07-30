<!-- dashboard/src/views/Dashboard.vue -->
<template>
  <div class="dashboard-container">
    <!-- 信号条已由 AppLayout 的 SignalBar 统一承载，此处不再重复 -->

    <!-- 统计卡片：不对称布局，第一个特色卡片更大 -->
    <div class="stats-grid">
      <StatCard
        :value="stats.total_distributions"
        label="分发总数"
        color="ink"
        featured
        index-label="01 / 04"
        :change="stats.total_change"
        change-direction="up"
        :spark-data="stats.total_spark"
        :submetrics="stats.total_sub"
      />
      <StatCard
        :value="stats.indexed_count"
        label="已收录"
        color="signal"
        index-label="02 / 04"
        :change="stats.indexed_change"
        change-direction="up"
        :spark-data="stats.indexed_spark"
        :submetrics="stats.indexed_sub"
      />
      <StatCard
        :value="stats.citation_count"
        label="AI 采信"
        color="depth"
        index-label="03 / 04"
        :change="stats.citation_change"
        change-direction="up"
        :spark-data="stats.citation_spark"
        :submetrics="stats.citation_sub"
      />
      <StatCard
        :value="indexRate + '%'"
        label="平均收录率"
        color="alert"
        index-label="04 / 04"
        :change="stats.rate_change"
        change-direction="up"
        :spark-data="stats.rate_spark"
        :submetrics="stats.rate_sub"
      />
    </div>

    <!-- 图表数据说明 -->
    <div class="data-notice">
      <el-icon><InfoFilled /></el-icon>
      <span>下方图表为示例数据展示，统计卡片为真实数据。图表接入真实数据功能开发中。</span>
    </div>

    <!-- 操作栏 -->
    <div class="action-bar">
      <el-button type="primary" @click="openExportDialog" :disabled="!chartsReady">
        <el-icon><Download /></el-icon> 导出报告（含图表）
      </el-button>
      <span v-if="!chartsReady" class="hint">图表渲染中…</span>
    </div>

    <!-- Bento 图表网格：非均匀，趋势图占 2/3 宽 -->
    <div class="charts-grid">
      <div class="chart-card chart-trend">
        <h3>多引擎收录趋势</h3>
        <div ref="trendChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card chart-pie">
        <h3>AI 采信分布</h3>
        <div ref="pieChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card chart-bar">
        <h3>引擎收录对比</h3>
        <div ref="barChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card chart-ring">
        <h3>来源分布</h3>
        <div ref="ringChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card chart-activity">
        <h3>活动统计</h3>
        <div ref="activityChartRef" class="chart-body"></div>
      </div>
    </div>

    <ExportDialog v-model="showExportDialog" :charts="chartsData" @created="onExportCreated" />
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import { useStore } from 'vuex'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Download, InfoFilled } from '@element-plus/icons-vue'
import StatCard from '@/components/StatCard.vue'
import ExportDialog from '@/components/ExportDialog.vue'
import { api } from '@/api'

const store = useStore()
const stats = ref({
  total_distributions: 0,
  indexed_count: 0,
  citation_count: 0,
  avg_index_rate: 0,
  // 新增：同比和子指标（需要后端 trend API 支持，暂时用 mock）
  total_change: '12%',
  total_change_dir: 'up',
  total_spark: [18, 22, 25, 20, 28, 30, 32, 35, 30, 33],
  total_sub: [
    { label: '本周', value: '+18' },
    { label: '本月', value: '+47' },
    { label: '待检测', value: '12' },
  ],
  indexed_change: '8%',
  indexed_change_dir: 'up',
  indexed_spark: [12, 15, 18, 16, 20, 22, 25, 23, 24, 25],
  indexed_sub: [
    { label: '本周', value: '+12' },
    { label: '百度', value: '198' },
    { label: '头条', value: '156' },
  ],
  citation_change: '23%',
  citation_change_dir: 'up',
  citation_spark: [5, 8, 10, 12, 15, 18, 20, 22, 25, 28],
  citation_sub: [
    { label: '完全命中', value: '32' },
    { label: '部分命中', value: '41' },
    { label: '未命中', value: '16' },
  ],
  rate_change: '5.2pp',
  rate_change_dir: 'up',
  rate_spark: [65, 68, 70, 69, 71, 72, 70, 72, 73, 73.4],
  rate_sub: [
    { label: '百度', value: '81%' },
    { label: '头条', value: '73%' },
    { label: '搜狗', value: '68%' },
  ],
})
const indexRate = computed(() => (stats.value.avg_index_rate * 100).toFixed(1))
const isAdmin = computed(() => store.state.role === 'admin')

// 信号条事件已由 App.vue 统一拉取并经 AppLayout 传给 SignalBar，本页不再维护。

// === ECharts "SaaS Spectrum" 多彩调色板 ===
const ECHARTS_PALETTE = {
  signal: '#6366F1',
  alert: '#EF4444',
  depth: '#8B5CF6',
  ink: '#0F172A',
  mute: '#64748B',
  // 多彩系列色：靛蓝/紫/粉/青/翠，现代 SaaS 仪表盘标准色板
  series: ['#6366F1', '#8B5CF6', '#EC4899', '#06B6D4', '#10B981'],
  pie: ['#6366F1', '#8B5CF6', '#EC4899', '#06B6D4', '#94A3B8'],
}

const ECHARTS_BASE = {
  textStyle: { fontFamily: 'Inter, sans-serif', color: '#0F172A' },
  color: ECHARTS_PALETTE.series,
}

// ECharts 实例引用（用于 getDataURL 截图导出）
const chartInstances = {}
const chartsReady = ref(false)

const showExportDialog = ref(false)
const chartsData = ref({})

const trendChartRef = ref(null)
const pieChartRef = ref(null)
const barChartRef = ref(null)
const ringChartRef = ref(null)
const activityChartRef = ref(null)

onMounted(async () => {
  await fetchStats()
  await nextTick()
  initCharts()
  chartsReady.value = true
})

async function fetchStats() {
  // 开发预览模式：使用 mock 数据，不调 API（避免 401 干扰设计预览）
  if (localStorage.getItem('token') === 'dev-preview-token') {
    // 合并赋值：保留 ref 中预设的同比/sparkline/子指标 mock（待后端 trend API 接入）
    stats.value = {
      ...stats.value,
      total_distributions: 42,
      indexed_count: 28,
      citation_count: 15,
      avg_index_rate: 0.533,
    }
    return
  }

  try {
    const endpoint = isAdmin.value ? '/admin/distributions' : '/distributions'
    const resp = await api.get(endpoint)
    const items = resp.data.items || []

    const engineKeys = ['baidu', 'toutiao', 'sogou', 'so360', 'bing']
    const totalSlots = items.length * engineKeys.length
    const indexedSlots = items.reduce((sum, i) =>
      sum + engineKeys.filter(k => (i.index_status || {})[k] === 'indexed').length, 0)
    const indexed = items.filter(i => Object.values(i.index_status || {}).some(s => s === 'indexed')).length

    let citationCount = 0
    try {
      const citationResp = await api.get('/stats/citation')
      citationCount = citationResp.data?.cited ?? citationResp.data?.citation_count ?? 0
    } catch {
      citationCount = 0
    }

    stats.value = {
      ...stats.value,
      total_distributions: items.length,
      indexed_count: indexed,
      citation_count: citationCount,
      avg_index_rate: totalSlots > 0 ? indexedSlots / totalSlots : 0,
    }
  } catch (err) {
    console.error('获取统计失败', err)
  }
}

function initCharts() {
  const baseAxis = {
    axisLine: { lineStyle: { color: '#CBD5E1' } },
    axisLabel: { color: '#64748B', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
    splitLine: { lineStyle: { color: 'rgba(15,23,42,0.06)' } },
  }
  const darkTooltip = {
    backgroundColor: 'rgba(15, 23, 42, 0.92)',
    borderColor: 'rgba(99, 102, 241, 0.3)',
    textStyle: { color: '#F8FAFC' },
    borderRadius: 8,
    padding: [8, 12],
    extraCssText: 'box-shadow: 0 8px 24px rgba(15,23,42,0.18); backdrop-filter: blur(8px);',
  }

  // 趋势图：多引擎折线，signal 主色
  if (trendChartRef.value) {
    const chart = echarts.init(trendChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'axis', ...darkTooltip },
      legend: { data: ['百度', '头条', '搜狗', '360', '必应'], textStyle: { color: '#0F172A' }, bottom: 0 },
      grid: { left: 40, right: 20, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: ['7/19', '7/20', '7/21', '7/22', '7/23', '7/24', '7/25'], ...baseAxis },
      yAxis: { type: 'value', ...baseAxis },
      series: [
        { name: '百度', type: 'line', data: [5, 8, 12, 15, 18, 22, 25], smooth: true, lineStyle: { width: 2 }, itemStyle: { color: ECHARTS_PALETTE.series[0] } },
        { name: '头条', type: 'line', data: [3, 5, 7, 9, 11, 13, 15], smooth: true, itemStyle: { color: ECHARTS_PALETTE.series[1] } },
        { name: '搜狗', type: 'line', data: [2, 3, 4, 5, 6, 7, 8], smooth: true, itemStyle: { color: ECHARTS_PALETTE.series[2] } },
        { name: '360',  type: 'line', data: [1, 2, 3, 4, 5, 6, 7], smooth: true, itemStyle: { color: ECHARTS_PALETTE.series[3] } },
        { name: '必应', type: 'line', data: [4, 6, 8, 10, 12, 14, 16], smooth: true, itemStyle: { color: ECHARTS_PALETTE.series[4] } },
      ],
    })
    chartInstances.trend = chart
  }

  // 饼图：AI 采信分布
  if (pieChartRef.value) {
    const chart = echarts.init(pieChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'item', ...darkTooltip },
      legend: { bottom: 0, textStyle: { color: '#0F172A' } },
      series: [{
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['50%', '45%'],
        itemStyle: { borderColor: '#FFFFFF', borderWidth: 2 },
        label: { color: '#0F172A' },
        data: [
          { value: 35, name: '千问',     itemStyle: { color: ECHARTS_PALETTE.pie[0] } },
          { value: 25, name: '豆包',     itemStyle: { color: ECHARTS_PALETTE.pie[1] } },
          { value: 20, name: 'DeepSeek', itemStyle: { color: ECHARTS_PALETTE.pie[2] } },
          { value: 15, name: '文心',     itemStyle: { color: ECHARTS_PALETTE.pie[3] } },
          { value: 5,  name: '未命中',   itemStyle: { color: ECHARTS_PALETTE.pie[4] } },
        ],
      }],
    })
    chartInstances.pie = chart
  }

  // 柱状图：引擎收录对比（渐变柱体）
  if (barChartRef.value) {
    const chart = echarts.init(barChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'axis', ...darkTooltip },
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: ['百度', '头条', '搜狗', '360', '必应'], ...baseAxis },
      yAxis: { type: 'value', ...baseAxis },
      series: [{
        type: 'bar',
        data: [25, 15, 8, 7, 16],
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
            { offset: 0, color: '#6366F1' },
            { offset: 1, color: '#8B5CF6' },
          ] },
        },
        barWidth: '50%',
      }],
    })
    chartInstances.bar = chart
  }

  // 环形图：来源分布
  if (ringChartRef.value) {
    const chart = echarts.init(ringChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'item', ...darkTooltip },
      legend: { bottom: 0, textStyle: { color: '#0F172A' } },
      series: [{
        type: 'pie',
        radius: ['45%', '70%'],
        itemStyle: { borderColor: '#FFFFFF', borderWidth: 2 },
        label: { color: '#0F172A' },
        data: [
          { value: 40, name: 'GEOFlow 推送', itemStyle: { color: ECHARTS_PALETTE.signal } },
          { value: 10, name: '手动录入',     itemStyle: { color: ECHARTS_PALETTE.mute } },
        ],
      }],
    })
    chartInstances.ring = chart
  }

  // 活动统计（渐变柱体）
  if (activityChartRef.value) {
    const chart = echarts.init(activityChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'axis', ...darkTooltip },
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], ...baseAxis },
      yAxis: { type: 'value', ...baseAxis },
      series: [{
        type: 'bar',
        data: [12, 18, 15, 22, 28, 8, 5],
        itemStyle: {
          borderRadius: [6, 6, 0, 0],
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
            { offset: 0, color: '#8B5CF6' },
            { offset: 1, color: '#EC4899' },
          ] },
        },
        barWidth: '50%',
      }],
    })
    chartInstances.activity = chart
  }
}

function getChartsDataURL() {
  const result = {}
  const opts = { type: 'png', pixelRatio: 2, backgroundColor: '#fff' }
  if (chartInstances.trend) {
    result.trend = chartInstances.trend.getDataURL(opts)
  }
  if (chartInstances.pie) {
    result.pie = chartInstances.pie.getDataURL(opts)
  }
  return result
}

function openExportDialog() {
  chartsData.value = getChartsDataURL()
  showExportDialog.value = true
}

function onExportCreated(taskId) {
  ElMessage.success(`导出任务已创建：${taskId}，预计 30 秒内完成`)
}
</script>

<style scoped>
.dashboard-container {
  padding: var(--space-md) var(--space-lg) var(--space-lg);
  max-width: 1440px;
  margin: 0 auto;
}

/* 信号条样式已移除——由 AppLayout 的 SignalBar 组件统一承载 */

/* === 统计卡片：不对称网格 === */
.stats-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr 1fr;
  gap: var(--space-md);
  margin-bottom: var(--space-lg);
}

/* === 数据提示 === */
.data-notice {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-md);
  background: rgba(245, 158, 11, 0.08);
  border-left: 3px solid var(--c-amber);
  border-radius: var(--radius-md);
  color: #92400E;
  font-size: var(--fs-small);
}

/* === 操作栏 === */
.action-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-lg);
}
.action-bar .hint {
  color: var(--mute);
  font-size: var(--fs-small);
}

/* === Bento 图表网格（非均匀） === */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-auto-rows: minmax(280px, auto);
  gap: var(--space-md);
}
.chart-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  transition: box-shadow var(--transition-base), transform var(--transition-base);
}
.chart-card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}
.chart-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.chart-card h3::before {
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
.chart-body { flex: 1; min-height: 240px; }

/* Bento 布局：趋势图占 2/3 宽 */
.chart-trend    { grid-column: span 2; }
.chart-pie      { grid-column: span 1; }
.chart-bar      { grid-column: span 1; }
.chart-ring     { grid-column: span 1; }
.chart-activity { grid-column: span 1; }

/* === 响应式 === */
@media (max-width: 1199px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .stats-grid > :first-child { grid-column: span 2; }
  .charts-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-trend { grid-column: span 2; }
}
@media (max-width: 768px) {
  .dashboard-container { padding: var(--space-sm); }
  .stats-grid { grid-template-columns: 1fr; }
  .stats-grid > :first-child { grid-column: span 1; }
  .charts-grid { grid-template-columns: 1fr; }
  .chart-trend { grid-column: span 1; }
}
</style>
