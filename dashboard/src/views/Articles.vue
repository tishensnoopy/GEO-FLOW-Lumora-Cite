<template>
  <div style="padding: 20px;">
    <h2>文章列表</h2>
    <el-table :data="articles" style="width: 100%" @row-click="openModal">
      <el-table-column prop="content_title" label="文章标题" />
      <el-table-column prop="baidu_status" label="百度" />
      <el-table-column prop="toutiao_status" label="头条" />
      <el-table-column prop="sogou_status" label="搜狗" />
      <el-table-column prop="so360_status" label="360" />
      <el-table-column prop="bing_status" label="必应" />
      <el-table-column prop="updated_at" label="检测时间" />
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
</script>
