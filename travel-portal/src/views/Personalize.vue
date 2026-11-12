<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api, MODE_EMOJI, MODE_ORDER, PREFERENCES, PARTY_TYPES,
  type ChangedItem, type PaceConfig, type PreviewItem, type Trip,
  type WeightMetadata, type WeightPreset, toast,
} from '../api'

const route = useRoute()
const router = useRouter()

const meta = ref<WeightMetadata | null>(null)
const loading = ref(true)
const submitting = ref(false)
const previewLoading = ref(false)

/** 目标行程（从行程详情页"按权重调整路线"进入时带上） */
const targetTripId = computed(() => String(route.query.trip || ''))

const form = reactive({
  mode: 'checkin',
  days: 2,
  budget: 1200,
  party_type: 'couple',
  preferences: [] as string[],
  /** 滑块原值 0~100 */
  sliders: {} as Record<string, number>,
  pace: {} as PaceConfig,
})

const preview = ref<PreviewItem[]>([])
const changed = ref<ChangedItem[]>([])
const previewWeights = ref<Record<string, number>>({})
const previewPersonalized = ref(false)
const previewTimer = ref<number | null>(null)

const CATEGORY_LABEL: Record<string, string> = {
  scenic: '景点', food: '美食', hotel: '住宿', leisure: '休闲', study: '游学',
}

const dimensions = computed(() => meta.value?.dimensions ?? [])
const presets = computed(() => meta.value?.presets ?? [])
const eveningPrefs = computed(() => meta.value?.evening_preferences ?? [])

const sliderTotal = computed(() =>
  Object.values(form.sliders).reduce((a, b) => a + (b || 0), 0),
)

/** 每个维度的归一化占比（前端实时计算，后端归一化口径一致） */
const percentMap = computed<Record<string, number>>(() => {
  const total = sliderTotal.value
  const out: Record<string, number> = {}
  for (const d of dimensions.value) {
    const v = form.sliders[d.key] || 0
    out[d.key] = total > 0 ? Math.round((v / total) * 100) : 0
  }
  return out
})

const activePreset = computed(() => {
  const cur = { ...form.sliders }
  for (const p of presets.value) {
    const target = p.key === 'balanced' ? modeDefaults.value : p.weights
    const keys = Object.keys(cur)
    const same = keys.every((k) => (cur[k] || 0) === (target[k] ?? (cur[k] || 0)))
    if (same) return p.key
  }
  return ''
})

const modeDefaults = computed<Record<string, number>>(
  () => meta.value?.modes[form.mode]?.slider_defaults ?? {},
)

const paceInfo = computed(() => {
  const m = meta.value?.modes[form.mode]
  return {
    poiMax: m?.daily_poi_max ?? 3,
    hoursMax: m?.play_hours_max ?? 6,
  }
})

