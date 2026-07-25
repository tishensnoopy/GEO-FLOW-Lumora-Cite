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
  // charts: 由 Dashboard.vue 通过 getChartsDataURL() 生成的 base64 数据 URL 字典，
  // 格式 {"trend": "data:image/png;base64,...", "pie": "..."}。
  // 仅在 PDF 导出且非空时随请求一并提交（后端 ExportRequest.charts: Optional[dict]）。
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

async function submit() {
  loading.value = true
  try {
    const endpoint = localStorage.getItem('role') === 'admin' ? '/admin/exports' : '/exports'
    const payload = {
      export_type: form.export_type,
      date_from: dateRange.value?.[0] || null,
      date_to: dateRange.value?.[1] || null,
    }
    // 仅 PDF 报告携带图表截图（Excel 明细无需图表）。
    // 后端 ExportRequest.charts: Optional[dict] = None，None/缺省均向后兼容。
    if (form.export_type === 'pdf' && props.charts && Object.keys(props.charts).length > 0) {
      payload.charts = props.charts
    }
    const resp = await api.post(endpoint, payload)
    ElMessage.success(`导出任务已创建：${resp.data.task_id}`)
    visible.value = false
    emit('created', resp.data.task_id)
  } catch (err) {
    ElMessage.error('导出失败')
  } finally {
    loading.value = false
  }
}
</script>
