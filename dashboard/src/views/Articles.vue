<template>
  <div style="padding: 20px;">
    <h2>文章列表</h2>
    <el-table :data="articles" style="width: 100%">
      <el-table-column prop="title" label="文章标题" />
      <el-table-column prop="baidu_status" label="百度" />
      <el-table-column prop="toutiao_status" label="头条" />
      <el-table-column prop="checked_at" label="检测时间" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const articles = ref([])

onMounted(async () => {
  try {
    const res = await api.get('/articles')
    articles.value = res.data
  } catch (e) {
    console.error('加载文章失败', e)
  }
})
</script>
