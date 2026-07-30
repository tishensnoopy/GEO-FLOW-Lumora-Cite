<template>
  <teleport to="body">
    <!-- 背景遮罩 -->
    <div class="scan-overlay" v-if="visible" @click="close"></div>
    <!-- 右侧滑出面板 -->
    <transition name="slide">
      <div class="scan-panel" v-if="visible">
        <!-- 头部 -->
        <div class="panel-header">
          <h3>扫描运行状态</h3>
          <button class="close-btn" @click="close" aria-label="关闭">×</button>
        </div>

        <!-- 进度区 -->
        <div class="panel-progress">
          <div class="progress-ring">
            <svg width="64" height="64" viewBox="0 0 64 64">
              <circle cx="32" cy="32" r="28" fill="none" stroke="rgba(26,26,26,0.1)" stroke-width="6" />
              <circle
                cx="32" cy="32" r="28" fill="none"
                class="progress-circle"
                :class="progressColorClass"
                stroke-width="6"
                stroke-linecap="round"
                :stroke-dasharray="175.9"
                :stroke-dashoffset="175.9 - (175.9 * progressPercent / 100)"
                transform="rotate(-90 32 32)"
              />
            </svg>
            <div class="ring-text">{{ progressPercent }}%</div>
          </div>
          <div class="progress-info">
            <div class="info-row">
              <span class="info-text">{{ task.processed }} / {{ task.total }} 已处理</span>
              <span class="success-count">✓ {{ task.success }}</span>
              <span class="failed-count" v-if="task.failed > 0">✗ {{ task.failed }}</span>
            </div>
            <div class="info-meta">
              <span class="meta-tag" v-if="task.scan_type">类型: {{ scanTypeText }}</span>
              <span class="meta-tag" v-if="elapsed">耗时: {{ elapsed }}s</span>
            </div>
          </div>
        </div>

        <!-- 三阶段进度环（all 类型：index → ai_index → citation 顺序执行） -->
        <div class="phase-rings" v-if="taskIds">
          <div
            class="phase-ring"
            v-for="(tid, phase) in taskIds"
            :key="phase"
            :class="phaseStatus(phase)"
          >
            <div class="phase-icon">{{ phaseIcon(phase) }}</div>
            <div class="phase-label">{{ phaseLabel(phase) }}</div>
          </div>
        </div>

        <!-- 引擎状态卡片（仅收录扫描显示） -->
        <div class="engine-status" v-if="task.scan_type === 'index' || task.scan_type === 'both'">
          <div class="section-title">搜索引擎收录状态</div>
          <div class="engine-grid">
            <div v-for="engine in engines" :key="engine.name" class="engine-item">
              <span class="engine-dot" :class="engine.status"></span>
              <span class="engine-name">{{ engine.name }}</span>
              <span class="engine-result">{{ engine.result }}</span>
            </div>
          </div>
        </div>

        <!-- 采信模型状态卡片（仅采信扫描显示，阶段 4 - ⑤） -->
        <!-- 从 task.citation_models 结构化读取 stage 4 probe 结果，
             替代从日志文本脆弱解析。后端 citation_checker stage 4 逐模型上报。 -->
        <div
          class="engine-status"
          v-if="task.scan_type === 'citation' || task.scan_type === 'both'"
        >
          <div class="section-title">
            AI 采信模型状态
            <span class="section-hint" v-if="!task.citation_models || task.citation_models.length === 0">
              等待模型探测…
            </span>
          </div>
          <div class="engine-grid" v-if="task.citation_models && task.citation_models.length > 0">
            <div
              v-for="m in task.citation_models"
              :key="m.model"
              class="engine-item"
              :title="m.error || citationModelTip(m.status)"
            >
              <span class="engine-dot" :class="citationModelDotClass(m.status)"></span>
              <span class="engine-name">{{ m.model }}</span>
              <span class="engine-result">{{ citationModelResult(m.status) }}</span>
            </div>
          </div>
        </div>

        <!-- 终端日志区 -->
        <div class="terminal-window" ref="terminalRef">
          <div v-for="(log, idx) in task.logs" :key="idx" class="log-line" :class="`log-${log.level}`">
            <span class="log-time">{{ formatTime(log.timestamp) }}</span>
            <span class="log-message">{{ log.message }}</span>
          </div>
          <div v-if="task.status === 'running'" class="log-line log-running">
            <span class="log-cursor">▌</span>
            <span class="log-message">扫描进行中...</span>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import api from '@/api'

