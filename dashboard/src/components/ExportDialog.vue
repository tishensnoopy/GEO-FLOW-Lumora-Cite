<!-- dashboard/src/components/ExportDialog.vue -->
<template>
  <el-dialog v-model="visible" title="导出报告" width="450px">
    <el-form :model="form" label-width="100px">
      <el-form-item label="导出格式">
        <el-radio-group v-model="form.export_type">
          <el-radio label="pdf">PDF 报告</el-radio>
          <el-radio label="excel">Excel 明细</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="时间范围">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
      </el-form-item>
      <!-- 图表提示信息 -->
      <el-form-item v-if="hasCharts && form.export_type === 'pdf'">
        <el-alert
          title="本次导出将包含当前图表截图（趋势图 + AI 采信分布）"
          type="info"
          :closable="false"
          show-icon
        />
      </el-form-item>
      <el-form-item v-if="!hasCharts && form.export_type === 'pdf'">
        <el-alert
          title="本次导出不含图表截图。如需含图表，请前往「数据总览」页面点击「导出报告（含图表）」按钮。"
          type="info"
          :closable="false"
          show-icon
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="submit" :loading="loading">开始导出</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const props = defineProps({
  modelValue: Boolean,
  // charts：可选，前端 ECharts getDataURL() 生成的 base64 字典。
  // 从 Dashboard 触发时传入，从 Exports 页面触发时不传（undefined 或空对象）。
  charts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'created'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const dateRange = ref([])
const form = reactive({ export_type: 'pdf' })

// 是否携带图表截图（charts 非空对象）
const hasCharts = computed(() => props.charts && Object.keys(props.charts).length > 0)

async function submit() {
  loading.value = true
  try {
    const endpoint = localStorage.getItem('role') === 'admin' ? '/admin/exports' : '/exports'
    const payload = {
      export_type: form.export_type,
      date_from: dateRange.value?.[0] || null,
      date_to: dateRange.value?.[1] || null,
    }
    // 仅 PDF 且有图表时上传 charts（Excel 不需要图表，减小 payload）
    if (form.export_type === 'pdf' && hasCharts.value) {
      payload.charts = props.charts
    }
    const resp = await api.post(endpoint, payload)
    ElMessage.success(`导出任务已创建：${resp.data.task_id}`)
    visible.value = false
    emit('created', resp.data.task_id)
  } catch (err) {
    // 缺口任务 5：详细错误信息（含后端 detail 字段）
    ElMessage.error(err.response?.data?.detail || '导出失败')
  } finally {
    loading.value = false
  }
}
</script>
