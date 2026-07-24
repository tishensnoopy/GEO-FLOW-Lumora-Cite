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
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['7天前', '6天前', '5天前', '4天前', '3天前', '2天前', '昨天'] },
    yAxis: { type: 'value' },
    series: [{ name: '收录数', type: 'line', data: [85, 88, 90, 92, 94, 95, 96], smooth: true, itemStyle: { color: '#409eff' } }]
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