const props = defineProps({
  modelValue: Boolean,
  taskId: String,
  taskIds: { type: Object, default: null }, // all 类型: {index, ai_index, citation} | null
})
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})
const terminalRef = ref(null)
let pollTimer = null
// 各阶段独立轮询 timer（key 为 phase 名称）
let phasePollTimers = {}

const task = reactive({
  task_id: '', scan_type: '', status: 'running',
  total: 0, processed: 0, success: 0, failed: 0,
  logs: [], citation_models: [], created_at: null, updated_at: null,
})

// all 类型三阶段状态：index → ai_index → citation 顺序执行
// 每阶段独立轮询 status，更新 phaseStatuses 用于进度环高亮
const phaseStatuses = reactive({
  index: 'pending',
  ai_index: 'pending',
  citation: 'pending',
})

const scanTypeText = computed(() => ({
  index: '收录检测', citation: 'AI采信检测', both: '收录+采信',
  ai_index: 'AI 收录检测', all: '全量扫描',
}[task.scan_type] || task.scan_type))

// 阶段进度环辅助：phaseStatus 由 phaseStatuses 实时驱动
function phaseStatus(phase) {
  return phaseStatuses[phase] || 'pending'
}
function phaseIcon(phase) {
  const s = phaseStatuses[phase]
  if (s === 'completed') return '✓'
  if (s === 'failed') return '✗'
  if (s === 'active') return '⏳'
  return '○'
}
function phaseLabel(phase) {
  return {
    index: '收录',
    ai_index: 'AI 收录',
    citation: '采信',
  }[phase] || phase
}

const progressPercent = computed(() => {
  if (task.total === 0) return 0
  // clamp 到 [0, 100]：后端已修正 total 与实际检测数一致，但保留前端防御，
  // 避免任何瞬态不一致（如并发进度更新）导致进度环和百分比显示 >100% 或负数。
  const pct = Math.round((task.processed / task.total) * 100)
  return Math.max(0, Math.min(100, pct))
})

const progressColorClass = computed(() => {
  if (task.status === 'failed') return 'progress-failed'
  return 'progress-normal'
})

const elapsed = computed(() => {
  if (!task.created_at || !task.updated_at) return null
  const c = new Date(task.created_at)
  const u = new Date(task.updated_at)
  return ((u - c) / 1000).toFixed(1)
})

// 引擎状态（从日志解析，简化版）
const engines = computed(() => {
  const engineNames = ['百度', '头条', '搜狗', '360', '必应']
  return engineNames.map(name => {
    const log = task.logs.find(l => l.message.includes(name))
    let status = 'pending'
    let result = '◌'
    if (log) {
      if (log.message.includes('收录确认') || log.message.includes('SUCCESS')) {
        status = 'success'; result = '✓'
      } else if (log.message.includes('未收录')) {
        status = 'failed'; result = '✗'
      } else if (log.message.includes('检测中') || log.message.includes('INFO')) {
        status = 'running'; result = '⏳'
      }
    }
    return { name, status, result }
  })
})

// 采信模型状态展示辅助（阶段 4 - ⑤）
// 后端 probe 状态：verified / error / no_search / search_without_sources
function citationModelDotClass(status) {
  return {
    verified: 'success',
    error: 'failed',
    no_search: 'pending',
    search_without_sources: 'running',
    unknown: 'pending',
  }[status] || 'pending'
}
function citationModelResult(status) {
  return {
    verified: '✓',
    error: '✗',
    no_search: '◌',
    search_without_sources: '⏳',
    unknown: '◌',
  }[status] || '◌'
}
function citationModelTip(status) {
  return {
    verified: '已通过联网搜索验证，可用于引用检测',
    error: 'Key 不可用或探测失败，该模型本轮可能无法返回来源',
    no_search: 'Key 有效但未检测到联网搜索能力',
    search_without_sources: '模型联网搜索但未返回来源 URL',
    unknown: '未知状态',
  }[status] || '未知状态'
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
}

