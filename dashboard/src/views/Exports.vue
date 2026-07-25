<!-- dashboard/src/views/Exports.vue -->
<!-- 缺口任务 5：导出报告页（列表 + 新建对话框 + 下载）。
     M4 主计划任务 4 的基础功能 + 缺口任务 5 的 ExportDialog 适配（不传 charts）。 -->
<template>
  <div class="exports-container">
    <div class="page-header">
      <h2>导出报告</h2>
      <el-button type="primary" @click="showDialog = true">
        <el-icon><Download /></el-icon> 新建导出
      </el-button>
    </div>

    <el-table :data="tasks" v-loading="loading" stripe>
      <el-table-column prop="export_type" label="格式" width="100">
        <template #default="{ row }">
          <el-tag>{{ row.export_type.toUpperCase() }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)">{{ getStatusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column prop="completed_at" label="完成时间" width="180" />
      <el-table-column label="文件大小" width="120">
        <template #default="{ row }">
          <span v-if="row.file_size">{{ formatFileSize(row.file_size) }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'completed'"
            type="primary"
            size="small"
            @click="handleDownload(row)"
          >下载</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 缺口任务 5：Exports 页面不传 charts（历史数据导出，无图表截图） -->
    <ExportDialog v-model="showDialog" :charts="{}" @created="fetchTasks" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import ExportDialog from '@/components/ExportDialog.vue'
import { api } from '@/api'

const loading = ref(false)
const tasks = ref([])
const showDialog = ref(false)

onMounted(fetchTasks)

async function fetchTasks() {
  loading.value = true
  try {
    const resp = await api.get('/exports', { params: { page: 1, page_size: 20 } })
    tasks.value = resp.data.items || []
  } catch {
    tasks.value = []
  } finally {
    loading.value = false
  }
}

function getStatusType(status) {
  return { completed: 'success', failed: 'danger', processing: 'warning', pending: 'info' }[status] || 'info'
}
function getStatusLabel(status) {
  return { completed: '已完成', failed: '失败', processing: '处理中', pending: '等待中' }[status] || status
}

function formatFileSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function handleDownload(task) {
  try {
    const resp = await api.get(`/exports/${task.task_id}/download`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `export_${task.task_id}.${task.export_type === 'pdf' ? 'pdf' : 'xlsx'}`
    a.click()
    window.URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('下载失败')
  }
}
</script>

<style scoped>
.exports-container { padding: 20px; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
</style>
