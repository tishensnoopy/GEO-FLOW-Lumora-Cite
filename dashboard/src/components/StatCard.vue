<template>
  <div class="stat-card" :class="[`color-${color}`, { featured }]" @mouseenter="hovered = true" @mouseleave="hovered = false">
    <!-- 左侧色条 -->
    <div class="color-bar"></div>
    <div class="card-body">
      <!-- 层 1：序号标签 + 名称 -->
      <div class="card-header">
        <span class="index-label mono">{{ indexLabel }}</span>
        <span class="card-label">{{ label }}</span>
      </div>
      <!-- 层 2：主数字 + 同比 -->
      <div class="card-main">
        <span class="card-value">{{ displayValue }}</span>
        <span v-if="change" class="card-change" :class="changeClass">
          {{ changeArrow }}{{ change }}
        </span>
      </div>
      <!-- 层 3：sparkline -->
      <div class="card-sparkline" v-if="sparkData && sparkData.length >= 2">
        <SparkLine :data="sparkData" :color="sparkColor" :width="sparkWidth" :height="32" />
      </div>
      <!-- 层 4：子指标 -->
      <div class="card-submetrics" v-if="submetrics && submetrics.length">
        <span v-for="(m, i) in submetrics" :key="i" class="submetric">
          {{ m.label }} <strong>{{ m.value }}</strong>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import SparkLine from './SparkLine.vue'

const props = defineProps({
  value: [Number, String],
  label: String,
  color: { type: String, default: 'ink' }, // ink/signal/depth/alert
  featured: Boolean,
  indexLabel: String,
  // 新增：4 层信息 props
  change: String,              // 同比，如 '12%' 或 '5.2pp'
  changeDirection: { type: String, default: 'up' }, // up/down
  sparkData: { type: Array, default: () => [] },
  submetrics: { type: Array, default: () => [] }, // [{label, value}, ...]
})

const hovered = ref(false)

const displayValue = computed(() => {
  if (typeof props.value === 'number') return props.value.toLocaleString()
  return props.value
})

const changeClass = computed(() => ({
  'change-up': props.changeDirection === 'up',
  'change-down': props.changeDirection === 'down',
}))

const changeArrow = computed(() => props.changeDirection === 'up' ? '↑' : '↓')

const sparkColor = computed(() => ({
  ink: '#0F172A',
  signal: '#6366F1',
  depth: '#8B5CF6',
  alert: '#EF4444',
}[props.color] || '#6366F1'))

const sparkWidth = computed(() => props.featured ? 180 : 120)
</script>

<style scoped>
.stat-card {
  position: relative;
  background: var(--grad-surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  display: flex;
  overflow: hidden;
  transition: transform var(--transition-base), box-shadow var(--transition-base), border-color var(--transition-base);
  cursor: default;
}
.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-hover);
  border-color: rgba(99, 102, 241, 0.25);
}
/* 特色卡片：顶部品牌渐变细条 */
.stat-card.featured::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--grad-brand);
  z-index: 1;
}
.color-bar {
  width: 4px;
  flex-shrink: 0;
}
.color-ink .color-bar { background: linear-gradient(180deg, #0F172A, #475569); }
.color-signal .color-bar { background: var(--grad-brand-2); }
.color-depth .color-bar { background: linear-gradient(180deg, #8B5CF6, #EC4899); }
.color-alert .color-bar { background: linear-gradient(180deg, #EF4444, #F59E0B); }

.card-body {
  padding: var(--space-md);
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.index-label {
  font-size: 10px;
  color: var(--mute);
  letter-spacing: 0.12em;
  font-weight: 600;
}
.card-label {
  font-size: var(--fs-small);
  color: var(--mute);
  font-weight: 500;
}
.card-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-xs);
}
.card-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--ink);
  letter-spacing: -0.02em;
  font-variant-numeric: lining-nums;
}
.featured .card-value { font-size: 36px; }
.card-change {
  font-size: var(--fs-small);
  font-weight: 700;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}
.change-up { color: #059669; background: rgba(16, 185, 129, 0.12); }
.change-down { color: #DC2626; background: rgba(239, 68, 68, 0.12); }

.card-sparkline {
  margin: 2px 0;
}
.card-submetrics {
  display: flex;
  justify-content: space-between;
  gap: var(--space-xs);
  font-size: 11px;
  color: var(--mute);
}
.submetric strong {
  color: var(--ink);
  font-weight: 700;
}

/* 移动端：卡片单列时增大内边距 */
@media (max-width: 768px) {
  .card-body { padding: var(--space-md); }
  .card-value { font-size: 28px; }
}
</style>
