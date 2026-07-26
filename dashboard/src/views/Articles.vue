<template>
  <div style="padding: 20px;">
    <h2>文章列表</h2>
    <el-table :data="articles" style="width: 100%" @row-click="openModal" border>
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
    </el-table>
    <ArticleModal v-model="visible" :article="currentArticle" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'
import ArticleModal from '../components/ArticleModal.vue'

const articles = ref([])
const visible = ref(false)
const currentArticle = ref({})

onMounted(async () => {
  try {
    const res = await api.get('/articles')
    articles.value = res.data
  } catch (e) {
    console.error('加载文章失败', e)
  }
})

const openModal = (row) => {
  currentArticle.value = row
  visible.value = true
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
.citation-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.citation-count { font-size: 12px; color: #606266; }
.citation-count.muted { color: #c0c4cc; }
</style>
