<template>
  <svg :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" class="sparkline">
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.2" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <!-- 填充区域 -->
    <path v-if="areaPath" :d="areaPath" :fill="`url(#${gradientId})`" />
    <!-- 折线 -->
    <path :d="linePath" fill="none" :stroke="color" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }, // 数值数组，如 [5, 8, 12, 15, 18]
  width: { type: Number, default: 120 },
  height: { type: Number, default: 32 },
  color: { type: String, default: '#0D9488' },
})

// 唯一 ID 避免多个 sparkline 渐变冲突
const gradientId = `spark-grad-${Math.random().toString(36).slice(2, 9)}`

const linePath = computed(() => {
  if (!props.data || props.data.length < 2) return ''
  const max = Math.max(...props.data)
  const min = Math.min(...props.data)
  const range = max - min || 1
  const stepX = props.width / (props.data.length - 1)
  return props.data
    .map((v, i) => {
      const x = i * stepX
      const y = props.height - ((v - min) / range) * (props.height - 4) - 2
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
})

const areaPath = computed(() => {
  if (!linePath.value) return ''
  return `${linePath.value} L ${props.width} ${props.height} L 0 ${props.height} Z`
})
</script>

<style scoped>
.sparkline { display: block; }
</style>
