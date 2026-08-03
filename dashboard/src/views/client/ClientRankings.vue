<template>
  <div class="client-rankings">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>回答快照</h2>
      <p class="page-subtitle">各 AI 平台对您监测问题的回答全文与引用情况</p>
    </div>

    <div class="rankings-body" v-loading="loading">
      <!-- 左侧：客户问题列表 -->
      <aside class="question-pane">
        <div class="pane-title">监测问题</div>
        <ul class="question-list" v-if="questions.length">
          <li
            v-for="(q, idx) in questions"
            :key="q.id || idx"
            class="question-item"
            :class="{ active: activeId === (q.id || idx) }"
            @click="selectQuestion(q.id, idx)"
          >
            <span class="q-index">{{ idx + 1 }}</span>
            <span class="q-text">{{ q.question || '未命名问题' }}</span>
            <el-tag
              v-if="answerCount(q) > 0"
              class="q-badge"
              size="small"
              type="info"
              effect="plain"
            >{{ answerCount(q) }}</el-tag>
          </li>
        </ul>
        <div v-else class="empty-tip">暂无监测问题</div>
      </aside>

      <!-- 右侧：选中问题的各平台 AI 回答 -->
      <section class="answer-pane">
        <template v-if="activeQuestion">
          <div class="answer-pane-header">
            <h3>{{ activeQuestion.question }}</h3>
            <span class="platform-count">共 {{ activeResults.length }} 个平台回答</span>
          </div>

          <div v-if="activeResults.length" class="answer-cards">
            <div
              v-for="(r, idx) in activeResults"
              :key="idx"
              class="answer-card"
              :class="['hit-' + (r.hit_type || 'none')]"
            >
              <div class="answer-card-head">
                <div class="platform-info">
                  <span class="platform-name">{{ modelDisplayName(r.model) }}</span>
                  <el-tag :type="hitTypeTagType(r.hit_type)" size="small" effect="dark">
                    {{ hitTypeLabel(r.hit_type) }}
                  </el-tag>
                  <!-- 阶段 4：置信度标签 -->
                  <el-tag
                    v-if="r.confidence_level && r.confidence_level !== 'uncalibrated'"
                    :type="getConfidenceTagType(r.confidence_level)"
                    size="small"
                  >
                    {{ getConfidenceLabel(r.confidence_level, r.confidence) }}
                  </el-tag>
                  <el-tag
                    v-else-if="r.confidence_level === 'uncalibrated'"
                    type="info"
                    size="small"
                  >
                    未校准
                  </el-tag>
                </div>
                <span v-if="isCited(r.hit_type)" class="cited-badge">已引用您的文章</span>
              </div>

              <div class="answer-block">
                <div class="block-label">AI 回答全文</div>
                <div class="answer-text">{{ r.answer || '（无回答内容）' }}</div>
              </div>

              <div class="answer-meta">
                <div class="meta-row" v-if="sourceUrls(r).length">
                  <span class="meta-label">引用来源：</span>
                  <a
                    v-for="(url, i) in sourceUrls(r)"
                    :key="i"
                    :href="url"
                    target="_blank"
                    rel="noopener"
                    class="source-link"
                  >{{ url }}</a>
                </div>
                <div class="meta-row" v-else-if="r.article_url">
                  <span class="meta-label">引用来源：</span>
                  <a :href="r.article_url" target="_blank" rel="noopener" class="source-link">{{ r.article_url }}</a>
                </div>
                <div class="meta-row" v-else>
                  <span class="meta-label">引用来源：</span>
                  <span class="mute-text">未引用</span>
                </div>
                <div class="meta-row">
                  <span class="meta-label">检测时间：</span>
                  <span>{{ formatTime(r.checked_at) }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="empty-tip">该问题暂无 AI 平台回答快照</div>
        </template>

        <div v-else-if="!loading" class="empty-tip">
          <p>请在左侧选择一个监测问题</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { clientViewApi } from '@/api/clientView'

// 后端 /client/rankings 返回 { questions: [{ id, question, results: [{ model, hit_type, answer, sources[], checked_at, article_url }] }] }
const questions = ref([])
const loading = ref(false)
const activeId = ref(null)

const activeQuestion = computed(() =>
  questions.value.find((q, idx) => (q.id ?? idx) === activeId.value) || null
)
const activeResults = computed(() => (activeQuestion.value && activeQuestion.value.results) || [])

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
function hitTypeLabel(type) {
  if (type === 'exact') return '精确命中'
  if (type === 'domain') return '域名命中'
  if (type === 'none') return '未命中'
  if (!type) return '—'
  return type
}

// 阶段 4：置信度标签辅助函数
const getConfidenceTagType = (level) => {
  switch (level) {
    case 'high': return 'success'
    case 'medium': return 'warning'
    case 'low': return 'danger'
    default: return 'info'
  }
}

const getConfidenceLabel = (level, confidence) => {
  const levelText = { high: '高置信度', medium: '中置信度', low: '低置信度' }
  return `${levelText[level] || ''} ${confidence}%`
}
// exact / domain 视为"已引用"
function isCited(type) {
  return type === 'exact' || type === 'domain'
}

function answerCount(q) {
  return (q.results && q.results.length) || 0
}

// 收集 sources 数组里的 URL（sources 可能是 [{url,title}] 或字符串数组，做兼容）
function sourceUrls(r) {
  const srcs = r.sources
  if (!Array.isArray(srcs) || srcs.length === 0) return []
  return srcs
    .map((s) => (typeof s === 'string' ? s : s && s.url))
    .filter(Boolean)
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function selectQuestion(id, idx) {
  // id 可能为 null（异常数据），回退用 idx 保证唯一可选中
  activeId.value = id ?? idx
}

async function fetchRankings() {
  loading.value = true
  try {
    const res = await clientViewApi.rankings()
    questions.value = res.data.questions || []
    // 默认选中第一个问题
    if (questions.value.length) {
      const first = questions.value[0]
      activeId.value = first.id ?? 0
    }
  } catch (err) {
    console.error('获取回答快照失败', err)
    ElMessage.error('获取回答快照失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(fetchRankings)
</script>

<style scoped>
.client-rankings {
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

/* === 双栏布局 === */
.rankings-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: var(--space-md);
  align-items: start;
}

/* 左侧问题列表 */
.question-pane {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-sm);
  position: sticky;
  top: calc(var(--topbar-height, 64px) + var(--space-sm));
  max-height: calc(100vh - var(--topbar-height, 64px) - var(--space-lg) * 2);
  overflow-y: auto;
}
.pane-title {
  font-size: var(--fs-small);
  color: var(--mute);
  font-weight: 600;
  letter-spacing: 0.08em;
  padding: var(--space-xs) var(--space-sm) var(--space-xs);
}
.question-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.question-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: 10px var(--space-sm);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--ink);
  transition: background var(--transition-fast, 0.15s), color var(--transition-fast, 0.15s);
  min-height: var(--touch-target, 44px);
}
.question-item:hover {
  background: var(--signal-soft, rgba(99, 102, 241, 0.08));
  color: var(--signal, #6366F1);
}
.question-item.active {
  background: var(--signal-soft, rgba(99, 102, 241, 0.12));
  color: var(--signal, #6366F1);
  font-weight: 600;
}
.q-index {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-pill, 999px);
  background: var(--ink-line, rgba(26, 26, 26, 0.08));
  color: var(--mute);
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.question-item.active .q-index {
  background: var(--grad-brand);
  color: #fff;
}
.q-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.q-badge {
  flex-shrink: 0;
}

/* 右侧回答区 */
.answer-pane {
  min-width: 0;
}
.answer-pane-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
  flex-wrap: wrap;
}
.answer-pane-header h3 {
  margin: 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.platform-count {
  font-size: var(--fs-small);
  color: var(--mute);
}

.answer-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

/* 单个平台回答卡片 */
.answer-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-left: 4px solid var(--mute);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-md);
  transition: box-shadow var(--transition-base, 0.2s);
}
.answer-card:hover {
  box-shadow: var(--shadow-hover, 0 8px 24px rgba(0, 0, 0, 0.08));
}
/* 命中类型左边框配色：exact=绿 / domain=黄 / none=灰 */
.answer-card.hit-exact { border-left-color: #10B981; }
.answer-card.hit-domain { border-left-color: #F59E0B; }
.answer-card.hit-none { border-left-color: #909399; }

.answer-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
  flex-wrap: wrap;
}
.platform-info {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}
.platform-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.cited-badge {
  font-size: var(--fs-small);
  font-weight: 600;
  color: #10B981;
  background: rgba(16, 185, 129, 0.12);
  padding: 2px 10px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
}

.answer-block {
  margin-bottom: var(--space-sm);
}
.block-label {
  font-size: var(--fs-small);
  color: var(--mute);
  margin-bottom: 6px;
}
.answer-text {
  color: var(--ink);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  background: rgba(99, 102, 241, 0.03);
  border-radius: var(--radius-md, 6px);
  padding: var(--space-sm) var(--space-md);
}

.answer-meta {
  border-top: 1px solid var(--ink-line);
  padding-top: var(--space-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.meta-row {
  display: flex;
  gap: 6px;
  font-size: var(--fs-small);
  color: var(--mute);
  flex-wrap: wrap;
  align-items: baseline;
}
.meta-label {
  flex-shrink: 0;
}
.source-link {
  color: var(--signal, #6366F1);
  text-decoration: none;
  word-break: break-all;
}
.source-link:hover {
  text-decoration: underline;
}
.source-link + .source-link {
  margin-left: 6px;
}
.mute-text {
  color: var(--mute);
  font-size: var(--fs-small);
}

.empty-tip {
  text-align: center;
  color: var(--mute);
  padding: var(--space-lg);
  font-size: var(--fs-small);
}

/* 响应式：移动端单栏堆叠 */
@media (max-width: 768px) {
  .client-rankings { padding: var(--space-sm); }
  .rankings-body {
    grid-template-columns: 1fr;
  }
  .question-pane {
    position: static;
    max-height: 280px;
  }
}
</style>
