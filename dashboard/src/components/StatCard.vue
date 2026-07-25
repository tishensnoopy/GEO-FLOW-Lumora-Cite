<!-- dashboard/src/components/StatCard.vue -->
<template>
  <div class="stat-card" :class="color">
    <div class="stat-icon">
      <el-icon :size="32"><component :is="icon" /></el-icon>
    </div>
    <div class="stat-content">
      <div class="stat-value">{{ value }}</div>
      <div class="stat-label">{{ label }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  value: [Number, String],
  label: String,
  icon: String,
  color: { type: String, default: 'blue' },
})
</script>

<style scoped>
.stat-card {
  display: flex;
  align-items: center;
  padding: 20px;
  border-radius: 8px;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transition: transform 0.2s;
}
.stat-card:hover {
  transform: translateY(-2px);
}
.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 15px;
}
.stat-value {
  font-size: 28px;
  font-weight: bold;
}
.stat-label {
  font-size: 14px;
  color: #666;
  margin-top: 4px;
}
.blue .stat-icon { background: #e3f2fd; color: #2196f3; }
.blue .stat-value { color: #2196f3; }
.green .stat-icon { background: #e8f5e9; color: #4caf50; }
.green .stat-value { color: #4caf50; }
.orange .stat-icon { background: #fff3e0; color: #ff9800; }
.orange .stat-value { color: #ff9800; }
.purple .stat-icon { background: #f3e5f5; color: #9c27b0; }
.purple .stat-value { color: #9c27b0; }
</style>
