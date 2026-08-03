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

    <!-- 服务商工作量统计（发稿量披露） -->
    <el-card class="section-card" shadow="never" v-loading="workLoading">
      <h3>服务商工作量统计</h3>
      <div class="work-stats-grid">
        <div class="mini-stat">
          <span class="mini-label">本月发稿量</span>
          <span class="mini-value">{{ workSummary.this_month_distributions ?? 0 }}</span>
        </div>
        <div class="mini-stat">
          <span class="mini-label">累计发稿量</span>
          <span class="mini-value">{{ workSummary.total_distributions ?? 0 }}</span>
        </div>
        <div class="mini-stat">
          <span class="mini-label">监测问题数</span>
          <span class="mini-value">{{ workSummary.total_questions ?? 0 }}</span>
        </div>
        <div class="mini-stat mini-stat-accent">
          <span class="mini-label">引用率</span>
          <span class="mini-value">{{ citationRatePercent }}%</span>
        </div>
      </div>

      <el-table :data="workItems" border style="width: 100%; margin-top: 16px">
        <el-table-column label="发稿标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <a v-if="row.url" :href="row.url" target="_blank" rel="noopener" class="cell-link">{{ row.title || '未命名' }}</a>
            <span v-else>{{ row.title || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分发时间" width="180">
          <template #default="{ row }">{{ formatTime(row.distributed_at) }}</template>
        </el-table-column>
        <el-table-column label="关联问题" min-width="220">
          <template #default="{ row }">
            <template v-if="row.questions && row.questions.length">
              <el-tag
                v-for="q in row.questions"
                :key="q.id || q.question"
                class="question-tag"
                size="small"
                type="info"
                effect="plain"
              >
                {{ q.question }}
              </el-tag>
            </template>
            <span v-else class="mute-text">—</span>
          </template>
        </el-table-column>
        <el-table-column label="引用检测结果" min-width="240">
          <template #default="{ row }">
            <template v-if="row.citation_results && row.citation_results.length">
              <div class="citation-list">
                <el-tag
                  v-for="(c, idx) in row.citation_results"
                  :key="idx"
                  :type="hitTypeTagType(c.hit_type)"
                  size="small"
                  class="citation-tag"
                >
                  {{ modelDisplayName(c.model) }} {{ hitTypeSymbol(c.hit_type) }}
                </el-tag>
              </div>
            </template>
            <span v-else class="mute-text">暂无检测</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!workLoading && workItems.length === 0" class="empty-tip">暂无发稿记录</div>
    </el-card>

    <!-- AI 可见度得分 -->
    <el-card class="section-card" shadow="never" v-loading="visibilityLoading">
      <h3>AI 可见度得分</h3>
      <div class="visibility-wrap">
        <div class="visibility-score">
          <el-progress
            type="dashboard"
            :percentage="overallScore"
            :width="160"
            :stroke-width="12"
            :color="scoreColor(overallScore)"
          >
            <template #default="{ percentage }">
              <div class="score-inner">
                <span class="score-num">{{ percentage }}</span>
                <span class="score-unit">分</span>
              </div>
            </template>
          </el-progress>
          <p class="score-hint">综合可见度得分（0-100）</p>
        </div>

        <div class="visibility-platforms">
          <div v-for="p in platformScores" :key="p.model" class="platform-row">
            <div class="platform-head">
              <span class="platform-name">{{ modelDisplayName(p.model) }}</span>
              <span class="platform-score">{{ p.score }}<small>分</small></span>
            </div>
            <el-progress
              :percentage="p.score"
              :color="scoreColor(p.score)"
              :show-text="false"
              :stroke-width="8"
            />
            <div class="platform-meta">引用 {{ p.cited }} / {{ p.total }} 次</div>
          </div>
          <div v-if="!visibilityLoading && platformScores.length === 0" class="empty-tip">暂无可见度数据</div>
        </div>
      </div>
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

// === 服务商工作量统计（发稿量披露） ===
// 后端 /client/work-report 返回 { summary, items }：
//   summary: { total_distributions, this_month_distributions, total_questions, total_cited, citation_rate(0~1) }
//   items:   [{ title, url, distributed_at, questions[], citation_results[] }]
const workReport = ref({ summary: {}, items: [] })
const workLoading = ref(false)
const workSummary = computed(() => workReport.value.summary || {})
const workItems = computed(() => workReport.value.items || [])
// 引用率：后端返回 0~1 浮点数，渲染为百分比（与上方收录率口径一致）
const citationRatePercent = computed(() => {
  const rate = Number(workSummary.value.citation_rate) || 0
  const pct = Math.round(rate * 1000) / 10
  return Number.isInteger(pct) ? String(pct) : pct.toFixed(1)
})

// === AI 可见度得分 ===
// 后端 /client/visibility 返回 { overall_score(0-100), platform_scores[], radar_data }
//   platform_scores: [{ model, score, total, cited }]
const visibility = ref({ overall_score: 0, platform_scores: [], radar_data: { labels: [], values: [] } })
const visibilityLoading = ref(false)
const overallScore = computed(() => Number(visibility.value.overall_score) || 0)
const platformScores = computed(() => visibility.value.platform_scores || [])

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

// AI 平台 model code → 中文展示名（与后端 client_routes.MODEL_DISPLAY_NAMES 对齐）
const MODEL_DISPLAY_NAMES = {
  doubao: '豆包', qwen: '千问', ernie: '文心', wenxin: '文心',
  openai: 'OpenAI', chatgpt: 'ChatGPT', gemini: 'Gemini', claude: 'Claude',
  deepseek: 'DeepSeek', glm: '智谱GLM', spark: '讯飞星火', baichuan: '百川',
  minimax: 'MiniMax', moonshot: '月之暗面', kimi: 'Kimi',
}
function modelDisplayName(model) {
  if (!model) return '—'
  return MODEL_DISPLAY_NAMES[model] || model
}

// 命中类型 → Element Plus tag 类型：exact=success(绿) / domain=warning(黄) / none=info(灰)
function hitTypeTagType(type) {
  if (type === 'exact') return 'success'
  if (type === 'domain') return 'warning'
  if (type === 'none') return 'info'
  return 'info'
}
// 命中类型 → 符号：exact✓ / domain✓ / none✗
function hitTypeSymbol(type) {
  if (type === 'exact') return '✓'
  if (type === 'domain') return '✓'
  if (type === 'none') return '✗'
  return ''
}

// 得分 → 进度条颜色：≥70 绿 / ≥40 黄 / <40 红
function scoreColor(score) {
  const s = Number(score) || 0
  if (s >= 70) return '#10B981'
  if (s >= 40) return '#F59E0B'
  return '#EF4444'
}

async function fetchWorkReport() {
  workLoading.value = true
  try {
    const res = await clientViewApi.workReport()
    workReport.value = {
      summary: res.data.summary || {},
      items: res.data.items || [],
    }
  } catch (err) {
    console.error('获取工作量统计失败', err)
    ElMessage.error('获取工作量统计失败，请稍后重试')
  } finally {
    workLoading.value = false
  }
}

async function fetchVisibility() {
  visibilityLoading.value = true
  try {
    const res = await clientViewApi.visibility()
    visibility.value = {
      overall_score: res.data.overall_score || 0,
      platform_scores: res.data.platform_scores || [],
      radar_data: res.data.radar_data || { labels: [], values: [] },
    }
  } catch (err) {
    console.error('获取 AI 可见度失败', err)
    ElMessage.error('获取 AI 可见度失败，请稍后重试')
  } finally {
    visibilityLoading.value = false
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
  // 工作量统计与可见度独立于概览，并行加载、互不阻塞
  fetchWorkReport()
  fetchVisibility()
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

/* === 通用分区卡片（工作量统计 / 可见度得分） === */
.section-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-top: var(--space-md);
}
.section-card h3 {
  margin: 0 0 var(--space-sm) 0;
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

/* === 工作量统计 === */
.work-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-sm);
}
.mini-stat {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mini-stat-accent {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.06));
  border-color: rgba(99, 102, 241, 0.25);
}
.mini-label {
  font-size: var(--fs-small);
  color: var(--mute);
}
.mini-value {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 800;
  color: var(--ink);
  line-height: 1.1;
  font-variant-numeric: lining-nums;
}
.cell-link {
  color: var(--signal, #6366F1);
  text-decoration: none;
}
.cell-link:hover {
  text-decoration: underline;
}
.question-tag {
  margin: 2px 4px 2px 0;
  max-width: 100%;
}
.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.citation-tag {
  white-space: nowrap;
}
.mute-text {
  color: var(--mute);
  font-size: var(--fs-small);
}

/* === AI 可见度得分 === */
.visibility-wrap {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: var(--space-lg);
  align-items: start;
}
.visibility-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
}
.score-inner {
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.score-num {
  font-family: var(--font-display);
  font-size: 40px;
  font-weight: 800;
  color: var(--ink);
  line-height: 1;
  font-variant-numeric: lining-nums;
}
.score-unit {
  font-size: var(--fs-small);
  color: var(--mute);
}
.score-hint {
  margin: 0;
  color: var(--mute);
  font-size: var(--fs-small);
  text-align: center;
}
.visibility-platforms {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.platform-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.platform-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.platform-name {
  font-weight: 600;
  color: var(--ink);
}
.platform-score {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--ink);
  font-variant-numeric: lining-nums;
}
.platform-score small {
  font-size: var(--fs-small);
  color: var(--mute);
  font-weight: 500;
  margin-left: 2px;
}
.platform-meta {
  font-size: var(--fs-small);
  color: var(--mute);
}

@media (max-width: 768px) {
  .client-overview { padding: var(--space-sm); }
  .stats-grid { grid-template-columns: 1fr; }
  .work-stats-grid { grid-template-columns: repeat(2, 1fr); }
  .visibility-wrap { grid-template-columns: 1fr; }
  .visibility-score { align-items: center; }
}
</style>
