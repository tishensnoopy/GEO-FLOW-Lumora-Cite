<!-- dashboard/src/components/StatCard.vue -->
<template>
  <div class="stat-card" :class="[color, { featured }]">
    <div class="stat-meta">
      <div class="stat-label">{{ label }}</div>
      <div class="stat-index mono" v-if="indexLabel">{{ indexLabel }}</div>
    </div>
    <div class="stat-value num-serif">{{ value }}</div>
    <div v-if="icon" class="stat-icon">
      <el-icon :size="20"><component :is="icon" /></el-icon>
    </div>
  </div>
</template>

<script setup>
defineProps({
  value: [Number, String],
  label: String,
  icon: String,
  // 语义色：ink（中性主指标）/ signal（已收录/采信）/ alert（警示率）/ depth（AI 相关）
  color: { type: String, default: 'ink' },
  // 是否为特色卡片（更大数字 + 衬线 900）
  featured: { type: Boolean, default: false },
  // 可选序号标签（如 "01 / 04"），呼应"报告"感
  indexLabel: { type: String, default: '' },
})
</script>

<style scoped>
.stat-card {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 120px;
  padding: var(--space-md);
  background: var(--surface);
  border: 1px solid var(--ink-line);
  border-radius: var(--radius-md);
  box-shadow: var(--paper-shadow);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  overflow: hidden;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(26, 26, 26, 0.08);
}
/* 特色卡片：数字放大 + 衬线 900，用于第一个"分发总数"卡片 */
.stat-card.featured {
  min-height: 160px;
}
.stat-card.featured .stat-value {
  font-size: 64px;
  font-weight: 900;
}

.stat-meta {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--space-sm);
}
.stat-label {
  font-size: var(--fs-body);
  color: var(--mute);
  font-weight: 500;
  letter-spacing: 0.02em;
}
.stat-index {
  font-size: var(--fs-mono);
  color: var(--mute);
  opacity: 0.7;
}

.stat-value {
  font-size: var(--fs-stat);
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);  /* 默认中性 */
  font-variant-numeric: lining-nums;
}

.stat-icon {
  position: absolute;
  bottom: var(--space-sm);
  right: var(--space-sm);
  opacity: 0.3;
}

/* === 语义色映射：仅染色数字与图标，不染卡片背景（克制） === */
.ink .stat-value { color: var(--ink); }
.ink .stat-icon { color: var(--ink); }

.signal .stat-value { color: var(--signal); }
.signal .stat-icon { color: var(--signal); }
.signal.stat-card { border-left: 3px solid var(--signal); }

.alert .stat-value { color: var(--alert); }
.alert .stat-icon { color: var(--alert); }
.alert.stat-card { border-left: 3px solid var(--alert); }

.depth .stat-value { color: var(--depth); }
.depth .stat-icon { color: var(--depth); }
.depth.stat-card { border-left: 3px solid var(--depth); }

/* === 向后兼容旧 color 值（避免遗漏调用点报错） === */
.blue .stat-value { color: var(--signal); }
.green .stat-value { color: var(--signal); }
.orange .stat-value { color: var(--alert); }
.purple .stat-value { color: var(--depth); }
</style>
