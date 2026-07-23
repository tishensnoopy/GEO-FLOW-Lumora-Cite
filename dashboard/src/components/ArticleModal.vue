<template>
  <el-dialog v-model="visible" :title="article.content_title || '文章详情'" width="70%">
    <el-descriptions :column="2" border>
      <el-descriptions-item label="发布时间">{{ article.created_at }}</el-descriptions-item>
      <el-descriptions-item label="URL">{{ article.url }}</el-descriptions-item>
      <el-descriptions-item label="百度收录">{{ article.baidu_status }}</el-descriptions-item>
      <el-descriptions-item label="头条收录">{{ article.toutiao_status }}</el-descriptions-item>
      <el-descriptions-item label="搜狗收录">{{ article.sogou_status }}</el-descriptions-item>
      <el-descriptions-item label="360收录">{{ article.so360_status }}</el-descriptions-item>
      <el-descriptions-item label="必应收录">{{ article.bing_status }}</el-descriptions-item>
      <el-descriptions-item label="AI 采信">{{ article.citation_status || '暂无数据' }}</el-descriptions-item>
    </el-descriptions>
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

const props = defineProps({ modelValue: Boolean, article: Object })
const emit = defineEmits(['update:modelValue'])
const visible = ref(props.modelValue)

watch(() => props.modelValue, (val) => { visible.value = val })
watch(visible, (val) => { emit('update:modelValue', val) })

const viewOriginal = () => {
  if (props.article.url) window.open(props.article.url, '_blank')
}
</script>

<style scoped>
.snapshot { max-height: 300px; overflow-y: auto; padding: 12px; background: #f9f9f9; border-radius: 4px; }
</style>
