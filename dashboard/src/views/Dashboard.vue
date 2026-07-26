<!-- dashboard/src/views/Dashboard.vue -->
<template>
  <div class="dashboard-container">
    <!-- 4 统计卡片 -->
    <div class="stats-row">
      <StatCard :value="stats.total_distributions" label="分发总数" icon="Document" color="blue" />
      <StatCard :value="stats.indexed_count" label="已收录" icon="CircleCheck" color="green" />
      <StatCard :value="stats.citation_count" label="AI 采信" icon="ChatDotRound" color="orange" />
      <StatCard :value="indexRate + '%'" label="平均收录率" icon="TrendCharts" color="purple" />
    </div>

    <!-- 图表数据说明 -->
    <div class="data-notice">
      <el-icon><InfoFilled /></el-icon>
      <span>下方图表为示例数据展示，统计卡片为真实数据。图表接入真实数据功能开发中。</span>
    </div>

    <!-- 操作栏（所有用户可见导出按钮，含图表截图） -->
    <div class="action-bar">
      <el-button type="primary" @click="openExportDialog" :disabled="!chartsReady">
        <el-icon><Download /></el-icon> 导出报告（含图表）
      </el-button>
      <span v-if="!chartsReady" class="hint">图表渲染中…</span>
    </div>

    <!-- 5 图表 -->
    <div class="charts-grid">
      <div class="chart-card large">
        <h3>多引擎收录趋势</h3>
        <div ref="trendChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>AI 采信分布</h3>
        <div ref="pieChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>引擎收录对比</h3>
        <div ref="barChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>来源分布</h3>
        <div ref="ringChartRef" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <h3>活动统计</h3>
        <div ref="activityChartRef" class="chart-body"></div>
      </div>
    </div>

    <!-- 导出对话框（接收 charts 截图） -->
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
// 修复：改用 Vuex store 的响应式 role，而非直接读 localStorage（localStorage 非响应式）
const isAdmin = computed(() => store.state.role === 'admin')

// ECharts 实例引用（用于 getDataURL 截图导出）
const chartInstances = {}
const chartsReady = ref(false)

// 导出对话框状态
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
  try {
    // 根据角色调用不同 API：admin 用 /admin/distributions（跨客户），client 用 /distributions（仅自己）
    const endpoint = isAdmin.value ? '/admin/distributions' : '/distributions'
    const resp = await api.get(endpoint)
    const items = resp.data.items || []

    // 修复收录率计算：按引擎槽位计算（5 个引擎 × URL 数）
    // 原逻辑"任一引擎收录即算已收录"会虚高（一个引擎收录就 100%）
    const engineKeys = ['baidu', 'toutiao', 'sogou', 'so360', 'bing']
    const totalSlots = items.length * engineKeys.length
    const indexedSlots = items.reduce((sum, i) =>
      sum + engineKeys.filter(k => (i.index_status || {})[k] === 'indexed').length, 0)
    // "已收录"卡片：至少一个引擎收录的 URL 数（保持原语义，但收录率用槽位算法）
    const indexed = items.filter(i => Object.values(i.index_status || {}).some(s => s === 'indexed')).length

    // 修复 AI 采信次数：用 cited 字段（真正被采信的次数，hit_type != "none"）
    // 原逻辑用 total 字段（所有检测记录数，包括未命中），导致显示 30 = 3问题×10模型
    let citationCount = 0
    try {
      const citationResp = await api.get('/stats/citation')
      // 优先 cited（真正被采信），其次 citation_count，最后才 total（兼容旧端点）
      citationCount = citationResp.data?.cited ?? citationResp.data?.citation_count ?? 0
    } catch {
      // 端点不存在或失败时降级为 0
      citationCount = 0
    }

    stats.value = {
      total_distributions: items.length,
      indexed_count: indexed,
      citation_count: citationCount,
      // 收录率：按引擎槽位计算（已收录槽位 / 总槽位）
      avg_index_rate: totalSlots > 0 ? indexedSlots / totalSlots : 0,
    }
  } catch (err) {
    console.error('获取统计失败', err)
  }
}

function initCharts() {
  // 趋势图
  if (trendChartRef.value) {
    const chart = echarts.init(trendChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['百度', '头条', '搜狗', '360', '必应'] },
      xAxis: { type: 'category', data: ['7/19', '7/20', '7/21', '7/22', '7/23', '7/24', '7/25'] },
      yAxis: { type: 'value' },
      series: [
        { name: '百度', type: 'line', data: [5, 8, 12, 15, 18, 22, 25], smooth: true },
        { name: '头条', type: 'line', data: [3, 5, 7, 9, 11, 13, 15], smooth: true },
        { name: '搜狗', type: 'line', data: [2, 3, 4, 5, 6, 7, 8], smooth: true },
        { name: '360', type: 'line', data: [1, 2, 3, 4, 5, 6, 7], smooth: true },
        { name: '必应', type: 'line', data: [4, 6, 8, 10, 12, 14, 16], smooth: true },
      ],
    })
    chartInstances.trend = chart
  }

  // 饼图：AI 采信分布
  if (pieChartRef.value) {
    const chart = echarts.init(pieChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        radius: '60%',
        data: [
          { value: 35, name: '千问' },
          { value: 25, name: '豆包' },
          { value: 20, name: 'DeepSeek' },
          { value: 15, name: '文心' },
          { value: 5, name: '未命中' },
        ],
      }],
    })
    chartInstances.pie = chart
  }

  // 柱状图：引擎收录对比
  if (barChartRef.value) {
    const chart = echarts.init(barChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['百度', '头条', '搜狗', '360', '必应'] },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: [25, 15, 8, 7, 16], itemStyle: { color: '#3498db' } }],
    })
    chartInstances.bar = chart
  }

  // 环形图：来源分布
  if (ringChartRef.value) {
    const chart = echarts.init(ringChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        data: [
          { value: 40, name: 'GEOFlow 推送' },
          { value: 10, name: '手动录入' },
        ],
      }],
    })
    chartInstances.ring = chart
  }

  // 活动统计
  if (activityChartRef.value) {
    const chart = echarts.init(activityChartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'] },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: [12, 18, 15, 22, 28, 8, 5], itemStyle: { color: '#9c27b0' } }],
    })
    chartInstances.activity = chart
  }
}

/**
 * 获取 PDF 导出所需的图表截图（base64 数据 URL）。
 * 只截 trend（趋势图）和 pie（AI 采信分布），与 report.html 模板的 charts.trend/charts.pie 占位一一对应。
 */
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
.dashboard-container { padding: 20px; }
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}
.data-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 20px;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 4px;
  color: #e6a23c;
  font-size: 13px;
}
.action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.action-bar .hint {
  color: #999;
  font-size: 13px;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.chart-card {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.chart-card.large { grid-column: span 3; }
.chart-card h3 { margin: 0 0 15px 0; color: #2c3e50; }
.chart-body { height: 300px; }

/* 响应式 */
@media (max-width: 1199px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .charts-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-card.large { grid-column: span 2; }
}
@media (max-width: 768px) {
  .stats-row { grid-template-columns: 1fr; }
  .charts-grid { grid-template-columns: 1fr; }
  .chart-card.large { grid-column: span 1; }
}
</style>
