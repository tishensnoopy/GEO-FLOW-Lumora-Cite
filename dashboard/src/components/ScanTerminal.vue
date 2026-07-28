<template>
  <el-dialog v-model="visible" title="扫描运行状态" width="800px" :close-on-click-modal="false" @close="onClose">
    <div class="scan-terminal">
      <!-- 进度条 -->
      <div class="scan-progress">
        <div class="progress-info">
          <span class="status-badge" :class="statusClass">{{ statusText }}</span>
          <span class="progress-text">{{ task.processed }} / {{ task.total }} 已处理</span>
          <span class="success-count">✓ {{ task.success }}</span>
          <span class="failed-count" v-if="task.failed > 0">✗ {{ task.failed }}</span>
          <span class="scan-type-tag" v-if="task.scan_type">类型: {{ scanTypeText }}</span>
        </div>
        <el-progress :percentage="progressPercent" :status="progressStatus" :stroke-width="8" />
      </div>

      <!-- 终端日志窗口 -->
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

    <template #footer>
      <el-button v-if="task.status === 'running'" disabled>扫描进行中...</el-button>
      <el-button v-else type="primary" @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onUnmounted } from 'vue'
import api from '@/api'

const props = defineProps({
  modelValue: Boolean,
  taskId: String,
})

const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const terminalRef = ref(null)
let pollTimer = null

const task = reactive({
  task_id: '',
  scan_type: '',
  status: 'running',
  total: 0,
  processed: 0,
  success: 0,
  failed: 0,
  logs: [],
})

const statusClass = computed(() => ({
  running: 'status-running',
  completed: 'status-completed',
  failed: 'status-failed',
}[task.status] || 'status-running'))

const statusText = computed(() => ({
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}[task.status] || '运行中'))

const scanTypeText = computed(() => ({
  index: '收录检测',
  citation: 'AI采信检测',
  both: '收录+采信',
}[task.scan_type] || task.scan_type))

const progressPercent = computed(() => {
  if (task.total === 0) return 0
  return Math.round((task.processed / task.total) * 100)
})

const progressStatus = computed(() => {
  if (task.status === 'running') return ''
  if (task.failed > 0) return 'warning'
  return 'success'
})

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${h}:${m}:${s}.${ms}`
}

async function fetchStatus() {
  if (!props.taskId) return
  try {
    const res = await api.get(`/admin/scan/status/${props.taskId}`)
    Object.assign(task, res.data)

    // 自动滚动到底部
    await nextTick()
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }

    // 扫描完成，停止轮询
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
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function onClose() {
  stopPolling()
}

watch(() => props.taskId, (newId) => {
  if (newId) {
    // 重置状态
    Object.assign(task, {
      task_id: '',
      scan_type: '',
      status: 'running',
      total: 0,
      processed: 0,
      success: 0,
      failed: 0,
      logs: [],
    })
    startPolling()
  }
})

watch(() => props.modelValue, (visible) => {
  if (!visible) {
    stopPolling()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.scan-terminal {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.scan-progress {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}

.status-badge {
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.status-running {
  background: #e6f7ff;
  color: #1890ff;
  border: 1px solid #91d5ff;
}

.status-completed {
  background: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}

.status-failed {
  background: #fff2f0;
  color: #ff4d4f;
  border: 1px solid #ffccc7;
}

.success-count {
  color: #52c41a;
  font-weight: 600;
}

.failed-count {
  color: #ff4d4f;
  font-weight: 600;
}

.scan-type-tag {
  color: #666;
  font-size: 12px;
}

.terminal-window {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px 16px;
  height: 350px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.terminal-window::-webkit-scrollbar {
  width: 8px;
}

.terminal-window::-webkit-scrollbar-track {
  background: #2d2d2d;
}

.terminal-window::-webkit-scrollbar-thumb {
  background: #555;
  border-radius: 4px;
}

.log-line {
  display: flex;
  gap: 8px;
  margin-bottom: 2px;
}

.log-time {
  color: #888;
  flex-shrink: 0;
}

.log-message {
  word-break: break-all;
}

.log-info .log-message {
  color: #d4d4d4;
}

.log-success .log-message {
  color: #4ec9b0;
}

.log-warning .log-message {
  color: #dcdcaa;
}

.log-error .log-message {
  color: #f44747;
}

.log-running .log-cursor {
  color: #4ec9b0;
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>
