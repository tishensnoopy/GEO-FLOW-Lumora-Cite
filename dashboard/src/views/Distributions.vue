<template>
  <div class="distributions-page">
    <div class="page-header">
      <h2>分发记录</h2>
      <div class="header-actions">
        <!-- 手动刷新：分发记录与 GEOFlow 文章同步可能有延迟，
             提供显式刷新按钮让用户主动拉取最新数据 -->
        <el-button @click="manualRefresh" :loading="loading" title="从服务端重新拉取最新分发记录">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button type="primary" @click="openAddDialog" v-if="isAdmin">
          <el-icon><Plus /></el-icon>手动添加链接
        </el-button>
        <el-button
          type="warning" :disabled="selectedIds.length === 0"
          @click="openBatchScanDialog" v-if="isAdmin"
        >
          <el-icon><Refresh /></el-icon>批量检测 ({{ selectedIds.length }})
        </el-button>
        <!-- 批量删除：仅 admin 可见。选中含 GEOFlow 同步记录时禁用按钮——
             同步记录为跨 schema 只读，删除会破坏与 GEOFlow 的数据一致性。
             后端也独立防御（仅删 manual_distributions 表），此处为前端体验层防护。 -->
        <el-button
          type="danger" plain
          :disabled="batchDeleteDisabled"
          @click="batchDelete" v-if="isAdmin"
          :title="batchDeleteTitle"
        >
          <el-icon><Delete /></el-icon>批量删除 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>
    <div class="refresh-hint" v-if="refreshHintVisible">
      <el-icon><InfoFilled /></el-icon>
      <span>已重新拉取最新数据。若 GEOFlow 新分发的文章尚未同步，请稍等片刻后再次刷新（跨系统同步存在数秒延迟）。</span>
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
      <!-- AI 收录联动徽章：仅对 useAutoPipeline 追踪过的 URL（如刚手动添加的文章）展示。
           未追踪的行（如已存在的 GEOFlow 同步记录）显示占位符，避免误导用户。 -->
      <el-table-column label="AI 收录" width="110">
        <template #default="{ row }">
          <el-tag
            v-if="pipelineTracked(row.remote_url)"
            :type="pipelineTagType(row.remote_url)"
            size="small"
          >
            {{ pipelineTagLabel(row.remote_url) }}
          </el-tag>
          <span v-else class="text-muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button text size="small" @click="rescanOne(row)" title="重新扫描">
              <el-icon><Refresh /></el-icon>
            </el-button>
            <el-button text size="small" @click="viewCitation(row)" title="采信详情">
              <el-icon><View /></el-icon>
            </el-button>
            <!-- 编辑/删除仅对手动录入记录开放；GEOFlow 同步记录为跨 schema 只读，
                 编辑会破坏与 GEOFlow 的数据一致性，故禁用。 -->
            <el-button
              text size="small" @click="editRow(row)" title="编辑"
              :disabled="row.source !== 'manual'"
            >
              <el-icon><Edit /></el-icon>
            </el-button>
            <el-button
              text size="small" type="danger" @click="deleteRow(row)" title="删除"
              :disabled="row.source !== 'manual'"
            >
              <el-icon><Delete /></el-icon>
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
        <el-form-item label="文章标题">
          <el-input v-model="addForm.title" placeholder="选填，系统会自动抓取标题；若抓取失败（如反爬网站）可手动填写" />
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

    <!-- 编辑分发记录对话框（仅手动录入记录可编辑） -->
    <el-dialog v-model="editVisible" title="编辑分发记录" width="480px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="链接 URL">
          <el-input :model-value="editForm.remote_url" disabled />
        </el-form-item>
        <el-form-item label="关联客户">
          <el-select v-model="editForm.client_id" filterable placeholder="选择客户" style="width: 100%">
            <el-option v-for="c in clientOptions" :key="c.client_id" :label="`${c.client_id} (${c.company_name || c.username})`" :value="c.client_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="已同步" value="synced" />
            <el-option label="待处理" value="pending" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 采信详情对话框：展示该 URL 的全部采信记录，支持单条删除与清空重扫 -->
    <el-dialog v-model="citationVisible" title="AI 采信详情" width="780px" top="6vh">
      <div v-if="citationLoading" v-loading="true" style="height: 200px"></div>
      <template v-else>
        <div class="citation-summary" v-if="citationRows.length">
          <el-tag type="success">精确命中 {{ citationSummary.exact }}</el-tag>
          <el-tag type="warning">域名命中 {{ citationSummary.domain }}</el-tag>
          <el-tag type="danger">未命中 {{ citationSummary.none }}</el-tag>
          <el-tag type="info">不可验证 {{ citationSummary.unverifiable }}</el-tag>
          <el-button
            size="small" type="warning" plain
            @click="clearCitationByUrl(citationUrl)"
            style="margin-left: auto"
          >清空全部（用于重扫）</el-button>
        </div>
        <el-empty v-if="!citationRows.length" description="该链接暂无采信检测记录" />
        <el-table v-else :data="citationRows" border max-height="420" style="margin-top: 12px">
          <el-table-column prop="model" label="模型" width="100" />
          <el-table-column prop="question" label="检测问题" min-width="200" show-overflow-tooltip />
          <el-table-column label="命中" width="100">
            <template #default="{ row }">
              <el-tag :type="hitTagType(row.hit_type)" size="small">{{ hitLabel(row.hit_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="answer" label="AI 回答摘要" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="answer-cell">{{ (row.answer || '').slice(0, 80) }}{{ (row.answer || '').length > 80 ? '…' : '' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源数" width="80" align="center">
            <template #default="{ row }">{{ (row.sources || []).length }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button text size="small" type="danger" @click="deleteCitationRow(row)" title="删除">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, inject } from 'vue'
import { useStore } from 'vuex'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, View, Edit, Delete, InfoFilled } from '@element-plus/icons-vue'
import api from '@/api'
import StatusDot from '@/components/StatusDot.vue'
import { useAutoPipeline } from '@/composables/useAutoPipeline'

const store = useStore()

// 自动联动反馈：手动添加文章后追踪其收录检测进度，驱动列表行徽章。
// useAutoPipeline 为模块级单例，多组件共享同一份状态。
const { trackUrl: pipelineTrack, getStatus: pipelineStatus, isTracked: pipelineTracked } = useAutoPipeline()
// 全局扫描面板触发（由 App.vue 通过 provide('openScanPanel') 提供）
const openScanPanel = inject('openScanPanel', null)
// 修复：改用 Vuex store 的 role（响应式），原 localStorage 读取非响应式，
// 退出管理员后用客户登录时 isAdmin 仍为 true，显示管理员界面。
const isAdmin = computed(() => store.state.role === 'admin')

// ---------- 列表状态 ----------
const items = ref([])
const loading = ref(false)
const selectedIds = ref([])
// 保存选中行的完整数据，用于检测是否含 GEOFlow 同步记录（source='geoflow'）。
// 批量删除按钮在含同步记录时禁用，避免误删跨 schema 只读数据。
const selectedRows = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
// 刷新提示条：手动刷新后短暂展示，告知用户数据已更新及同步延迟说明
const refreshHintVisible = ref(false)

// ---------- 筛选 ----------
const filter = reactive({ client_id: '', source: '', dateRange: null })
const clientOptions = ref([])

// ---------- 手动添加 ----------
const addVisible = ref(false)
const submitting = ref(false)
const addFormRef = ref()
const addForm = reactive({ remote_url: '', client_id: '', title: '', note: '' })
const addRules = {
  remote_url: [{ required: true, message: '请输入链接 URL', trigger: 'blur' }],
  client_id: [{ required: true, message: '请选择关联客户', trigger: 'change' }],
}

// ---------- 批量检测 ----------
const scanVisible = ref(false)
const scanType = ref('index')

// ---------- 编辑分发记录 ----------
const editVisible = ref(false)
const editForm = reactive({ id: '', remote_url: '', client_id: '', status: 'synced', note: '' })

// ---------- 采信详情 ----------
const citationVisible = ref(false)
const citationLoading = ref(false)
const citationUrl = ref('')
const citationRows = ref([])
const citationSummary = reactive({ exact: 0, domain: 0, none: 0, unverifiable: 0 })

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

// 手动刷新：重新拉取当前页数据，并短暂展示同步延迟提示。
// 解决 GEOFlow 分发记录与文章列表同步缓慢、用户无法主动触发的体验问题。
async function manualRefresh() {
  await fetchList()
  refreshHintVisible.value = true
  ElMessage.success('已刷新分发记录')
  setTimeout(() => { refreshHintVisible.value = false }, 6000)
}

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
  selectedRows.value = rows
  selectedIds.value = rows.map(r => r.id).filter(Boolean)
}

// 选中行是否含 GEOFlow 同步记录（source !== 'manual'）。
// 同步记录来自 public.article_distributions（跨 schema 只读），不可删除。
const hasGeoflowInSelection = computed(() =>
  selectedRows.value.some(r => r.source !== 'manual')
)

// 批量删除按钮禁用条件：未选中任何行，或选中含 GEOFlow 同步记录。
const batchDeleteDisabled = computed(() =>
  selectedIds.value.length === 0 || hasGeoflowInSelection.value
)

// 按钮 hover 提示：解释为何禁用，引导用户取消同步记录的勾选。
const batchDeleteTitle = computed(() => {
  if (selectedIds.value.length === 0) return '请先勾选要删除的记录'
  if (hasGeoflowInSelection.value) {
    return '选中项含 GEOFlow 同步记录（跨 schema 只读），不可删除。请仅勾选手动录入记录。'
  }
  return '批量删除选中的手动录入记录'
})

function openAddDialog() {
  addForm.remote_url = ''
  addForm.client_id = ''
  addForm.title = ''
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
      title: addForm.title || null,
      note: addForm.note || null,
    })
    // 触发自动联动追踪：注册 URL 后 useAutoPipeline 开始轮询 aiIndexApi.listResults，
    // 列表行徽章会从「收录检测中」逐步过渡到「已收录/未收录/检测失败」。
    pipelineTrack(addForm.remote_url)
    ElMessage.success('文章已添加，正在自动触发 AI 收录检测...')
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

// 查看采信详情：拉取该 URL 的全部采信记录，展示并支持删除/清空重扫。
// 解决"采信黑盒"问题：用户能看到每条记录的模型、问题、命中类型、AI 回答摘要。
async function viewCitation(row) {
  citationUrl.value = row.remote_url
  citationVisible.value = true
  citationLoading.value = true
  citationRows.value = []
  try {
    const res = await api.get('/citations/detail', { params: { url: row.remote_url } })
    const data = res.data || []
    // /citations/detail 直接返回数组；兼容 {results: [...]} 结构
    citationRows.value = Array.isArray(data) ? data : (data.results || data.items || [])
    // 聚合命中统计
    const agg = { exact: 0, domain: 0, none: 0, unverifiable: 0 }
    citationRows.value.forEach(r => { if (agg[r.hit_type] !== undefined) agg[r.hit_type]++ })
    Object.assign(citationSummary, agg)
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载采信详情失败')
  } finally {
    citationLoading.value = false
  }
}

// 编辑分发记录：打开编辑对话框，预填当前值
function editRow(row) {
  editForm.id = row.id
  editForm.remote_url = row.remote_url
  editForm.client_id = row.client_id
  editForm.status = row.status || 'synced'
  editForm.note = row.note || ''
  editVisible.value = true
}

// 提交编辑：调用 PUT /admin/distributions/{id}
async function handleEdit() {
  submitting.value = true
  try {
    await api.put(`/admin/distributions/${editForm.id}`, {
      note: editForm.note,
      status: editForm.status,
      client_id: editForm.client_id,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

// 删除分发记录：二次确认后调用 DELETE /admin/distributions/{id}
async function deleteRow(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除该分发记录？\n${row.content_title || row.remote_url}\n删除后可重新手动添加。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return } // 用户取消
  try {
    await api.delete(`/admin/distributions/${row.id}`)
    ElMessage.success('已删除')
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

// 批量删除：仅删除手动录入记录。前端已禁用含 GEOFlow 同步记录的勾选场景，
// 后端也仅删 manual_distributions 表作独立防御。删除后清空选中并刷新列表。
async function batchDelete() {
  if (batchDeleteDisabled.value) return
  const count = selectedIds.value.length
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${count} 条手动录入记录？删除后可重新手动添加。\n注意：GEOFlow 同步记录不会被删除。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return } // 用户取消
  try {
    const res = await api.post('/admin/distributions/batch-delete', { ids: selectedIds.value })
    ElMessage.success(`已删除 ${res.data.deleted} 条`)
    selectedRows.value = []
    selectedIds.value = []
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '批量删除失败')
  }
}

// 删除单条采信记录
async function deleteCitationRow(row) {
  try {
    await ElMessageBox.confirm('确认删除该采信记录？', '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/admin/citation-results/${row.id}`)
    ElMessage.success('已删除')
    // 刷新采信详情
    viewCitation({ remote_url: citationUrl.value })
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

// 清空该 URL 的全部采信记录（用于重新扫描）
async function clearCitationByUrl(url) {
  try {
    await ElMessageBox.confirm(
      '确认清空该链接的全部采信记录？清空后可重新触发采信检测。',
      '清空确认',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await api.post('/admin/citation-results/batch-delete', { url })
    ElMessage.success('已清空')
    citationRows.value = []
    Object.assign(citationSummary, { exact: 0, domain: 0, none: 0, unverifiable: 0 })
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '清空失败')
  }
}

// 采信命中类型 → 中文标签 + 颜色
function hitLabel(t) {
  return { exact: '精确命中', domain: '域名命中', none: '未命中', unverifiable: '不可验证' }[t] || t
}
function hitTagType(t) {
  return { exact: 'success', domain: 'warning', none: 'danger', unverifiable: 'info' }[t] || 'info'
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

// === AI 收录联动徽章映射 ===
// pending(黄,检测中) / indexed(绿,已收录) / not_indexed(灰,未收录) / failed(红,检测失败)
function pipelineTagType(url) {
  const s = pipelineStatus(url)
  return { pending: 'warning', indexed: 'success', not_indexed: 'info', failed: 'danger' }[s] || 'info'
}
function pipelineTagLabel(url) {
  const s = pipelineStatus(url)
  return { pending: '收录检测中', indexed: '已收录', not_indexed: '未收录', failed: '检测失败' }[s] || s
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
.refresh-hint {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 12px; padding: 8px 12px;
  background: #ecf5ff; border: 1px solid #d9ecff; border-radius: 4px;
  color: #409eff; font-size: 13px;
}
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

/* 采信详情对话框：摘要条 + 回答摘要单元格 */
.citation-summary {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  padding: 10px 12px; background: #f4f4f5; border-radius: 4px;
}
.answer-cell { color: #606266; font-size: 12px; }

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
