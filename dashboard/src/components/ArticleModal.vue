<template>
  <el-dialog v-model="visible" :title="article.content_title || '文章详情'" width="75%" top="5vh">
    <el-descriptions :column="2" border>
      <el-descriptions-item label="发布时间">{{ formatTime(article.created_at) }}</el-descriptions-item>
      <el-descriptions-item label="URL">
        <a :href="article.url" target="_blank" rel="noopener" class="url-link">{{ article.url }}</a>
      </el-descriptions-item>
      <el-descriptions-item label="百度收录">
        <el-tag :type="statusTagType(article.baidu_status)" size="small" effect="dark">{{ statusLabel(article.baidu_status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="头条收录">
        <el-tag :type="statusTagType(article.toutiao_status)" size="small" effect="dark">{{ statusLabel(article.toutiao_status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="搜狗收录">
        <el-tag :type="statusTagType(article.sogou_status)" size="small" effect="dark">{{ statusLabel(article.sogou_status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="360收录">
        <el-tag :type="statusTagType(article.so360_status)" size="small" effect="dark">{{ statusLabel(article.so360_status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="必应收录">
        <el-tag :type="statusTagType(article.bing_status)" size="small" effect="dark">{{ statusLabel(article.bing_status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="AI 采信">
        <el-tag v-if="article.citation_status === 'cited'" type="success" effect="dark">已采信（{{ article.citation_exact }}/{{ article.citation_total }}）</el-tag>
        <el-tag v-else-if="article.citation_status === 'partial'" type="warning" effect="dark">部分引用（{{ article.citation_domain }}/{{ article.citation_total }}）</el-tag>
        <el-tag v-else-if="article.citation_status === 'not_cited'" type="danger" effect="dark">未采信（0/{{ article.citation_total }}）</el-tag>
        <el-tag v-else type="info" effect="dark">待检测</el-tag>
      </el-descriptions-item>
    </el-descriptions>

    <!-- AI 采信详情区域 -->
    <el-divider>AI 采信详情（{{ citationDetails.length }} 条记录）</el-divider>
    <el-table :data="citationDetails" v-loading="loadingCitations" border style="width: 100%">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="answer-detail">
            <div class="answer-label">🤖 AI 回答：</div>
            <div class="answer-content">{{ row.answer || '（无回答）' }}</div>
            <div v-if="row.sources" class="answer-sources">
              <strong>来源：</strong>{{ JSON.stringify(row.sources) }}
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="model" label="AI 模型" width="130">
        <template #default="{ row }">
          <el-tag size="small" type="primary" effect="plain">{{ modelLabel(row.model) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="question" label="检测问题" min-width="250" show-overflow-tooltip />
      <el-table-column label="命中类型" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="hitTypeTagType(row.hit_type)" size="small" effect="dark">
            {{ hitTypeLabel(row.hit_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="checked_at" label="检测时间" width="160">
        <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loadingCitations && citationDetails.length === 0" description="暂无 AI 采信检测记录" :image-size="60" />

    <el-divider>原文快照</el-divider>
    <div class="snapshot" v-html="article.content_snapshot"></div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" @click="viewOriginal">查看原文</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '@/api'

const props = defineProps({ modelValue: Boolean, article: Object })
const emit = defineEmits(['update:modelValue'])
const visible = ref(props.modelValue)

// AI 采信详情
const citationDetails = ref([])
const loadingCitations = ref(false)

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val && props.article?.url) {
    fetchCitationDetails(props.article.url)
  }
})
watch(visible, (val) => { emit('update:modelValue', val) })

async function fetchCitationDetails(url) {
  loadingCitations.value = true
  citationDetails.value = []
  try {
    const res = await api.get('/citations/detail', { params: { url } })
    citationDetails.value = res.data || []
  } catch (err) {
    console.error('加载采信详情失败', err)
    citationDetails.value = []
  } finally {
    loadingCitations.value = false
  }
}

// 命中类型：中文 + 颜色
function hitTypeLabel(t) {
  const map = { exact: '精确命中', domain: '域名命中', none: '未命中', unverifiable: '无法验证' }
  return map[t] || t || '—'
}
function hitTypeTagType(t) {
  if (t === 'exact') return 'success'   // 绿
  if (t === 'domain') return 'warning'  // 黄
  if (t === 'none') return 'danger'     // 红
  return 'info'                         // 灰
}

// 收录状态
function statusLabel(s) {
  const map = { indexed: '已收录', not_indexed: '未收录', failed: '未收录', pending: '待检测', checking: '检测中' }
  return map[s] || s || '—'
}
function statusTagType(s) {
  if (s === 'indexed') return 'success'
  if (s === 'not_indexed' || s === 'failed') return 'danger'
  if (s === 'pending' || s === 'checking') return 'info'
  return 'info'
}

// AI 模型名称中文化
function modelLabel(m) {
  const map = {
    qwen: '通义千问', deepseek: 'DeepSeek', chatgpt: 'ChatGPT',
    ernie: '文心一言', wenxin: '文心一言', glm: '智谱GLM',
    doubao: '豆包', spark: '讯飞星火', baichuan: '百川',
    minimax: 'MiniMax', moonshot: '月之暗面', kimi: 'Kimi',
  }
  return map[m?.toLowerCase()] || m || '未知'
}

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

const viewOriginal = () => {
  if (props.article.url) window.open(props.article.url, '_blank')
}
</script>

<style scoped>
.url-link { color: #409eff; text-decoration: none; }
.url-link:hover { text-decoration: underline; }
.snapshot { max-height: 300px; overflow-y: auto; padding: 12px; background: #f9f9f9; border-radius: 4px; }
.answer-detail { padding: 12px 20px; background: #f9f9f9; border-radius: 4px; }
.answer-label { font-weight: bold; color: #409eff; margin-bottom: 8px; }
.answer-content { white-space: pre-wrap; line-height: 1.6; color: #333; max-height: 200px; overflow-y: auto; }
.answer-sources { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ddd; font-size: 12px; color: #909399; }
</style>
