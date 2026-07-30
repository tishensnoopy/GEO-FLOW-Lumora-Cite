<template>
  <!-- 审计日志页（admin 专用）。
       功能：列表展示管理员操作日志、按操作类型筛选、分页、按日期清理旧日志。
       数据来源：GET /admin/audit_logs（列表）、POST /admin/audit-logs/cleanup（清理）。 -->
  <div class="audit-logs-page">
    <div class="page-header">
      <h2>审计日志</h2>
      <div class="header-actions">
        <el-button @click="fetchLogs" :loading="loading" title="重新拉取日志">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button type="warning" plain @click="openCleanupDialog">
          <el-icon><Delete /></el-icon>按日期清理
        </el-button>
      </div>
    </div>

    <!-- 筛选栏：按操作类型筛选 -->
    <div class="filter-bar">
      <el-select
        v-model="filterAction" placeholder="按操作类型筛选" clearable
        style="width: 220px" @change="applyFilter"
      >
        <el-option v-for="a in actionOptions" :key="a" :label="a" :value="a" />
      </el-select>
      <el-button @click="resetFilter">重置</el-button>
    </div>

    <el-table :data="logs" v-loading="loading" border>
      <el-table-column prop="created_at" label="时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="admin_name" label="操作人" width="120" />
      <el-table-column prop="action" label="操作类型" width="200">
        <template #default="{ row }">
          <el-tag size="small">{{ row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target_type" label="对象类型" width="120" />
      <el-table-column prop="target_id" label="对象 ID" width="160" show-overflow-tooltip />
      <el-table-column label="详情" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="detail-cell">{{ formatDetail(row.detail) }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchLogs"
      />
    </div>

    <!-- 清理对话框：删除指定日期之前的日志（保留策略） -->
    <el-dialog v-model="cleanupVisible" title="清理旧审计日志" width="420px">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        此操作将永久删除指定日期之前的所有审计日志，不可恢复。请谨慎操作。
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="清理截止日期">
          <el-date-picker
            v-model="cleanupDate" type="date" placeholder="选择日期"
            value-format="YYYY-MM-DD" style="width: 100%"
          />
          <div class="hint">将删除该日期之前的全部日志（不含当天）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cleanupVisible = false">取消</el-button>
        <el-button type="danger" :loading="submitting" @click="handleCleanup">确认清理</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Delete } from '@element-plus/icons-vue'
import api from '@/api'

const logs = ref([])
const loading = ref(false)
const currentPage = ref(1)
const pageSize = ref(50)
const total = ref(0)
const filterAction = ref('')

// 清理对话框状态
const cleanupVisible = ref(false)
const cleanupDate = ref('')
const submitting = ref(false)

// 操作类型选项（覆盖系统中所有审计 action，便于筛选）
const actionOptions = [
  'create_client', 'update_client', 'deactivate_client', 'delete_client', 'restore_client',
  'reset_client_password',
  'create_client_site', 'update_client_site', 'delete_client_site',
  'manual_create_distribution', 'update_distribution', 'delete_distribution',
  'trigger_index_scan', 'trigger_citation_scan', 'batch_scan',
  'delete_citation_result', 'batch_delete_citation_results',
  'delete_index_result', 'batch_delete_index_results',
  'cleanup_audit_logs', 'create_export', 'sso_login',
]

onMounted(async () => {
  await fetchLogs()
})

async function fetchLogs() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (filterAction.value) params.action = filterAction.value
    const res = await api.get('/admin/audit_logs', { params })
    logs.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

// 筛选变更时重置到第 1 页，避免高页码返回空
async function applyFilter() {
  currentPage.value = 1
  await fetchLogs()
}

function resetFilter() {
  filterAction.value = ''
  currentPage.value = 1
  fetchLogs()
}

function openCleanupDialog() {
  cleanupDate.value = ''
  cleanupVisible.value = true
}

async function handleCleanup() {
  if (!cleanupDate.value) {
    ElMessage.warning('请选择清理截止日期')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除 ${cleanupDate.value} 之前的所有审计日志？此操作不可恢复。`,
      '清理确认',
      { type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消' }
    )
  } catch { return }
  submitting.value = true
  try {
    const res = await api.post('/admin/audit-logs/cleanup', { before_date: cleanupDate.value })
    ElMessage.success(`已清理 ${res.data.deleted} 条日志`)
    cleanupVisible.value = false
    fetchLogs()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '清理失败')
  } finally {
    submitting.value = false
  }
}

// detail 字段后端存为 JSON 字符串，格式化为可读形式
function formatDetail(detail) {
  if (!detail) return '—'
  try {
    const obj = typeof detail === 'string' ? JSON.parse(detail) : detail
    return JSON.stringify(obj)
  } catch {
    return String(detail)
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.audit-logs-page { padding: 20px; }
.page-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; }
.header-actions { display: flex; gap: 12px; }
.filter-bar {
  display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
}
.pagination-bar { margin-top: 20px; display: flex; justify-content: flex-end; }
.detail-cell { color: #606266; font-size: 12px; }
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
