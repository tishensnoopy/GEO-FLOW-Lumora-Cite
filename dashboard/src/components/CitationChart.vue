<template>
  <div ref="chartRef" style="height: 300px;"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const chartRef = ref(null)
let chart = null

onMounted(() => {
  const palette = ['#6366F1', '#8B5CF6', '#EC4899', '#06B6D4', '#10B981']
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item' },
    color: palette,
    series: [{
      name: '搜索引擎', type: 'pie', radius: ['40%', '70%'],
      itemStyle: { borderColor: '#FFFFFF', borderWidth: 2, borderRadius: 6 },
      label: { color: '#0F172A' },
      data: [
        { value: 96, name: '百度' }, { value: 88, name: '头条' },
        { value: 85, name: '搜狗' }, { value: 90, name: '360' }, { value: 92, name: '必应' }
      ]
    }]
  })
})

onUnmounted(() => {
  // 释放 echarts 实例，防止内存泄漏
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>
