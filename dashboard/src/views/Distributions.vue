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
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <StatusDot :status="getStatusType(row)" />
        </template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button text size="small" @click="rescanOne(row)" title="重新扫描">
              <el-icon><Refresh /></el-icon>
            </el-button>
            <el-button text size="small" @click="viewCitation(row)" title="采信详情">
              <el-icon><View /></el-icon>
            </el-button>
            <el-button text size="small" @click="editRow(row)" title="编辑">
              <el-icon><Edit /></el-icon>
            </el-button>
          </div>
        </template>
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

    <!-- 扫描面板已由 AppLayout 的 ScanPanel 全局承载，本页不再内嵌扫描终端 -->
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, inject } from 'vue'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, View, Edit, InfoFilled } from '@element-plus/icons-vue'
import api from '@/api'
import StatusDot from '@/components/StatusDot.vue'

const store = useStore()
// 全局扫描面板触发（由 App.vue 通过 provide('openScanPanel') 提供）
const openScanPanel = inject('openScanPanel', null)
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
    ElMessage.success(`已开始检测 ${res.data.queued} 条链接`)
    scanVisible.value = false
    // 触发全局扫描面板（由 App.vue 的 AppLayout 提供）
    if (openScanPanel) openScanPanel(res.data.task_id)
    // 刷新列表（扫描结果会异步更新）
    setTimeout(() => fetchList(), 5000)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量检测失败')
  } finally {
    submitting.value = false
  }
}

// 单条重新扫描：触发全局扫描面板
async function rescanOne(row) {
  try {
    const res = await api.post('/admin/distributions/batch-scan', {
      distribution_ids: [row.id],
      scan_type: 'index',
    })
    ElMessage.success(`已开始检测: ${row.content_title || row.remote_url}`)
    if (openScanPanel) openScanPanel(res.data.task_id)
  } catch (err) {
    ElMessage.error('扫描失败: ' + (err.response?.data?.detail || err.message))
  }
}

function viewCitation(row) {
  ElMessage.info(`采信详情功能开发中: ${row.content_title || row.remote_url}`)
}

function editRow(row) {
  ElMessage.info(`编辑功能开发中: ${row.content_title || row.remote_url}`)
}

// 从 row.index_status（如 {baidu: 'indexed', ...}）聚合三态：
// 全部未收录 → pending；部分收录 → partial；全部收录 → indexed
function getStatusType(row) {
  const status = row.index_status || {}
  const engines = ['baidu', 'toutiao', 'sogou', 'so360', 'bing']
  const indexed = engines.filter(e => status[e] === 'indexed')
  if (indexed.length === 0) return 'pending'
  if (indexed.length < engines.length) return 'partial'
  return 'indexed'
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

/* 内联操作按钮组 */
.row-actions { display: flex; gap: 4px; }
.row-actions .el-button { padding: 4px; }

/* === 移动端：表格转卡片式 === */
@media (max-width: 768px) {
  /* 隐藏表头 */
  :deep(.el-table .el-table__header-wrapper) { display: none; }
  /* 行转卡片 */
  :deep(.el-table .el-table__row) {
    display: flex;
    flex-wrap: wrap;
    padding: var(--space-sm);
    border: 1px solid var(--ink-line);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-sm);
  }
  /* 单元格转行：label 在左、value 在右 */
  :deep(.el-table .el-table__cell) {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100% !important;
    border: none !important;
    padding: 4px 0 !important;
  }
  /* 通过 data-label 显示列名（需列配置 data-label，否则为空） */
  :deep(.el-table .el-table__cell::before) {
    content: attr(data-label);
    font-size: 11px;
    color: var(--mute);
    margin-right: var(--space-sm);
  }
  .row-actions .el-button {
    min-width: var(--touch-target);
    min-height: var(--touch-target);
  }
}
</style>
