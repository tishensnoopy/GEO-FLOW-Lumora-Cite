<template>
  <div style="padding: 20px;">
    <div class="page-header">
      <h2>文章列表</h2>
      <div class="header-actions">
        <!-- 手动刷新：文章列表与 GEOFlow 分发记录同步可能有延迟，
             提供显式刷新按钮让用户主动拉取最新数据 -->
        <el-button @click="manualRefresh" :loading="loading" title="重新拉取文章列表">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <!-- 批量删除收录结果：admin 专用。删除后可重新触发收录检测。 -->
        <el-button
          v-if="isAdmin" type="danger" plain :disabled="selectedIds.length === 0"
          @click="batchDelete"
        >
          <el-icon><Delete /></el-icon>批量删除 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>
    <div class="refresh-hint" v-if="refreshHintVisible">
      <el-icon><InfoFilled /></el-icon>
      <span>已重新拉取文章列表。若新分发的文章尚未出现，请稍等片刻后再次刷新（跨系统同步存在数秒延迟）。</span>
    </div>
    <el-table
      :data="articles" style="width: 100%" v-loading="loading"
      @row-click="openModal" border
      @selection-change="onSelectionChange"
    >
      <el-table-column v-if="isAdmin" type="selection" width="45" />
      <el-table-column prop="content_title" label="文章标题" min-width="200" show-overflow-tooltip />
      <el-table-column label="百度" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.baidu_status)" size="small" effect="dark">
            {{ statusLabel(row.baidu_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="头条" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.toutiao_status)" size="small" effect="dark">
            {{ statusLabel(row.toutiao_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="搜狗" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.sogou_status)" size="small" effect="dark">
            {{ statusLabel(row.sogou_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="360" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.so360_status)" size="small" effect="dark">
            {{ statusLabel(row.so360_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="必应" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.bing_status)" size="small" effect="dark">
            {{ statusLabel(row.bing_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="AI 采信" width="140" align="center">
        <template #default="{ row }">
          <div class="citation-cell">
            <el-tag :type="citationTagType(row.citation_status)" size="small" effect="dark">
              {{ citationLabel(row.citation_status) }}
            </el-tag>
            <div v-if="row.citation_total > 0" class="citation-count">
              {{ row.citation_exact || 0 }}/{{ row.citation_total }} 次命中
            </div>
            <div v-else class="citation-count muted">待检测</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="检测时间" width="160">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column v-if="isAdmin" label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <!-- 删除收录结果（硬删除，可重新检测）。点击时阻止冒泡，避免触发行点击打开详情。 -->
          <el-button text size="small" type="danger" @click.stop="deleteRow(row)" title="删除">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <ArticleModal v-model="visible" :article="currentArticle" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, InfoFilled, Delete } from '@element-plus/icons-vue'
import api from '../api'
import ArticleModal from '../components/ArticleModal.vue'

const store = useStore()
// admin 才显示删除/批量删除；普通客户只读
const isAdmin = computed(() => store.state.role === 'admin')

const articles = ref([])
const visible = ref(false)
const currentArticle = ref({})
const loading = ref(false)
const selectedIds = ref([])
// 刷新提示条：手动刷新后短暂展示同步延迟说明
const refreshHintVisible = ref(false)

async function fetchArticles() {
  loading.value = true
  try {
    const res = await api.get('/articles')
    articles.value = res.data
  } catch (e) {
    console.error('加载文章失败', e)
    ElMessage.error('加载文章失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await fetchArticles()
})

// 手动刷新：重新拉取文章列表，并短暂展示同步延迟提示。
async function manualRefresh() {
  await fetchArticles()
  refreshHintVisible.value = true
  ElMessage.success('已刷新文章列表')
  setTimeout(() => { refreshHintVisible.value = false }, 6000)
}

function onSelectionChange(rows) {
  selectedIds.value = rows.map(r => r.id).filter(Boolean)
}

const openModal = (row) => {
  currentArticle.value = row
  visible.value = true
}

// 删除单条收录结果
async function deleteRow(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除该收录记录？\n${row.content_title || row.url}\n删除后可重新触发收录检测。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await api.delete(`/admin/index-results/${row.id}`)
    ElMessage.success('已删除')
    fetchArticles()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

// 批量删除收录结果
async function batchDelete() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${selectedIds.value.length} 条收录记录？删除后可重新触发收录检测。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    const res = await api.post('/admin/index-results/batch-delete', { ids: selectedIds.value })
    ElMessage.success(`已删除 ${res.data.deleted} 条`)
    selectedIds.value = []
    fetchArticles()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量删除失败')
  }
}

// 收录状态：中文标签 + 颜色映射
function statusLabel(s) {
  const map = {
    indexed: '已收录',
    not_indexed: '未收录',
    failed: '未收录',
    pending: '待检测',
    checking: '检测中',
  }
  return map[s] || s || '—'
}

function statusTagType(s) {
  if (s === 'indexed') return 'success'   // 绿色
  if (s === 'not_indexed' || s === 'failed') return 'danger'  // 红色
  if (s === 'pending' || s === 'checking') return 'info'  // 灰色
  return 'info'
}

// AI 采信状态
function citationLabel(s) {
  const map = {
    cited: '已采信',
    not_cited: '未采信',
    pending: '待检测',
    none: '未采信',
  }
  return map[s] || s || '—'
}

function citationTagType(s) {
  if (s === 'cited') return 'success'   // 绿色
  if (s === 'not_cited' || s === 'none') return 'danger'  // 红色
  return 'info'  // 灰色
}

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.page-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; }
.header-actions { display: flex; gap: 12px; }
.refresh-hint {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 12px; padding: 8px 12px;
  background: #ecf5ff; border: 1px solid #d9ecff; border-radius: 4px;
  color: #409eff; font-size: 13px;
}
.citation-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.citation-count { font-size: 12px; color: #606266; }
.citation-count.muted { color: #c0c4cc; }
</style>
