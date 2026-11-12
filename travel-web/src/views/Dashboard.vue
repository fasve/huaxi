<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type Stats } from '../api'

const stats = ref<Stats | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    stats.value = (await api.getStats()).data
  } finally {
    loading.value = false
  }
}
onMounted(load)

const maxTrend = computed(() =>
  Math.max(1, ...(stats.value?.trend.map((t) => t.count) || [1])))
const maxBudget = computed(() =>
  Math.max(1, ...(stats.value?.budget_distribution.map((b) => b.count) || [1])))
const maxCat = computed(() =>
  Math.max(1, ...(stats.value?.poi.by_category.map((c) => c.count) || [1])))
const maxMode = computed(() =>
  Math.max(1, ...(stats.value?.trip.by_mode.map((m) => m.count) || [1])))

const COLORS = ['#2f7d5c', '#4a9b78', '#74b894', '#e6803a', '#d4a24c']

function barWidth(n: number, max: number) {
  return Math.max(2, Math.round((n / max) * 100)) + '%'
}

async function refreshCache() {
  await api.clearCache()
  ElMessage.success('缓存已清空')
  load()
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>数据概览</h2>
        <span class="hint">系统运营状态一览 · {{ stats?.generated_at || '加载中' }}</span>
      </div>
      <div style="display: flex; gap: 8px">
        <el-button :icon="'Refresh'" @click="load">刷新数据</el-button>
        <el-button @click="refreshCache">清缓存</el-button>
      </div>
    </div>

    <template v-if="stats">
      <!-- KPI -->
      <div class="kpi-grid">
        <div class="page-card kpi">
          <span class="kpi-label">资源总数</span>
          <b class="kpi-value">{{ stats.poi.total }}</b>
          <span class="hint">平均评分 {{ stats.poi.avg_rating }}</span>
        </div>
        <div class="page-card kpi">
          <span class="kpi-label">已上架</span>
          <b class="kpi-value">{{ stats.poi.visitable }}</b>
          <span class="hint">上架率 {{ Math.round(stats.poi.online_rate * 100) }}% · 下架 {{ stats.poi.offline }}</span>
        </div>
        <div class="page-card kpi">
          <span class="kpi-label">生成行程</span>
          <b class="kpi-value">{{ stats.trip.total }}</b>
          <span class="hint">已保存 {{ stats.trip.saved }} · 草稿 {{ stats.trip.draft }}</span>
        </div>
        <div class="page-card kpi">
          <span class="kpi-label">注册用户 / 标签</span>
          <b class="kpi-value">{{ stats.users.total }} <small>/ {{ stats.tags.total }}</small></b>
          <span class="hint">平均花费 ¥{{ stats.trip.avg_cost }}</span>
        </div>
      </div>

      <div class="two-col">
        <!-- 资源分布 -->
        <div class="page-card">
          <h3>资源分类分布</h3>
          <div v-for="(c, i) in stats.poi.by_category" :key="c.code" class="bar-row">
            <span class="bar-label">{{ c.name }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: barWidth(c.count, maxCat), background: COLORS[i % COLORS.length] }"></div>
            </div>
            <b class="bar-num">{{ c.count }}</b>
          </div>
        </div>

        <!-- 模式分布 -->
        <div class="page-card">
          <h3>行程模式分布</h3>
          <div v-for="(m, i) in stats.trip.by_mode" :key="m.mode" class="bar-row">
            <span class="bar-label">{{ m.name }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: barWidth(m.count, maxMode), background: COLORS[i % COLORS.length] }"></div>
            </div>
            <b class="bar-num">{{ m.count }}</b>
          </div>
          <div v-if="!stats.trip.by_mode.length" class="hint">暂无行程数据</div>
        </div>
      </div>

      <div class="two-col">
        <!-- 趋势 SVG -->
        <div class="page-card">
          <h3>近 7 日行程生成趋势</h3>
          <svg viewBox="0 0 520 170" class="chart">
            <line x1="30" y1="140" x2="510" y2="140" stroke="#e6ebe8" stroke-width="1" />
            <g v-for="(t, i) in stats.trend" :key="t.date">
              <rect
                :x="40 + i * 68" :y="140 - (t.count / maxTrend) * 110"
                width="34" :height="Math.max(2, (t.count / maxTrend) * 110)"
                rx="4" fill="#2f7d5c" :opacity="0.45 + (i / 7) * 0.55"
              />
              <text :x="57 + i * 68" y="158" text-anchor="middle" font-size="11" fill="#909399">
                {{ t.date.slice(5) }}
              </text>
              <text v-if="t.count" :x="57 + i * 68" :y="134 - (t.count / maxTrend) * 110"
                    text-anchor="middle" font-size="11" fill="#303133">{{ t.count }}</text>
            </g>
          </svg>
        </div>

        <!-- 预算分布 -->
        <div class="page-card">
          <h3>预算区间分布</h3>
          <div v-for="b in stats.budget_distribution" :key="b.label" class="bar-row">
            <span class="bar-label" style="width: 100px">¥{{ b.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: barWidth(b.count, maxBudget), background: '#e6803a' }"></div>
            </div>
            <b class="bar-num">{{ b.count }}</b>
          </div>
        </div>
      </div>

      <!-- 热门 POI -->
      <div class="page-card">
        <h3>最常被排进行程的资源点 <span class="hint">（反映算法偏好）</span></h3>
        <div class="top-grid">
          <div v-for="(p, i) in stats.top_pois" :key="p.poi_id" class="top-item">
            <span class="rank" :class="{ top3: i < 3 }">{{ i + 1 }}</span>
            <span class="top-name">{{ p.name }}</span>
            <el-tag size="small" type="success">{{ p.count }} 次</el-tag>
          </div>
          <div v-if="!stats.top_pois.length" class="hint">暂无行程数据</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; flex-wrap: wrap; gap: 10px;
}
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; font-weight: 400; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.kpi { display: flex; flex-direction: column; gap: 4px; }
.kpi-label { font-size: 13px; color: #909399; }
.kpi-value { font-size: 30px; color: #2f7d5c; line-height: 1.2; }
.kpi-value small { font-size: 18px; color: #909399; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.page-card h3 { margin: 0 0 16px; font-size: 15px; }
.bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.bar-label { width: 64px; font-size: 13px; color: #606266; flex: none; }
.bar-track { flex: 1; height: 12px; background: #f1f4f2; border-radius: 999px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; transition: width .4s ease; }
.bar-num { width: 34px; text-align: right; font-size: 13px; }
.chart { width: 100%; height: 170px; }
.top-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 24px; }
.top-item { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px dashed #f0f2f1; }
.rank {
  width: 22px; height: 22px; border-radius: 6px; background: #f1f4f2;
  display: grid; place-items: center; font-size: 12px; color: #909399;
}
.rank.top3 { background: #2f7d5c; color: #fff; }
.top-name { flex: 1; font-size: 13px; }
@media (max-width: 1100px) {
  .kpi-grid, .two-col, .top-grid { grid-template-columns: 1fr 1fr; }
}
</style>
