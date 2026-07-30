<template>
  <div class="ai-index-table">
    <!-- 筛选栏：url 输入 + model 下拉 + status 下拉 + 查询按钮 -->
    <el-card class="filter-card" shadow="never">
      <div class="filter-bar">
        <el-input
          v-model="localFilters.url"
          placeholder="按 URL 关键词筛选"
          clearable
          class="filter-url"
        />
        <el-select
          v-model="localFilters.model"
          placeholder="按模型筛选"
          clearable
          class="filter-model"
        >
          <el-option
            v-for="m in modelOptions"
            :key="m"
            :label="m"
            :value="m"
          />
        </el-select>
        <el-select
          v-model="localFilters.index_status"
          placeholder="按收录状态筛选"
          clearable
          class="filter-status"
        >
          <el-option label="已收录" value="indexed" />
          <el-option label="未收录" value="not_indexed" />
          <el-option label="待检测" value="pending" />
        </el-select>
        <el-button type="primary" @click="emitFilter">查询</el-button>
      </div>
    </el-card>

    <!-- 结果列表 -->
    <el-card class="result-card" shadow="never">
      <h3>检测结果</h3>
      <el-table :data="items" border v-loading="loading" style="width: 100%">
        <el-table-column prop="url" label="URL" min-width="240" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" width="120" />
        <el-table-column label="收录状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.index_status)" size="small">
              {{ statusLabel(row.index_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="checked_at" label="检测时间" width="180">
          <template #default="{ row }">
            {{ row.checked_at ? formatTime(row.checked_at) : '—' }}
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-bar">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="emitPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'
import dayjs from 'dayjs'

const props = defineProps({
  items: { type: Array, default: () => [] },
  filters: {
    type: Object,
    default: () => ({ url: '', model: '', index_status: '' }),
  },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  modelOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['filter-change', 'page-change'])

// 本地筛选状态：双向同步父组件 filters
const localFilters = reactive({ ...props.filters })
watch(
  () => props.filters,
  (v) => Object.assign(localFilters, v),
  { deep: true },
)

function emitFilter() {
  emit('filter-change', { ...localFilters })
}

function emitPageChange(p) {
  emit('page-change', p)
}

function statusType(status) {
  if (status === 'indexed') return 'success'
  if (status === 'not_indexed') return 'danger'
  return 'info'
}

function statusLabel(status) {
  if (status === 'indexed') return '已收录'
  if (status === 'not_indexed') return '未收录'
  if (status === 'pending') return '待检测'
  return status || '—'
}

function formatTime(t) {
  return dayjs(t).format('YYYY-MM-DD HH:mm')
}

// 暴露纯函数供单元测试验证颜色/标签映射（不改变运行时行为）
defineExpose({ statusType, statusLabel })
</script>

<style scoped>
.ai-index-table {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.filter-card,
.result-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  padding: var(--space-md);
  box-shadow: var(--shadow-card);
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-sm);
}
.filter-url { flex: 1 1 260px; min-width: 200px; }
.filter-model { width: 160px; }
.filter-status { width: 180px; }

.result-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.result-card h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 20px;
  background: var(--grad-brand);
  border-radius: var(--radius-pill);
}

.pagination-bar {
  margin-top: var(--space-md);
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-url,
  .filter-model,
  .filter-status { width: 100%; }
  .pagination-bar { justify-content: center; }
}
</style>
