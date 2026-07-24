<template>
  <div class="dashboard-container">
    <el-container>
      <el-header>
        <div class="header-content">
          <h1>知氪AI全链路监测仪表盘</h1>
        </div>
      </el-header>
      <el-main>
        <el-row :gutter="20" class="stats-row">
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ indexStats.total }}</div><div class="stat-label">总文章数</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ indexStats.indexed }}</div><div class="stat-label">已收录数</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ (indexStats.rate * 100).toFixed(1) }}%</div><div class="stat-label">收录率</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ citationStats.cited }}</div><div class="stat-label">AI 采信数</div></el-card></el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12"><el-card><template #header><span>收录趋势</span></template><IndexChart /></el-card></el-col>
          <el-col :span="12"><el-card><template #header><span>搜索引擎分布</span></template><CitationChart /></el-card></el-col>
        </el-row>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { onMounted, computed } from 'vue'
import { useStore } from 'vuex'
import IndexChart from '../components/IndexChart.vue'
import CitationChart from '../components/CitationChart.vue'

const store = useStore()
const indexStats = computed(() => store.state.indexStats)
const citationStats = computed(() => store.state.citationStats)

onMounted(async () => {
  await store.dispatch('fetchIndexStats')
  await store.dispatch('fetchCitationStats')
})
</script>

<style scoped>
.dashboard-container { min-height: 100vh; background: #f5f7fa; }
.el-header { background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.header-content { display: flex; justify-content: space-between; align-items: center; height: 100%; }
h1 { font-size: 24px; color: #333; }
.stats-row { margin-bottom: 20px; }
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: bold; color: #409eff; margin-bottom: 8px; }
.stat-label { font-size: 14px; color: #999; }
</style>
