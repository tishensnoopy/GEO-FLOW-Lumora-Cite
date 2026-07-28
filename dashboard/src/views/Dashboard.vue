<!-- dashboard/src/views/Dashboard.vue -->
<template>
  <div class="dashboard-container">
    <!-- 信号条：标志性元素，横向滚动实时事件 ticker -->
    <div class="signal-strip" role="marquee" aria-label="实时监测事件">
      <div class="signal-strip-label mono">SIGNAL · LIVE</div>
      <!-- viewport 负责裁剪（固定不动），track 负责动画（滚动）——分离两层避免 transform 移动裁剪区域 -->
      <div class="signal-strip-viewport">
        <div class="signal-strip-track">
          <div class="signal-strip-item" v-for="(evt, i) in signalEvents" :key="i">
            <span class="evt-time mono">{{ evt.time }}</span>
            <span class="evt-engine" :class="evt.status">{{ evt.engine }}</span>
            <span class="evt-action">{{ evt.action }}</span>
            <span class="evt-title">{{ evt.title }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 统计卡片：不对称布局，第一个特色卡片更大 -->
    <div class="stats-grid">
      <StatCard
        :value="stats.total_distributions"
        label="分发总数"
        icon="Document"
        color="ink"
        featured
        index-label="01 / 04"
      />
      <StatCard
        :value="stats.indexed_count"
        label="已收录"
        icon="CircleCheck"
        color="signal"
        index-label="02 / 04"
      />
      <StatCard
        :value="stats.citation_count"
        label="AI 采信"
        icon="ChatDotRound"
        color="depth"
        index-label="03 / 04"
      />
      <StatCard
        :value="indexRate + '%'"
        label="平均收录率"
        icon="TrendCharts"
        color="alert"
        index-label="04 / 04"
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
const stats = ref({ total_distributions: 0, indexed_count: 0, citation_count: 0, avg_index_rate: 0 })
const indexRate = computed(() => (stats.value.avg_index_rate * 100).toFixed(1))
const isAdmin = computed(() => store.state.role === 'admin')

// 信号条 mock 事件（真实数据接入前占位；后续可从 /distributions 实时拉取）
const signalEvents = ref([
  { time: '10:32', engine: '百度',     action: '收录',   title: '《内容营销新趋势》', status: 'indexed' },
  { time: '10:28', engine: 'DeepSeek', action: '采信',   title: '《SEO 实战指南》',  status: 'cited' },
  { time: '10:15', engine: '头条',     action: '待检测', title: '《GEO 优化手册》',  status: 'pending' },
  { time: '10:02', engine: '必应',     action: '收录',   title: '《AI 搜索原理》',   status: 'indexed' },
  { time: '09:48', engine: '千问',     action: '采信',   title: '《长尾词策略》',    status: 'cited' },
  { time: '09:30', engine: '搜狗',     action: '未收录', title: '《外链建设》',      status: 'failed' },
])

// === ECharts "Ink & Signal" 调色板 ===
const ECHARTS_PALETTE = {
  signal: '#0D9488',
  alert: '#E76F51',
  depth: '#4C1D95',
  ink: '#1A1A1A',
  mute: '#78716C',
  series: ['#0D9488', '#4C1D95', '#E76F51', '#78716C', '#1A1A1A'],
  pie: ['#0D9488', '#4C1D95', '#E76F51', '#78716C', '#C9C5BD'],
}

const ECHARTS_BASE = {
  textStyle: { fontFamily: 'Inter, sans-serif', color: '#1A1A1A' },
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
    stats.value = {
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
    axisLine: { lineStyle: { color: '#78716C' } },
    axisLabel: { color: '#78716C', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 },
    splitLine: { lineStyle: { color: 'rgba(26,26,26,0.06)' } },
  }
  const darkTooltip = {
    backgroundColor: '#1A1A1A',
    borderColor: '#1A1A1A',
    textStyle: { color: '#FAFAF7' },
  }

  // 趋势图：多引擎折线，signal 主色
  if (trendChartRef.value) {
    const chart = echarts.init(trendChartRef.value)
    chart.setOption({
      ...ECHARTS_BASE,
      tooltip: { trigger: 'axis', ...darkTooltip },
      legend: { data: ['百度', '头条', '搜狗', '360', '必应'], textStyle: { color: '#1A1A1A' }, bottom: 0 },
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
      legend: { bottom: 0, textStyle: { color: '#1A1A1A' } },
      series: [{
        type: 'pie',
        radius: ['35%', '65%'],
        center: ['50%', '45%'],
        itemStyle: { borderColor: '#FFFFFF', borderWidth: 2 },
        label: { color: '#1A1A1A' },
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

  // 柱状图：引擎收录对比
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
        itemStyle: { color: ECHARTS_PALETTE.signal, borderRadius: [2, 2, 0, 0] },
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
      legend: { bottom: 0, textStyle: { color: '#1A1A1A' } },
      series: [{
        type: 'pie',
        radius: ['45%', '70%'],
        itemStyle: { borderColor: '#FFFFFF', borderWidth: 2 },
        label: { color: '#1A1A1A' },
        data: [
          { value: 40, name: 'GEOFlow 推送', itemStyle: { color: ECHARTS_PALETTE.signal } },
          { value: 10, name: '手动录入',     itemStyle: { color: ECHARTS_PALETTE.mute } },
        ],
      }],
    })
    chartInstances.ring = chart
  }

  // 活动统计
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
        itemStyle: { color: ECHARTS_PALETTE.depth, borderRadius: [2, 2, 0, 0] },
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

/* === 信号条（标志性元素） === */
.signal-strip {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  height: 44px;
  margin-bottom: var(--space-lg);
  background: var(--ink);
  color: var(--paper);
  border-radius: var(--radius-md);
  overflow: hidden;
  padding: 0 var(--space-md);
}
.signal-strip-label {
  position: relative;
  z-index: 2;
  background: var(--ink);  /* 实色背景兜底：即使 track 内容滑入也遮住 */
  padding-right: var(--space-md);
  color: var(--signal);
  font-size: var(--fs-mono);
  letter-spacing: 0.2em;
  white-space: nowrap;
  font-weight: 500;
  flex-shrink: 0;
}
.signal-strip-label::before {
  content: '●';
  margin-right: 6px;
  animation: blink 1.5s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* viewport：固定裁剪层，不参与动画 */
.signal-strip-viewport {
  flex: 1;
  overflow: hidden;
  /* 左右渐隐遮罩：文字进出 viewport 时优雅淡入/淡出 */
  -webkit-mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0%, black 24px, black calc(100% - 24px), transparent 100%);
}

/* track：动画层，只负责 translateX 滚动 */
.signal-strip-track {
  display: flex;
  gap: var(--space-xl);
  white-space: nowrap;
  animation: ticker 30s linear infinite;
}
@keyframes ticker {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
.signal-strip-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--fs-mono);
}
.evt-time { color: var(--mute); }
.evt-engine { padding: 1px 6px; border-radius: var(--radius-sm); font-weight: 500; }
.evt-engine.indexed { background: var(--signal-soft); color: var(--signal); }
.evt-engine.cited   { background: var(--depth-soft);  color: var(--depth); }
.evt-engine.pending { background: rgba(201, 151, 0, 0.15); color: #C99700; }
.evt-engine.failed  { background: var(--alert-soft);  color: var(--alert); }
.evt-action { color: var(--paper); opacity: 0.7; }
.evt-title { color: var(--paper); }

/* hover 暂停滚动（提升可读性） */
.signal-strip:hover .signal-strip-track { animation-play-state: paused; }

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
  background: rgba(201, 151, 0, 0.08);
  border-left: 3px solid #C99700;
  border-radius: var(--radius-sm);
  color: #8a6800;
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
  background: var(--surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  box-shadow: var(--paper-shadow);
  display: flex;
  flex-direction: column;
}
.chart-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 12px;
}
.chart-card h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  background: var(--signal);
  border-radius: var(--radius-sm);
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
  .signal-strip-track { animation-duration: 40s; }
}
</style>
