<template>
  <div class="distributions-page">
    <div class="page-header">
      <h2>分发记录</h2>
      <div class="header-actions" v-if="isAdmin">
        <el-button type="primary" @click="openAddDialog">
          <el-icon><Plus /></el-icon>手动添加链接
        </el-button>
        <el-button
          type="warning" :disabled="selectedIds.length === 0"
          @click="openBatchScanDialog"
        >
          <el-icon><Refresh /></el-icon>批量检测 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 筛选栏（仅 admin 可见客户筛选） -->
    <div class="filter-bar">
      <el-select v-if="isAdmin" v-model="filter.client_id" placeholder="按客户筛选" clearable style="width: 180px" @change="applyFilter">
        <el-option v-for="c in clientOptions" :key="c.client_id" :label="`${c.client_id} (${c.company_name || c.username})`" :value="c.client_id" />
      </el-select>
      <el-select v-model="filter.source" placeholder="按来源筛选" clearable style="width: 140px" @change="applyFilter">
        <el-option label="手动录入" value="manual" />
        <el-option label="GEOFlow 同步" value="geoflow" />
      </el-select>
      <el-date-picker
        v-model="filter.dateRange" type="daterange" range-separator="至"
        start-placeholder="开始日期" end-placeholder="结束日期"
        value-format="YYYY-MM-DD" style="width: 260px" @change="applyFilter"
      />
      <el-button @click="resetFilter">重置</el-button>
    </div>

    <!-- 分发记录列表 -->
    <el-table :data="pagedItems" v-loading="loading" border @selection-change="onSelectionChange">
      <el-table-column type="selection" width="45" />
      <el-table-column prop="content_title" label="文章标题" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.content_title">{{ row.content_title }}</span>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="remote_url" label="链接 URL" min-width="300" show-overflow-tooltip>
        <template #default="{ row }">
          <a :href="row.remote_url" target="_blank" rel="noopener" class="url-link">{{ row.remote_url }}</a>
        </template>
      </el-table-column>
      <el-table-column prop="client_id" label="客户" width="140" />
      <el-table-column label="来源" width="100">
        <template #default="{ row }">
          <el-tag :type="row.source === 'manual' ? 'warning' : 'success'" size="small">
            {{ row.source === 'manual' ? '手动' : 'GEOFlow' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="distStatusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>

    <!-- 后端分页 -->
    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchList"
      />
    </div>

    <!-- 手动添加链接对话框 -->
    <el-dialog v-model="addVisible" title="手动添加监测链接" width="520px">
      <el-form :model="addForm" label-width="80px" ref="addFormRef" :rules="addRules">
        <el-form-item label="链接 URL" prop="remote_url">
          <el-input v-model="addForm.remote_url" placeholder="https://example.com/article/xxx" />
        </el-form-item>
        <el-form-item label="关联客户" prop="client_id">
          <el-select v-model="addForm.client_id" filterable placeholder="选择客户（必选）" style="width: 100%">
            <el-option v-for="c in clientOptions" :key="c.client_id" :label="`${c.client_id} (${c.company_name || c.username})`" :value="c.client_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="addForm.note" type="textarea" :rows="2" placeholder="选填，如文章标题、发布渠道等" />
        </el-form-item>
      </el-form>
      <div class="dialog-tip">
        <el-icon><InfoFilled /></el-icon>
        添加后系统会自动开始监测该链接的搜索引擎收录情况。
      </div>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleAdd">添加</el-button>
      </template>
    </el-dialog>

    <!-- 批量检测对话框 -->
    <el-dialog v-model="scanVisible" title="批量检测" width="420px">
      <p style="margin-bottom: 16px;">
        将对选中的 <b>{{ selectedIds.length }}</b> 条链接执行检测：
      </p>
      <el-form label-width="80px">
        <el-form-item label="检测类型">
          <el-radio-group v-model="scanType">
            <el-radio value="index">收录检测</el-radio>
            <el-radio value="citation">AI 采信检测</el-radio>
            <el-radio value="both">两者都检测</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scanVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleBatchScan">开始检测</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, InfoFilled } from '@element-plus/icons-vue'
import api from '@/api'

const store = useStore()
// 修复：改用 Vuex store 的 role（响应式），原 localStorage 读取非响应式，
// 退出管理员后用客户登录时 isAdmin 仍为 true，显示管理员界面。
const isAdmin = computed(() => store.state.role === 'admin')

// ---------- 列表状态 ----------
const items = ref([])
const loading = ref(false)
const selectedIds = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// ---------- 筛选 ----------
const filter = reactive({ client_id: '', source: '', dateRange: null })
const clientOptions = ref([])

// ---------- 手动添加 ----------
const addVisible = ref(false)
const submitting = ref(false)
const addFormRef = ref()
const addForm = reactive({ remote_url: '', client_id: '', note: '' })
const addRules = {
  remote_url: [{ required: true, message: '请输入链接 URL', trigger: 'blur' }],
  client_id: [{ required: true, message: '请选择关联客户', trigger: 'change' }],
}

// ---------- 批量检测 ----------
const scanVisible = ref(false)
const scanType = ref('index')

// ---------- 生命周期 ----------
onMounted(async () => {
  if (isAdmin.value) await fetchClients()
  await fetchList()
})

async function fetchClients() {
  try {
    const res = await api.get('/admin/clients', { params: { page: 1, page_size: 200 } })
    clientOptions.value = res.data.items || []
  } catch { /* admin 未登录时忽略 */ }
}

async function fetchList() {
  loading.value = true
  try {
    // admin 用 /admin/distributions（跨客户），client 用 /distributions（仅自己）
    const endpoint = isAdmin.value ? '/admin/distributions' : '/distributions'
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (filter.client_id) params.client_id = filter.client_id
    if (filter.source) params.source = filter.source
    if (filter.dateRange && filter.dateRange.length === 2) {
      params.date_from = filter.dateRange[0]
      params.date_to = filter.dateRange[1]
    }
    const res = await api.get(endpoint, { params })
    items.value = res.data.items || []
    total.value = res.data.total || items.value.length
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载分发记录失败')
  } finally {
    loading.value = false
  }
}

// 后端分页：直接用 items，不需要前端 slice
const pagedItems = computed(() => items.value)

// 修复：筛选条件变更时重置到第 1 页，避免停留在高页码导致筛选结果为空。
// 原 @change="fetchList" 直接请求当前页，若原在第 3 页筛选后只剩 1 页会返回空。
async function applyFilter() {
  currentPage.value = 1
  await fetchList()
}

function resetFilter() {
  filter.client_id = ''
  filter.source = ''
  filter.dateRange = null
  currentPage.value = 1
  fetchList()
}

function onSelectionChange(rows) {
  selectedIds.value = rows.map(r => r.id)
}

function openAddDialog() {
  addForm.remote_url = ''
  addForm.client_id = ''
  addForm.note = ''
  addVisible.value = true
}

async function handleAdd() {
  await addFormRef.value?.validate()
  submitting.value = true
  try {
    await api.post('/distributions', {
      remote_url: addForm.remote_url,
      client_id: addForm.client_id,
      note: addForm.note || null,
    })
    ElMessage.success('链接已添加，系统将开始监测')
    addVisible.value = false
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '添加失败')
  } finally {
    submitting.value = false
  }
}

function openBatchScanDialog() {
  scanType.value = 'index'
  scanVisible.value = true
}

async function handleBatchScan() {
  submitting.value = true
  try {
    const res = await api.post('/admin/distributions/batch-scan', {
      distribution_ids: selectedIds.value,
      scan_type: scanType.value,
    })
    ElMessage.success(`已入队 ${res.data.queued} 条检测任务`)
    scanVisible.value = false
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量检测失败')
  } finally {
    submitting.value = false
  }
}

function distStatusType(s) {
  return { synced: 'success', pending: 'warning', failed: 'danger' }[s] || 'info'
}
function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.distributions-page { padding: 20px; }
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
.url-link { color: #409eff; text-decoration: none; }
.url-link:hover { text-decoration: underline; }
.text-muted { color: #c0c4cc; }
.dialog-tip {
  margin-top: 12px; padding: 10px 12px; background: #f4f4f5;
  border-radius: 4px; color: #909399; font-size: 13px;
  display: flex; align-items: center; gap: 6px;
}
</style>
