<template>
  <span class="status-dot" :class="`status-${status}`">
    <span class="dot"></span>
    <span class="label">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // indexed（收录）/ partial（部分）/ pending（未检）
  status: { type: String, default: 'pending' },
})

const label = computed(() => ({
  indexed: '收录',
  partial: '部分',
  pending: '未检',
}[props.status] || props.status))
</script>

<style scoped>
.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-small);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
/* 实心圆：收录 */
.status-indexed .dot {
  background: var(--status-indexed);
}
/* 半圆：部分（用渐变模拟左半实心） */
.status-partial .dot {
  background: linear-gradient(to right, var(--status-partial) 50%, transparent 50%);
  border: 1px solid var(--status-partial);
}
/* 空心圆：未检 */
.status-pending .dot {
  background: transparent;
  border: 1px solid var(--status-pending);
}
.status-indexed .label { color: var(--status-indexed); }
.status-partial .label { color: var(--status-partial); }
.status-pending .label { color: var(--status-pending); }
</style>
