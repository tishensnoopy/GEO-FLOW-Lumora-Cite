<template>
  <el-drawer
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    title="客户问题管理"
    size="480px"
    :close-on-click-modal="false"
  >
    <div v-loading="loading" class="question-list">
      <div
        v-for="(q, idx) in questions"
        :key="q.id"
        class="question-item"
        draggable="true"
        @dragstart="onDragStart(idx)"
        @dragover.prevent="onDragOver(idx)"
        @drop="onDrop(idx)"
        @dragend="onDragEnd"
      >
        <span class="drag-handle" title="拖拽排序">⠿</span>
        <el-input
          v-if="editingId === q.id"
          v-model="editText"
          size="small"
          @keyup.enter="saveEdit(q)"
          @blur="saveEdit(q)"
        />
        <span v-else class="question-text">{{ q.question }}</span>
        <el-switch
          v-model="q.status"
          active-value="active"
          inactive-value="inactive"
          @change="toggleStatus(q)"
        />
        <el-button v-if="editingId !== q.id" size="small" @click="startEdit(q)">编辑</el-button>
        <el-button v-else size="small" type="primary" @click="saveEdit(q)">保存</el-button>
        <el-button size="small" type="danger" class="delete-btn" @click="handleDelete(q)">删除</el-button>
      </div>
      <div v-if="!loading && questions.length === 0" class="empty-tip">
        暂无问题，请在下方添加
      </div>
    </div>

    <div class="add-section">
      <el-input
        v-model="newQuestion"
        placeholder="输入新问题后回车或点击添加"
        class="new-question-input"
        @keyup.enter="handleAdd"
      />
      <el-button type="primary" class="add-question-btn" @click="handleAdd">添加</el-button>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { clientQuestionApi } from '@/api/clientQuestion'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  clientId: { type: String, default: '' },
})
defineEmits(['update:modelValue'])

const questions = ref([])
const loading = ref(false)
const newQuestion = ref('')
const editingId = ref(null)
const editText = ref('')

// 拖拽状态（非响应式，避免无谓渲染）
let dragFromIndex = null
let dragMoved = false

watch(
  () => [props.modelValue, props.clientId],
  ([visible, cid]) => {
    if (visible && cid) loadQuestions(cid)
  },
  { immediate: true }
)

async function loadQuestions(cid) {
  loading.value = true
  try {
    const res = await clientQuestionApi.list(cid)
    const list = res.data || []
    questions.value = list
      .slice()
      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载问题列表失败')
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  const text = newQuestion.value.trim()
  if (!text) {
    ElMessage.warning('请输入问题内容')
    return
  }
  if (!props.clientId) return
  try {
    const res = await clientQuestionApi.create(props.clientId, { question: text })
    questions.value.push({
      id: res.data.id,
      question: res.data.question || text,
      sort_order: res.data.sort_order ?? questions.value.length,
      status: res.data.status || 'active',
    })
    newQuestion.value = ''
    ElMessage.success('已添加')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '添加失败')
  }
}

function startEdit(q) {
  editingId.value = q.id
  editText.value = q.question
}

async function saveEdit(q) {
  if (editingId.value !== q.id) return
  const text = editText.value.trim()
  if (!text) {
    ElMessage.warning('问题内容不能为空')
    return
  }
  try {
    await clientQuestionApi.update(props.clientId, q.id, { question: text })
    q.question = text
    editingId.value = null
    ElMessage.success('已保存')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存失败')
  }
}

async function toggleStatus(q) {
  try {
    await clientQuestionApi.update(props.clientId, q.id, { status: q.status })
    ElMessage.success('状态已更新')
  } catch (err) {
    // 回滚 UI 状态
    q.status = q.status === 'active' ? 'inactive' : 'active'
    ElMessage.error(err.response?.data?.detail || '状态更新失败')
  }
}

async function handleDelete(q) {
  try {
    await ElMessageBox.confirm(`确认删除问题「${q.question}」？`, '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await clientQuestionApi.delete(props.clientId, q.id)
    questions.value = questions.value.filter(item => item.id !== q.id)
    ElMessage.success('已删除')
  } catch (err) {
    // 用户取消
    if (err === 'cancel' || err?.message === 'cancel' || err === 'close') return
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

// ---------- 拖拽排序（HTML5 原生 API） ----------
function onDragStart(idx) {
  dragFromIndex = idx
  dragMoved = false
}

function onDragOver(idx) {
  // @dragover.prevent 已阻止默认行为；此处预留视觉反馈钩子
  void idx
}

function onDrop(idx) {
  if (dragFromIndex === null || dragFromIndex === idx) return
  const moved = questions.value.splice(dragFromIndex, 1)[0]
  questions.value.splice(idx, 0, moved)
  dragMoved = true
  // 同步本地 sort_order
  questions.value.forEach((q, i) => { q.sort_order = i })
}

async function onDragEnd() {
  const fromIndex = dragFromIndex
  dragFromIndex = null
  if (!dragMoved) return
  dragMoved = false
  try {
    const orderedIds = questions.value.map(q => q.id)
    await clientQuestionApi.reorder(props.clientId, orderedIds)
    ElMessage.success('排序已更新')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '排序保存失败，已回滚')
    if (props.clientId) await loadQuestions(props.clientId)
  }
  void fromIndex
}
</script>

<style scoped>
.question-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 4px 8px;
  min-height: 120px;
}
.question-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 6px;
  background: var(--el-bg-color, #fff);
  cursor: grab;
}
.question-item:active {
  cursor: grabbing;
}
.drag-handle {
  color: var(--el-text-color-placeholder, #c0c4cc);
  font-size: 16px;
  line-height: 1;
  user-select: none;
}
.question-text {
  flex: 1;
  word-break: break-all;
  font-size: 14px;
}
.empty-tip {
  color: var(--el-text-color-placeholder, #c0c4cc);
  font-size: 13px;
  text-align: center;
  padding: 24px 0;
}
.add-section {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding: 12px 4px 0;
  border-top: 1px solid var(--el-border-color, #dcdfe6);
}
.add-section .new-question-input {
  flex: 1;
}
</style>