onMounted(async () => {
  try {
    meta.value = await api.getWeightMetadata()
    const m = String(route.query.mode || '')
    if (MODE_ORDER.includes(m)) form.mode = m
    const d = Number(route.query.days)
    if (d >= 1 && d <= 7) form.days = d
    const b = Number(route.query.budget)
    if (b > 0) form.budget = b
    applyModeDefaults(form.mode)
    await runPreview()
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
})

/** 切换模式：滑块重置为该模式的默认权重 */
function applyModeDefaults(mode: string) {
  const d = meta.value?.modes[mode]?.slider_defaults
  if (!d) return
  const next: Record<string, number> = {}
  for (const dim of dimensions.value) next[dim.key] = d[dim.key] ?? 0
  form.sliders = next
  const m = meta.value?.modes[mode]
  form.pace = {
    daily_poi_max: m?.daily_poi_max ?? 3,
    play_hours_max: m?.play_hours_max ?? 6,
  }
}

/** 套用预设：把预设的关注度写入滑块 */
function applyPreset(p: WeightPreset) {
  if (p.key === 'balanced') {
    applyModeDefaults(form.mode)
    return
  }
  const next: Record<string, number> = {}
  for (const dim of dimensions.value) next[dim.key] = p.weights[dim.key] ?? 0
  form.sliders = next
}

function togglePref(code: string) {
  const i = form.preferences.indexOf(code)
  if (i >= 0) form.preferences.splice(i, 1)
  else form.preferences.push(code)
}

/** 滑块变化 → 防抖刷新预览 */
watch(
  () => [form.mode, form.sliders, form.pace, form.preferences],
  () => {
    if (loading.value) return
    if (previewTimer.value) window.clearTimeout(previewTimer.value)
    previewTimer.value = window.setTimeout(runPreview, 320)
  },
  { deep: true },
)

async function runPreview() {
  previewLoading.value = true
  try {
    const res = await api.previewWeights({
      mode: form.mode,
      weights: { ...form.sliders },
      preferences: [...form.preferences],
      pace: { ...form.pace },
      top_k: 12,
    })
    preview.value = res.items || []
    changed.value = res.changed || []
    previewWeights.value = res.weights || {}
    previewPersonalized.value = res.is_personalized
  } catch { /* 拦截器已提示 */ } finally {
    previewLoading.value = false
  }
}

/** 生成个性化行程（无目标行程时新建） */
async function generate() {
  submitting.value = true
  try {
    const trip: Trip = await api.generateTrip({
      days: form.days,
      budget: form.budget,
      mode: form.mode,
      preferences: [...form.preferences],
      party_type: form.party_type,
      seed: Math.floor(Math.random() * 9999),
      weights: { ...form.sliders },
      pace: { ...form.pace },
    })
    toast('个性化行程已生成')
    router.push({ path: `/trip/${trip.trip_id}` })
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}

/** 按新权重重排既有行程 */
async function reweight() {
  if (!targetTripId.value) return
  submitting.value = true
  try {
    await api.reweightTrip(targetTripId.value, {
      weights: { ...form.sliders },
      pace: { ...form.pace },
    })
    toast('已按新权重重排路线')
    router.push({ path: `/trip/${targetTripId.value}` })
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}

function scoreText(it: PreviewItem) {
  const delta = it.score - it.base_score
  if (Math.abs(delta) < 0.001) return '与默认持平'
  return `较默认 ${delta > 0 ? '+' : ''}${delta.toFixed(3)}`
}
</script>

<template>
  <div class="container">
    <div v-if="loading" class="empty">个性化配置加载中…</div>

    <template v-else>
      <section class="section">
        <div class="section-head">
          <div>
            <h1 class="section-title">个性化 · 按权重调整路线</h1>
            <div class="section-sub">
              拖动滑块定义"你更在乎什么"，系统实时换算选点顺序；节奏微调控制每天排几个点、几点收工
            </div>
          </div>
          <router-link to="/plan" class="small brand-text">← 基础定制</router-link>
        </div>

        <div class="pz-layout">
          <!-- 左：配置面板 -->
          <div class="pz-left">
            <!-- 模式 -->
            <div class="card block">
              <div class="block-title"><i>1</i> 基准模式</div>
              <div class="mode-grid">
                <div
                  v-for="m in MODE_ORDER" :key="m"
                  class="mode-opt" :class="{ on: form.mode === m }"
                  @click="form.mode = m; applyModeDefaults(m)"
                >
                  <span class="mode-e">{{ MODE_EMOJI[m] }}</span>
                  <span class="mode-n">{{ meta?.modes[m]?.mode_name || m }}</span>
                </div>
              </div>
              <div class="small muted" style="margin-top: 10px">
                滑块初值取自该模式默认权重，微调后仅改变关注度分配
              </div>
            </div>

            <!-- 预设 -->
            <div class="card block">
              <div class="block-title"><i>2</i> 偏好模板</div>
              <div class="preset-grid">
                <button
                  v-for="p in presets" :key="p.key"
                  class="preset" :class="{ on: activePreset === p.key }"
                  :title="p.desc" @click="applyPreset(p)"
                >
                  <span class="p-icon">{{ p.icon }}</span>
                  <span class="p-label">{{ p.label }}</span>
                  <span class="p-desc">{{ p.desc }}</span>
                </button>
              </div>
            </div>

            <!-- 权重滑块 -->
            <div class="card block">
              <div class="block-title">
                <i>3</i> 关注度分配
                <span class="small muted">（拖动即生效，右侧实时预览）</span>
              </div>

              <div class="slider-row" v-for="d in dimensions" :key="d.key">
                <div class="slider-head">
                  <span class="s-icon">{{ d.icon }}</span>
                  <span class="s-label">{{ d.label }}</span>
                  <span class="s-pct">{{ percentMap[d.key] }}%</span>
                </div>
                <input
                  v-model.number="form.sliders[d.key]"
                  type="range" min="0" max="100" step="1" class="slider"
                  :style="{ accentColor: 'var(--brand)' }"
                />
                <div class="s-hint">{{ d.desc }} · {{ d.hint }}</div>
              </div>

              <div class="slider-total">
                <span class="small muted">
                  关注度合计 {{ sliderTotal }}，归一化后按占比参与打分
                </span>
                <button class="btn btn-sm btn-soft" @click="applyModeDefaults(form.mode)">
                  恢复模式默认
                </button>
              </div>
            </div>

            <!-- 节奏微调 -->
            <div class="card block">
              <div class="block-title"><i>4</i> 节奏微调</div>

              <div class="pace-row">
                <div class="field">
                  <label>每日游玩点上限：{{ form.pace.daily_poi_max }} 个</label>
                  <input v-model.number="form.pace.daily_poi_max" type="range"
                         min="2" max="6" step="1" class="range" />
                </div>
                <div class="field">
                  <label>每日游玩时长上限：{{ form.pace.play_hours_max }} 小时</label>
                  <input v-model.number="form.pace.play_hours_max" type="range"
                         min="3" max="12" step="1" class="range" />
                </div>
              </div>

              <div class="small muted" style="margin: 12px 0 8px">晚间偏好</div>
              <div class="chips">
                <button
                  v-for="e in eveningPrefs" :key="e.key"
                  class="chip" :class="{ on: form.pace.evening === e.key }"
                  :title="e.desc" @click="form.pace.evening = e.key"
                >{{ e.icon }} {{ e.label }}</button>
              </div>
              <div class="small muted" style="margin-top: 8px">
                {{ eveningPrefs.find((e) => e.key === form.pace.evening)?.desc || '不指定则沿用模式默认的晚间安排' }}
              </div>
            </div>

            <!-- 行程要素 -->
            <div class="card block">
              <div class="block-title"><i>5</i> 行程要素</div>
              <div class="form-row">
                <div class="field">
                  <label>行程天数：{{ form.days }} 天</label>
                  <input v-model.number="form.days" type="range" min="1" max="7" step="1" class="range" />
                </div>
                <div class="field">
                  <label>全程人均预算（元）</label>
                  <input v-model.number="form.budget" type="number" min="1" class="input" />
                </div>
              </div>
              <div class="divider"></div>
              <div class="small muted" style="margin-bottom: 8px">出行人群</div>
              <div class="chips">
                <button v-for="p in PARTY_TYPES" :key="p.code" class="chip"
                        :class="{ on: form.party_type === p.code }"
                        @click="form.party_type = p.code">{{ p.label }}</button>
              </div>
              <div class="small muted" style="margin: 14px 0 8px">旅行偏好</div>
              <div class="chips">
                <button v-for="p in PREFERENCES" :key="p.code" class="chip"
                        :class="{ on: form.preferences.includes(p.code) }"
                        @click="togglePref(p.code)">{{ p.label }}</button>
              </div>
            </div>
          </div>

          <!-- 右：实时预览 -->
          <aside class="pz-right">
            <div class="card preview-card">
              <div class="pv-head">
                <div>
                  <div class="pv-title">选点顺序预览</div>
                  <div class="small muted">
                    {{ previewLoading ? '重新计算中…' : '按当前权重重排的候选点位' }}
                  </div>
                </div>
                <span v-if="previewPersonalized" class="tag orange">已个性化</span>
                <span v-else class="tag gray">模式默认</span>
              </div>

              <div v-if="!preview.length" class="empty">暂无可预览的候选点</div>
              <div v-else class="pv-list">
                <div v-for="it in preview" :key="it.poi_id" class="pv-item">
                  <div class="pv-rank">{{ it.rank }}</div>
                  <div v-if="it.image" class="pv-thumb">
                    <img :src="it.image" :alt="it.name" loading="lazy" />
                  </div>
                  <div v-else class="pv-thumb pv-thumb-empty">📍</div>
                  <div class="pv-body">
                    <div class="pv-name">{{ it.name }}</div>
                    <div class="small muted">
                      {{ CATEGORY_LABEL[it.category] || it.category }} · ★ {{ it.rating?.toFixed(1) }} ·
                      {{ it.ticket_price > 0 ? '¥' + it.ticket_price : '免费' }}
                    </div>
                    <div class="small score-line">
                      综合分 {{ it.score.toFixed(3) }}
                      <span :class="it.score > it.base_score ? 'up' : (it.score < it.base_score ? 'down' : '')">
                        {{ scoreText(it) }}
                      </span>
                    </div>
                  </div>
                  <div class="pv-delta" :class="{ up: it.rank < it.base_rank, down: it.rank > it.base_rank }">
                    {{ it.rank < it.base_rank ? '↑' + (it.base_rank - it.rank) : (it.rank > it.base_rank ? '↓' + (it.rank - it.base_rank) : '–') }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 变化提示 -->
            <div v-if="changed.length" class="card changed-card">
              <div class="pv-title" style="margin-bottom: 10px">与模式默认的差异</div>
              <div class="ch-list">
                <span v-for="c in changed" :key="c.poi_id" class="ch-item"
                      :class="c.direction">
                  {{ c.direction === 'up' ? '▲' : '▼' }} {{ c.name }}
                </span>
              </div>
              <div class="small muted" style="margin-top: 10px">
                ▲ 表示新权重下更靠前，▼ 表示被挤出前列
              </div>
            </div>

            <!-- 权重画像 -->
            <div class="card profile-card">
              <div class="pv-title" style="margin-bottom: 12px">当前权重画像</div>
              <div class="pf-bar">
                <span v-for="d in dimensions" :key="d.key"
                      :title="`${d.label} ${percentMap[d.key]}%`"
                      :style="{ width: percentMap[d.key] + '%' }"></span>
              </div>
              <div class="pf-legend">
                <span v-for="d in dimensions" :key="d.key" class="pf-item">
                  {{ d.icon }} {{ d.label }} {{ percentMap[d.key] }}%
                </span>
              </div>
            </div>

            <div class="action-card">
              <button v-if="targetTripId" class="btn btn-primary btn-block"
                      :disabled="submitting" @click="reweight">
                {{ submitting ? '重排中…' : '按新权重重排这条行程' }}
              </button>
              <button v-else class="btn btn-primary btn-block"
                      :disabled="submitting" @click="generate">
                {{ submitting ? '生成中…' : '生成个性化行程 →' }}
              </button>
              <div class="small muted" style="margin-top: 10px; line-height: 1.8">
                权重只改变"选点优先级"，预算、时间窗、不重复等硬约束始终生效；
                生成后仍可在行程详情里逐个槽位替换。
              </div>
            </div>
          </aside>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.pz-layout { display: grid; grid-template-columns: 1fr 380px; gap: 22px; align-items: start; }
.pz-left { display: flex; flex-direction: column; gap: 18px; }
.block { padding: 22px; }
.block-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.block-title i {
  width: 22px; height: 22px; border-radius: 50%; background: var(--brand);
  color: #fff; font-size: 12px; font-style: normal; display: grid; place-items: center;
}
.mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.mode-opt {
  border: 1.5px solid var(--line); border-radius: 12px; padding: 12px 6px;
  text-align: center; cursor: pointer; transition: all .15s ease;
}
.mode-opt:hover { border-color: var(--brand); }
.mode-opt.on { border-color: var(--brand); background: var(--brand-light); }
.mode-e { display: block; font-size: 22px; }
.mode-n { font-size: 13px; font-weight: 600; }

.preset-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.preset {
  border: 1.5px solid var(--line); border-radius: 12px; padding: 12px;
  text-align: left; cursor: pointer; background: #fff; transition: all .15s ease;
  display: flex; flex-direction: column; gap: 4px; min-height: 96px;
}
.preset:hover { border-color: var(--brand); }
.preset.on { border-color: var(--brand); background: var(--brand-light); }
.p-icon { font-size: 18px; line-height: 1.3; }
.p-label { font-size: 14px; font-weight: 700; line-height: 1.3; }
.p-desc { font-size: 12px; color: var(--muted); line-height: 1.5; flex: 1; }

.slider-row { padding: 10px 0; border-bottom: 1px dashed var(--line); }
.slider-row:last-of-type { border-bottom: none; }
.slider-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.s-icon { font-size: 16px; }
.s-label { font-size: 14px; font-weight: 600; flex: 1; }
.s-pct { font-size: 13px; color: var(--brand); font-weight: 700; }
.slider { width: 100%; }
.s-hint { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.5; }
.slider-total {
  display: flex; justify-content: space-between; align-items: center;
  gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line);
  flex-wrap: wrap;
}

.pace-row { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
.range { width: 100%; accent-color: var(--brand); }
.chips { display: flex; gap: 9px; flex-wrap: wrap; }

.pz-right { display: flex; flex-direction: column; gap: 16px; position: sticky; top: 80px; }
.preview-card, .changed-card, .profile-card { padding: 20px; }
.pv-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 14px; }
.pv-title { font-weight: 700; font-size: 15px; }
.pv-list { max-height: 460px; overflow: auto; }
.pv-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 0; border-bottom: 1px solid var(--line);
}
.pv-item:last-child { border-bottom: none; }
.pv-rank {
  width: 22px; height: 22px; border-radius: 50%; background: var(--brand-light);
  color: var(--brand); font-size: 12px; font-weight: 700;
  display: grid; place-items: center; flex: none;
}
.pv-thumb { width: 52px; height: 40px; border-radius: 8px; overflow: hidden; flex: none; border: 1px solid var(--line); }
.pv-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.pv-thumb-empty { display: grid; place-items: center; background: #f4f6f5; font-size: 16px; }
.pv-body { flex: 1; min-width: 0; }
.pv-name { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.score-line { color: var(--muted); }
.score-line .up { color: #c0453b; margin-left: 6px; }
.score-line .down { color: #2f7d5c; margin-left: 6px; }
.pv-delta { font-size: 13px; font-weight: 700; color: var(--muted); min-width: 42px; text-align: right; flex: none; white-space: nowrap; }
.pv-delta.up { color: #c0453b; }
.pv-delta.down { color: #2f7d5c; }

.ch-list { display: flex; flex-wrap: wrap; gap: 8px; }
.ch-item { font-size: 12px; padding: 4px 10px; border-radius: 999px; }
.ch-item.up { background: #fdeeec; color: #c0453b; }
.ch-item.down { background: #eaf5ef; color: #2f7d5c; }

.pf-bar { display: flex; height: 12px; border-radius: 999px; overflow: hidden; background: #eef1ef; }
.pf-bar span:nth-child(1) { background: #2f7d5c; }
.pf-bar span:nth-child(2) { background: #4a9c78; }
.pf-bar span:nth-child(3) { background: #e6803a; }
.pf-bar span:nth-child(4) { background: #c9a227; }
.pf-bar span:nth-child(5) { background: #6b8fce; }
.pf-bar span:nth-child(6) { background: #9b7ede; }
.pf-bar span:nth-child(7) { background: #55b8b0; }
.pf-bar span:nth-child(8) { background: #d98c9f; }
.pf-legend { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 12px; }
.pf-item { font-size: 12px; color: #5b6b64; }

.action-card { background: var(--brand-light); border-radius: var(--radius); padding: 18px; }
.btn-block { width: 100%; }

@media (max-width: 980px) {
  .pz-layout { grid-template-columns: 1fr; }
  .pz-right { position: static; }
  .preset-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .mode-grid { grid-template-columns: repeat(2, 1fr); }
  .pace-row, .form-row { grid-template-columns: 1fr; }
}
</style>
