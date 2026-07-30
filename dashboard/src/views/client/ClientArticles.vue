<template>
  <div class="client-articles">
    <!-- 页面头 -->
    <div class="page-header">
      <h2>我的文章</h2>
      <p class="page-subtitle">监测问题集与文章在 AI 搜索引擎中的收录情况</p>
    </div>

    <!-- 我的监测问题（只读） -->
    <el-card class="section-card" shadow="never" v-loading="questionsLoading">
      <h3>我的监测问题</h3>
      <el-table :data="questions" border style="width: 100%">
        <el-table-column type="index" label="#" width="60" align="center" />
        <el-table-column prop="question" label="监测问题" min-width="320" />
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!questionsLoading && questions.length === 0" class="empty-tip">
        暂无监测问题，请联系管理员配置
      </div>
    </el-card>

    <!-- 我的文章收录情况 -->
    <el-card class="section-card" shadow="never" v-loading="articlesLoading">
      <h3>我的文章收录</h3>
      <el-table :data="articles" border style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="url" label="URL" min-width="220" show-overflow-tooltip />
        <el-table-column prop="model" label="模型" width="110" />
        <el-table-column label="收录状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.index_status)">{{ statusLabel(row.index_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检测时间" width="180">
          <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="!articlesLoading && articles.length === 0" class="empty-tip">暂无文章收录数据</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { clientQuestionApi } from '@/api/clientQuestion'
import { clientViewApi } from '@/api/clientView'

const questions = ref([])
const articles = ref([])
const questionsLoading = ref(false)
const articlesLoading = ref(false)

function statusType(status) {
  if (status === 'indexed') return 'success'
  if (status === 'not_indexed') return 'danger'
  return 'info'
}

function statusLabel(status) {
  if (status === 'indexed') return '已收录'
  if (status === 'not_indexed') return '未收录'
  if (status === 'pending') return '待检测'
  if (!status) return '—'
  return status
}

function formatTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function fetchQuestions() {
  questionsLoading.value = true
  try {
    const res = await clientQuestionApi.listOwn()
    // 后端可能返回数组或 { items: [...] }
    const data = res.data
    questions.value = Array.isArray(data) ? data : (data.items || [])
  } catch (err) {
    console.error('获取监测问题失败', err)
    ElMessage.error('获取监测问题失败，请稍后重试')
  } finally {
    questionsLoading.value = false
  }
}

async function fetchArticles() {
  articlesLoading.value = true
  try {
    const res = await clientViewApi.overview()
    articles.value = res.data.articles || []
  } catch (err) {
    console.error('获取文章收录情况失败', err)
    ElMessage.error('获取文章收录情况失败，请稍后重试')
  } finally {
    articlesLoading.value = false
  }
}

onMounted(() => {
  fetchQuestions()
  fetchArticles()
})
</script>

<style scoped>
.client-articles {
  padding: var(--space-md) var(--space-lg) var(--space-lg);
  max-width: 1280px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-lg);
}
.page-header h2 {
  margin: 0;
  font-size: var(--fs-h1);
  color: var(--ink);
  letter-spacing: -0.02em;
}
.page-subtitle {
  margin: 4px 0 0;
  color: var(--mute);
  font-size: var(--fs-small);
}

.section-card {
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-md);
}

.section-card h3 {
  margin: 0 0 var(--space-sm) 0;
  font-size: var(--fs-h2);
  color: var(--ink);
  position: relative;
  padding-left: 14px;
  letter-spacing: -0.01em;
}
.section-card h3::before {
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

.empty-tip {
  text-align: center;
  color: var(--mute);
  padding: var(--space-lg);
  font-size: var(--fs-small);
}

@media (max-width: 768px) {
  .client-articles { padding: var(--space-sm); }
}
</style>