async function fetchStatus() {
  if (!props.taskId) return
  try {
    const res = await api.get(`/admin/scan/status/${props.taskId}`)
    Object.assign(task, res.data)
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
    if (task.status === 'completed' || task.status === 'failed') {
      stopPolling()
    }
  } catch (err) {
    console.error('获取扫描状态失败:', err)
    stopPolling()
  }
}

function startPolling() {
  stopPolling()
  fetchStatus()
  pollTimer = setInterval(fetchStatus, 2000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
function close() {
  visible.value = false
  stopPolling()
  stopPhasePolling()
}

// 阶段轮询：taskIds 存在时，为每个 phase 独立轮询 status，更新 phaseStatuses
async function fetchPhaseStatus(phase, tid) {
  if (!tid) return
  try {
    const res = await api.get(`/admin/scan/status/${tid}`)
    const status = res.data?.status
    if (status === 'completed') {
      phaseStatuses[phase] = 'completed'
      // 该阶段完成，停止其独立轮询
      if (phasePollTimers[phase]) {
        clearInterval(phasePollTimers[phase])
        delete phasePollTimers[phase]
      }
    } else if (status === 'running') {
      phaseStatuses[phase] = 'active'
    } else if (status === 'failed') {
      // 失败：独立标记为 failed（红 ✗），与 completed 视觉区分，停止该阶段轮询
      phaseStatuses[phase] = 'failed'
      if (phasePollTimers[phase]) {
        clearInterval(phasePollTimers[phase])
        delete phasePollTimers[phase]
      }
    }
  } catch (err) {
    console.error(`获取阶段 ${phase} 状态失败:`, err)
  }
}
function startPhasePolling() {
  stopPhasePolling()
  if (!props.taskIds) return
  Object.keys(props.taskIds).forEach((phase) => {
    const tid = props.taskIds[phase]
    if (!tid) return
    // 初始为 pending，立即拉取一次以同步状态
    fetchPhaseStatus(phase, tid)
    phasePollTimers[phase] = setInterval(() => fetchPhaseStatus(phase, tid), 2000)
  })
}
function stopPhasePolling() {
  Object.keys(phasePollTimers).forEach((phase) => {
    clearInterval(phasePollTimers[phase])
    delete phasePollTimers[phase]
  })
}
function resetPhaseStatuses() {
  phaseStatuses.index = 'pending'
  phaseStatuses.ai_index = 'pending'
  phaseStatuses.citation = 'pending'
}

watch(() => props.taskId, (newId) => {
  if (newId) {
    Object.assign(task, {
      task_id: '', scan_type: '', status: 'running',
      total: 0, processed: 0, success: 0, failed: 0,
      logs: [], citation_models: [], created_at: null, updated_at: null,
    })
    startPolling()
  }
})
watch(() => props.modelValue, (v) => {
  if (v && props.taskId) startPolling()
  else if (!v) stopPolling()
  if (v && props.taskIds) startPhasePolling()
  else if (!v) stopPhasePolling()
})
watch(() => props.taskIds, (newVal) => {
  resetPhaseStatuses()
  if (newVal && props.modelValue) startPhasePolling()
  else stopPhasePolling()
}, { deep: true })
onUnmounted(() => {
  stopPolling()
  stopPhasePolling()
})
</script>

<style scoped>
.scan-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 200;
}
.scan-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--scan-panel-width-desktop);
  background: var(--paper);
  z-index: 201;
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.08);
}
@media (max-width: 1279px) {
  .scan-panel { width: var(--scan-panel-width-tablet); }
}
@media (max-width: 768px) {
  .scan-panel { width: 100%; }
}

