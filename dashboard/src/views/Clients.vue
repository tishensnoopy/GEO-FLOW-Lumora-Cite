<template>
  <div class="clients-page">
    <div class="page-header">
      <h2>客户管理</h2>
      <div class="header-actions">
        <el-switch v-model="includeDeleted" active-text="显示已删除" @change="fetchClients" />
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>创建客户
        </el-button>
      </div>
    </div>

    <!-- 客户列表 -->
    <el-table :data="clients" v-loading="loading" border style="width: 100%">
      <el-table-column prop="client_id" label="客户 ID" width="140" />
      <el-table-column prop="username" label="用户名" width="110" />
      <el-table-column prop="company_name" label="公司名称" min-width="140" show-overflow-tooltip />
      <el-table-column label="服务期" width="200">
        <template #default="{ row }">
          <div v-if="row.service_start_date && row.service_end_date" class="service-period">
            <div>{{ row.service_start_date }} ~ {{ row.service_end_date }}</div>
          </div>
          <span v-else class="muted">未设置</span>
        </template>
      </el-table-column>
      <el-table-column label="服务状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="serviceStatusType(row)" size="small" effect="dark">
            {{ serviceStatusLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="账号状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最后登录" width="150">
        <template #default="{ row }">
          {{ row.last_login_at ? formatTime(row.last_login_at) : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="340" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
          <el-button size="small" type="warning" @click="openPasswordDialog(row)">改密码</el-button>
          <el-button size="small" type="primary" plain @click="openQuestionDrawer(row)">问题管理</el-button>
          <el-button
            v-if="row.status !== 'deleted'"
            size="small" type="danger" @click="handleDelete(row)"
          >删除</el-button>
          <el-button
            v-else
            size="small" type="success" @click="handleRestore(row)"
          >恢复</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchClients"
      />
    </div>

    <!-- 创建客户对话框 -->
    <el-dialog v-model="createVisible" title="创建客户" width="520px">
      <el-form :model="createForm" label-width="100px" ref="createFormRef" :rules="createRules">
        <el-form-item label="客户 ID" prop="client_id">
          <el-input v-model="createForm.client_id" placeholder="登录用唯一标识，如 client_001" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="客户用户名（唯一）" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 8 位，含大小写+数字" />
        </el-form-item>
        <el-form-item label="公司名称">
          <el-input v-model="createForm.company_name" placeholder="选填" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="createForm.contact_name" placeholder="选填" />
        </el-form-item>
        <el-form-item label="联系邮箱">
          <el-input v-model="createForm.contact_email" placeholder="选填，唯一" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="createForm.contact_phone" placeholder="选填" />
        </el-form-item>
        <el-form-item label="服务开始日期">
          <el-date-picker
            v-model="createForm.service_start_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择服务开始日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="服务结束日期">
          <el-date-picker
            v-model="createForm.service_end_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择服务结束日期"
            style="width: 100%"
            :disabled-date="(d) => createForm.service_start_date && d < new Date(createForm.service_start_date)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑客户对话框 -->
    <el-dialog v-model="editVisible" title="编辑客户" width="520px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="客户 ID">
          <el-input :value="editForm.client_id" disabled />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input :value="editForm.username" disabled />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="活跃" value="active" />
            <el-option label="停用" value="inactive" />
          </el-select>
        </el-form-item>
        <el-form-item label="公司名称">
          <el-input v-model="editForm.company_name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="editForm.contact_name" />
        </el-form-item>
        <el-form-item label="联系邮箱">
          <el-input v-model="editForm.contact_email" placeholder="唯一" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="editForm.contact_phone" />
        </el-form-item>
        <el-form-item label="服务开始日期">
          <el-date-picker
            v-model="editForm.service_start_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择服务开始日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="服务结束日期">
          <el-date-picker
            v-model="editForm.service_end_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择服务结束日期"
            style="width: 100%"
            :disabled-date="(d) => editForm.service_start_date && d < new Date(editForm.service_start_date)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码对话框 -->
    <el-dialog v-model="passwordVisible" title="重置密码" width="420px">
      <p style="margin-bottom: 16px; color: #666;">
        正在重置客户 <b>{{ passwordForm.client_id }}</b> 的密码
      </p>
      <el-form :model="passwordForm" label-width="80px">
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.new_password" type="password" show-password placeholder="至少 8 位，含大小写+数字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleResetPassword">重置</el-button>
      </template>
    </el-dialog>

    <!-- 客户问题管理抽屉 -->
    <QuestionDrawer v-model="questionDrawerVisible" :client-id="currentQuestionClientId" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '@/api'
import QuestionDrawer from '@/components/QuestionDrawer.vue'

// ---------- 列表状态 ----------
const clients = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const includeDeleted = ref(false)

// ---------- 创建客户 ----------
const createVisible = ref(false)
const submitting = ref(false)
const createFormRef = ref()
const createForm = reactive({
  client_id: '', username: '', password: '',
  company_name: '', contact_name: '', contact_email: '', contact_phone: '',
  service_start_date: '', service_end_date: '',
})
const createRules = {
  client_id: [{ required: true, message: '请输入客户 ID', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, message: '至少 8 位', trigger: 'blur' },
    {
      validator: (_, val, cb) => {
        if (!/[A-Z]/.test(val) || !/[a-z]/.test(val) || !/[0-9]/.test(val)) {
          cb(new Error('需含大写、小写字母和数字'))
        } else { cb() }
      }, trigger: 'blur',
    },
  ],
}

// ---------- 编辑客户 ----------
const editVisible = ref(false)
const editForm = reactive({
  client_id: '', username: '', status: 'active',
  company_name: '', contact_name: '', contact_email: '', contact_phone: '',
  service_start_date: '', service_end_date: '',
})

// ---------- 重置密码 ----------
const passwordVisible = ref(false)
const passwordForm = reactive({ client_id: '', new_password: '' })

// ---------- 客户问题管理抽屉 ----------
const questionDrawerVisible = ref(false)
const currentQuestionClientId = ref('')

function openQuestionDrawer(row) {
  currentQuestionClientId.value = row.client_id
  questionDrawerVisible.value = true
}

// ---------- 生命周期 ----------
onMounted(() => fetchClients())

// ---------- 方法 ----------
async function fetchClients() {
  loading.value = true
  try {
    const res = await api.get('/admin/clients', {
      params: { include_deleted: includeDeleted.value, page: page.value, page_size: pageSize.value },
    })
    clients.value = res.data.items || []
    total.value = res.data.total || clients.value.length
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '加载客户列表失败')
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  Object.assign(createForm, {
    client_id: '', username: '', password: '',
    company_name: '', contact_name: '', contact_email: '', contact_phone: '',
    service_start_date: '', service_end_date: '',
  })
  createVisible.value = true
}

async function handleCreate() {
  await createFormRef.value?.validate()
  submitting.value = true
  try {
    await api.post('/admin/clients', createForm)
    ElMessage.success('客户创建成功')
    createVisible.value = false
    fetchClients()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '创建失败')
  } finally {
    submitting.value = false
  }
}

function openEditDialog(row) {
  Object.assign(editForm, {
    client_id: row.client_id, username: row.username, status: row.status,
    company_name: row.company_name || '', contact_name: row.contact_name || '',
    contact_email: row.contact_email || '', contact_phone: row.contact_phone || '',
    service_start_date: row.service_start_date || '',
    service_end_date: row.service_end_date || '',
  })
  editVisible.value = true
}

async function handleEdit() {
  submitting.value = true
  try {
    await api.put(`/admin/clients/${editForm.client_id}`, {
      status: editForm.status,
      company_name: editForm.company_name,
      contact_name: editForm.contact_name,
      contact_email: editForm.contact_email,
      contact_phone: editForm.contact_phone,
      service_start_date: editForm.service_start_date || null,
      service_end_date: editForm.service_end_date || null,
    })
    ElMessage.success('保存成功')
    editVisible.value = false
    fetchClients()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

function openPasswordDialog(row) {
  passwordForm.client_id = row.client_id
  passwordForm.new_password = ''
  passwordVisible.value = true
}

async function handleResetPassword() {
  if (!passwordForm.new_password || passwordForm.new_password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  submitting.value = true
  try {
    await api.put(`/admin/clients/${passwordForm.client_id}/password`, {
      new_password: passwordForm.new_password,
    })
    ElMessage.success('密码已重置')
    passwordVisible.value = false
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '重置失败')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`确认删除客户 ${row.client_id}？删除后客户无法登录（可恢复）`, '确认删除', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
  try {
    await api.delete(`/admin/clients/${row.client_id}`)
    ElMessage.success('客户已删除')
    fetchClients()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败')
  }
}

async function handleRestore(row) {
  try {
    await api.put(`/admin/clients/${row.client_id}`, { status: 'active' })
    ElMessage.success('客户已恢复')
    fetchClients()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '恢复失败')
  }
}

// ---------- 服务期状态计算 ----------
function serviceStatusLabel(row) {
  if (row.status === 'deleted') return '已删除'
  if (row.status === 'inactive') return '已停用'
  if (!row.service_end_date) return '未设置'
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const end = new Date(row.service_end_date)
  const diffDays = Math.ceil((end - now) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return '已过期'
  if (diffDays <= 30) return `${diffDays}天后到期`
  return '服务中'
}
function serviceStatusType(row) {
  if (row.status === 'deleted') return 'danger'
  if (row.status === 'inactive') return 'info'
  if (!row.service_end_date) return 'info'
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const end = new Date(row.service_end_date)
  const diffDays = Math.ceil((end - now) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return 'danger'   // 红：已过期
  if (diffDays <= 30) return 'warning' // 黄：即将到期
  return 'success'                     // 绿：服务中
}

function statusLabel(s) {
  return { active: '活跃', inactive: '停用', deleted: '已删除' }[s] || s
}
function statusTagType(s) {
  return { active: 'success', inactive: 'warning', deleted: 'danger' }[s] || 'info'
}
function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.clients-page { padding: 20px; }
.page-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px;
}
.page-header h2 { margin: 0; }
.header-actions { display: flex; align-items: center; gap: 16px; }
.pagination-bar { margin-top: 20px; display: flex; justify-content: flex-end; }
.muted { color: #c0c4cc; font-size: 12px; }
.service-period { font-size: 12px; line-height: 1.4; }
</style>
