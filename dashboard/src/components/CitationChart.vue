<template>
  <div ref="chartRef" style="height: 300px;"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const chartRef = ref(null)
let chart = null

onMounted(() => {
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item' },
    series: [{
      name: '搜索引擎', type: 'pie', radius: ['40%', '70%'],
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
