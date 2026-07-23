<template>
  <div style="padding: 20px;">
    <h2>系统设置</h2>
    <el-form :model="config" label-width="200px">
      <el-form-item label="收录检测频率（天/次）">
        <el-input-number v-model="config.index_scan_frequency" :min="1" :max="30" />
      </el-form-item>
      <el-form-item label="AI 采信检测频率（天/次）">
        <el-input-number v-model="config.citation_scan_frequency" :min="1" :max="30" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveConfig">保存配置</el-button>
        <el-button type="warning" @click="triggerScan('index')">立即收录扫描</el-button>
        <el-button type="warning" @click="triggerScan('citation')">立即 AI 采信扫描</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const config = ref({})

onMounted(async () => {
  try {
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    console.error('加载配置失败', e)
  }
})

const saveConfig = async () => {
  try {
    await api.put('/config', config.value)
    ElMessage.success('配置保存成功')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const triggerScan = async (type) => {
  try {
    await api.post(`/scan/trigger/${type}`)
    ElMessage.success('扫描任务已触发')
  } catch (e) {
    ElMessage.error('触发失败')
  }
}
</script>