/* 滑出动画 */
.slide-enter-active, .slide-leave-active {
  transition: transform var(--transition-slow);
}
.slide-enter-from, .slide-leave-to {
  transform: translateX(100%);
}

/* 头部 */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  height: 48px;
  flex-shrink: 0;
}
.panel-header h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--fs-h2);
}
.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  color: var(--mute);
  cursor: pointer;
  padding: 4px 8px;
  min-width: var(--touch-target);
  min-height: var(--touch-target);
  border-radius: var(--radius-sm);
  transition: color var(--transition-fast), background var(--transition-fast);
}
.close-btn:hover {
  color: var(--alert);
  background: var(--alert-soft);
}

/* 进度区 */
.panel-progress {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  flex-shrink: 0;
}
.progress-ring {
  position: relative;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
}
.ring-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.progress-circle { stroke: var(--signal); }
.progress-circle.progress-failed { stroke: var(--alert); }
.progress-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.info-row {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
  font-size: var(--fs-body);
}
.info-text { color: var(--ink); }
.success-count { color: var(--signal); font-weight: 600; }
.failed-count { color: var(--alert); font-weight: 600; }
.info-meta { display: flex; gap: var(--space-sm); }
.meta-tag {
  font-size: var(--fs-small);
  color: var(--mute);
  background: var(--paper);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

/* 引擎状态 */
.engine-status {
  padding: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  flex-shrink: 0;
}

/* 三阶段进度环（all 类型） */
.phase-rings {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-md);
  border-bottom: 1px solid var(--ink-line);
  flex-shrink: 0;
}
.phase-ring {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-xs);
  background: var(--surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--ink-line);
  opacity: 0.5;
  transition: opacity var(--transition-fast), border-color var(--transition-fast);
}
.phase-ring.completed {
  opacity: 1;
  border-color: var(--status-indexed);
}
.phase-ring.active {
  opacity: 1;
  border-color: var(--signal);
}
.phase-ring.failed {
  opacity: 1;
  border-color: var(--alert);
}
.phase-icon {
  font-size: 18px;
  font-weight: 700;
  color: var(--mute);
}
.phase-ring.completed .phase-icon { color: var(--status-indexed); }
.phase-ring.active .phase-icon { color: var(--signal); }
.phase-ring.failed .phase-icon { color: var(--alert); }
.phase-label {
  font-size: var(--fs-small);
  color: var(--ink);
}
.section-title {
  font-size: var(--fs-small);
  color: var(--mute);
  margin-bottom: var(--space-xs);
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}
.section-hint {
  font-size: var(--fs-small);
  color: var(--mute);
  font-weight: normal;
}
.engine-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-xs);
}
.engine-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--space-xs);
  background: var(--surface);
  border-radius: var(--radius-md);
  border: 1px solid var(--ink-line);
}
.engine-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.engine-dot.pending { background: transparent; border: 1px solid var(--mute); }
.engine-dot.running { background: var(--status-partial); animation: pulse 1.5s infinite; }
.engine-dot.success { background: var(--status-indexed); }
.engine-dot.failed { background: var(--alert); }
.engine-name { font-size: 11px; color: var(--ink); }
.engine-result { font-size: 14px; font-weight: 600; }

/* 终端日志区 */
.terminal-window {
  flex: 1;
  background: var(--terminal-bg);
  padding: var(--space-md);
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-mono);
  line-height: 1.6;
  color: var(--terminal-text);
}
.terminal-window::-webkit-scrollbar { width: 8px; }
.terminal-window::-webkit-scrollbar-track { background: #1a2a28; }
.terminal-window::-webkit-scrollbar-thumb { background: #3a4a48; border-radius: 4px; }

.log-line {
  display: flex;
  gap: var(--space-xs);
  margin-bottom: 2px;
}
.log-time { color: #888; flex-shrink: 0; }
.log-message { word-break: break-all; }
.log-info .log-message { color: #d4d4d4; }
.log-success .log-message { color: #4ec9b0; }
.log-warning .log-message { color: #dcdcaa; }
.log-error .log-message { color: #f44747; }
.log-running .log-cursor {
  color: #4ec9b0;
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
