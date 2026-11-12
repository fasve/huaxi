<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api, MODE_EMOJI, MODE_ORDER, PREFERENCES, PARTY_TYPES,
  type CompareResult, toast,
} from '../api'

const route = useRoute()
const router = useRouter()
const form = reactive({
  days: 2,
  budget: 1200,
  preferences: [] as string[],
  party_type: 'couple',
})
const results = ref<CompareResult[]>([])
const note = ref('')
const loading = ref(false)
const compared = ref(false)

onMounted(() => {
  const q = route.query
  if (q.days) form.days = Number(q.days) || 2
  if (q.budget) form.budget = Number(q.budget) || 1200
  if (q.party) form.party_type = String(q.party)
  if (typeof q.prefs === 'string' && q.prefs) form.preferences = q.prefs.split(',')
  // 从定制页跳转过来时自动出结果
  if (q.days || q.budget) run()
})

function togglePref(code: string) {
  const i = form.preferences.indexOf(code)
  if (i >= 0) form.preferences.splice(i, 1)
  else form.preferences.push(code)
}

async function run() {
  if (form.budget <= 0) {
    toast('请输入有效预算', true)
    return
  }
  loading.value = true
  try {
    const res = await api.compare({
      days: form.days, budget: form.budget,
      preferences: [...form.preferences], party_type: form.party_type,
      seed: 42,
    })
    results.value = res.results
    note.value = res.note
    compared.value = true
  } finally {
    loading.value = false
  }
}

const insights = computed(() => {
  if (results.value.length < 2) return []
  const rs = results.value
  const minCost = rs.reduce((a, b) => (a.total_cost <= b.total_cost ? a : b))
  const maxPoi = rs.reduce((a, b) => (a.poi_per_day >= b.poi_per_day ? a : b))
  const mostFree = rs.reduce((a, b) => (a.free_poi_ratio >= b.free_poi_ratio ? a : b))
  const maxUsage = rs.reduce((a, b) => (a.budget_usage >= b.budget_usage ? a : b))
  return [
    `最省钱：${minCost.mode_name}（¥${minCost.total_cost}）`,
    `节奏最满：${maxPoi.mode_name}（日均 ${maxPoi.poi_per_day} 个点）`,
    `免费点最多：${mostFree.mode_name}（占比 ${Math.round(mostFree.free_poi_ratio * 100)}%）`,
    `预算用得最足：${maxUsage.mode_name}（${Math.round(maxUsage.budget_usage * 100)}%）`,
  ]
})

function useMode(mode: string) {
  router.push({ path: '/plan', query: { mode } })
}
</script>

<template>
  <div class="container">
    <section class="section">
      <div class="section-head">
        <div>
          <h1 class="section-title">四种模式，同一组需求</h1>
          <div class="section-sub">并排对比算法输出，直观看到权重差异如何改变路线节奏与花费</div>
        </div>
      </div>

      <div class="card no-print">
        <div class="filter-row">
          <div class="field"><label>天数</label>
            <select v-model.number="form.days" class="select">
              <option v-for="d in 7" :key="d" :value="d">{{ d }} 天</option>
            </select>
          </div>
          <div class="field"><label>人均预算（元）</label>
            <input v-model.number="form.budget" type="number" min="1" class="input" />
          </div>
          <div class="field"><label>出行人群</label>
            <select v-model="form.party_type" class="select">
              <option v-for="p in PARTY_TYPES" :key="p.code" :value="p.code">{{ p.label }}</option>
            </select>
          </div>
          <button class="btn btn-primary" :disabled="loading" @click="run">
            {{ loading ? '计算中…' : '开始对比' }}
          </button>
        </div>
        <div class="chips" style="margin-top: 14px">
          <button v-for="p in PREFERENCES" :key="p.code" class="chip"
                  :class="{ on: form.preferences.includes(p.code) }"
                  @click="togglePref(p.code)">{{ p.label }}</button>
        </div>
      </div>

      <div v-if="loading" class="empty">四种模式正在并行计算…</div>
      <div v-else-if="!compared" class="empty">填好条件，点「开始对比」查看四种模式的差异</div>

      <template v-else>
        <!-- 差异总结 -->
        <div class="card insight-card">
          <b>一眼看懂差异</b>
          <div class="insight-row">
            <span v-for="s in insights" :key="s" class="tag">{{ s }}</span>
          </div>
          <div class="small muted" style="margin-top: 10px">{{ note }}</div>
        </div>

        <!-- 四列对比 -->
        <div class="grid grid-4 compare-grid">
          <div v-for="r in results" :key="r.mode" class="card compare-col">
            <div class="col-head">
              <span class="col-emoji">{{ MODE_EMOJI[r.mode] || '🧭' }}</span>
              <div>
                <div class="col-name">{{ r.mode_name }}</div>
                <div class="small muted">¥{{ r.total_cost }} · 使用率 {{ Math.round(r.budget_usage * 100) }}%</div>
              </div>
            </div>
            <div class="divider"></div>
            <div class="metric"><span>总花费</span><b>¥{{ r.total_cost }}</b></div>
            <div class="metric"><span>行程点数</span><b>{{ r.poi_count }} 个</b></div>
            <div class="metric"><span>日均节奏</span><b>{{ r.poi_per_day }} 个/天</b></div>
            <div class="metric"><span>免费点占比</span><b>{{ Math.round(r.free_poi_ratio * 100) }}%</b></div>
            <div class="metric"><span>住宿</span><b class="small">{{ r.hotel || '不安排' }}</b></div>
            <div class="metric"><span>松弛提示</span><b>{{ r.relax_count }} 条</b></div>
            <div class="divider"></div>
            <div v-for="d in r.days_plan" :key="d.day_index" class="col-day">
              <div class="small"><b>Day {{ d.day_index }}</b> {{ d.theme }}</div>
              <div class="small muted col-pois">{{ d.poi_names.join(' → ') }}</div>
            </div>
            <button class="btn btn-primary btn-sm col-btn no-print" @click="useMode(r.mode)">
              用这个模式生成 →
            </button>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.filter-row { display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap; }
.filter-row .field { min-width: 150px; }
.insight-card { margin-top: 20px; }
.insight-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.insight-row .tag { padding: 5px 12px; font-size: 13px; }
.compare-grid { margin-top: 20px; }
.compare-col { display: flex; flex-direction: column; padding: 18px; }
.col-head { display: flex; align-items: center; gap: 10px; }
.col-emoji { font-size: 28px; }
.col-name { font-size: 17px; font-weight: 700; }
.metric { display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; font-size: 13px; }
.metric span { color: var(--muted); }
.metric b { text-align: right; }
.col-day { margin-bottom: 10px; }
.col-pois { line-height: 1.6; margin-top: 2px; }
.col-btn { margin-top: auto; width: 100%; }
@media (max-width: 1100px) { .compare-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
