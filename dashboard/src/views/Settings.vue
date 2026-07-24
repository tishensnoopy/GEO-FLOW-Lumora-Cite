<template>
  <div style="padding: 20px;">
    <h2>系统设置</h2>

    <!-- 收录检测设置 -->
    <el-card header="收录检测设置" style="margin-bottom: 20px;">
      <el-form :model="config" label-width="220px">
        <el-form-item label="收录检测频率（天/次）">
          <el-input-number v-model="config.index_scan_frequency" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="爬虫并发数">
          <el-input-number v-model="config.spider_concurrent" :min="1" :max="10" />
        </el-form-item>
        <el-form-item label="爬虫最小间隔（秒）">
          <el-input-number v-model="config.spider_interval_min" :min="1" :max="60" />
        </el-form-item>
        <el-form-item label="爬虫最大间隔（秒）">
          <el-input-number v-model="config.spider_interval_max" :min="1" :max="60" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- AI 采信检测设置 -->
    <el-card header="AI 采信检测设置" style="margin-bottom: 20px;">
      <el-form :model="config" label-width="220px">
        <el-form-item label="采信检测频率（天/次）">
          <el-input-number v-model="config.citation_scan_frequency" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="问题生成模型">
          <el-input v-model="config.ai_question_model" placeholder="deepseek-chat" />
          <div class="hint">用于推断文章发布目的和生成检测问题的 LLM 模型（DeepSeek）</div>
        </el-form-item>
        <el-form-item label="引用检测模型">
          <el-checkbox-group v-model="citationModels">
            <el-checkbox label="doubao">豆包</el-checkbox>
            <el-checkbox label="qwen">千问</el-checkbox>
            <el-checkbox label="deepseek">DeepSeek</el-checkbox>
            <el-checkbox label="ernie">文心</el-checkbox>
            <el-checkbox label="openai">ChatGPT</el-checkbox>
            <el-checkbox label="gemini">Gemini</el-checkbox>
            <el-checkbox label="claude">Claude</el-checkbox>
          </el-checkbox-group>
          <div class="hint">不勾选则自动使用所有已配置 API Key 的模型</div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- AI API Key 管理 -->
    <el-card header="AI API Key 管理" style="margin-bottom: 20px;">
      <el-alert type="info" :closable="false" style="margin-bottom: 16px;">
        API Key 仅在服务端存储，前端仅显示脱敏值（如 sk-****81f）。修改后点击"保存配置"生效，留空表示不修改。
      </el-alert>
      <el-form :model="config" label-width="220px">
        <el-form-item label="DeepSeek API Key">
          <el-input v-model="config.ai_deepseek_api_key" show-password placeholder="sk-..." />
          <div class="hint">问题生成+目的推断用（必填），OpenAI 兼容接口</div>
        </el-form-item>
        <el-form-item label="DashScope API Key">
          <el-input v-model="config.ai_dashscope_api_key" show-password placeholder="sk-..." />
          <div class="hint">千问/DeepSeek 引用检测用（阿里云百炼平台）</div>
        </el-form-item>
        <el-form-item label="ARK API Key">
          <el-input v-model="config.ai_ark_api_key" show-password placeholder="" />
          <div class="hint">豆包引用检测用（火山引擎方舟平台）</div>
        </el-form-item>
        <el-form-item label="百度千帆 API Key">
          <el-input v-model="config.ai_baidu_api_key" show-password placeholder="" />
          <div class="hint">文心引用检测用（百度千帆平台）</div>
        </el-form-item>
        <el-form-item label="OpenAI API Key">
          <el-input v-model="config.ai_openai_api_key" show-password placeholder="sk-..." />
          <div class="hint">ChatGPT 引用检测用</div>
        </el-form-item>
        <el-form-item label="Gemini API Key">
          <el-input v-model="config.ai_gemini_api_key" show-password placeholder="" />
          <div class="hint">Gemini 引用检测用（Google AI）</div>
        </el-form-item>
        <el-form-item label="Anthropic API Key">
          <el-input v-model="config.ai_anthropic_api_key" show-password placeholder="sk-ant-..." />
          <div class="hint">Claude 引用检测用</div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 操作按钮 -->
    <div style="text-align: center;">
      <el-button type="primary" @click="saveConfig">保存配置</el-button>
      <el-button type="warning" @click="triggerScan('index')">立即收录扫描</el-button>
      <el-button type="warning" @click="triggerScan('citation')">立即 AI 采信扫描</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const config = ref({})

// 引用检测模型复选框：与 config.ai_citation_models（逗号分隔字符串）双向同步
const citationModels = computed({
  get() {
    const val = config.value.ai_citation_models || ''
    return val ? val.split(',').map(s => s.trim()).filter(Boolean) : []
  },
  set(val) {
    config.value.ai_citation_models = val.join(',')
  }
})

onMounted(async () => {
  try {
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    console.error('加载配置失败', e)
    ElMessage.error('加载配置失败')
  }
})

const saveConfig = async () => {
  try {
    await api.put('/config', config.value)
    ElMessage.success('配置保存成功')
    // 重新加载以获取脱敏后的 API Key 显示
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const triggerScan = async (type) => {
  try {
    const res = await api.post(`/scan/trigger/${type}`)
    ElMessage.success(res.data.message || '扫描任务已触发')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发失败')
  }
}
</script>

<style scoped>
.hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
