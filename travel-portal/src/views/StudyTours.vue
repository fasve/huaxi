<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  api, MODE_EMOJI, toast,
  type PresetRouteDetail, type PresetRouteSummary, type PresetStop,
} from '../api'

const router = useRouter()
const routes = ref<PresetRouteSummary[]>([])
const detail = ref<PresetRouteDetail | null>(null)
const loading = ref(true)
const loadingDetail = ref(false)
const visitDate = ref(today())
const selectedCode = ref('')
const includeAddon = ref(false)
const expandedSources = ref(false)

const gen = ref({ mode: 'leisure', days: 1, budget: 600 })
const submitting = ref(false)

const MODE_LABEL: Record<string, string> = {
  leisure: '休闲游', blitz: '特种兵游', premium: '高端游', checkin: '打卡游',
}
const MODE_KEYS = ['leisure', 'blitz', 'premium', 'checkin']

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtMin(v: number): string {
  const n = Math.round(v || 0)
  return n >= 60 ? `${Math.floor(n / 60)}小时${n % 60 ? ` ${n % 60}分` : ''}` : `${n} 分钟`
}

const GATE_META: Record<string, { label: string; cls: string; icon: string }> = {
  open: { label: '正常开放', cls: 'ok', icon: '✓' },
  reminder: { label: '需预约', cls: 'info', icon: '!' },
  degraded: { label: '已降级', cls: 'warn', icon: '↻' },
  replaced: { label: '已替换', cls: 'warn', icon: '⇄' },
}
function gateMeta(s: string) { return GATE_META[s] || GATE_META.open }

const activeStops = computed<PresetStop[]>(() => {
  if (!detail.value) return []
  const base = detail.value.stops || []
  const addon = includeAddon.value ? (detail.value.addon_stops || []) : []
  return [...base, ...addon].sort((a, b) => a.seq - b.seq)
})

const mustStops = computed(() => activeStops.value.filter((s) => s.must_visit))
const totalMinutes = computed(() => mustStops.value.reduce(
  (sum, s) => sum + (s.effective_stay_min || s.stay_min) + s.walk_in_min, 0,
))

async function loadList() {
  loading.value = true
  try {
    const r = await api.getPresetRoutes({ visit_date: visitDate.value })
    routes.value = r.items || []
    if (!selectedCode.value && routes.value.length) {
      selectedCode.value = routes.value[0].code
    }
    if (!routes.value.some((x) => x.code === selectedCode.value)) {
      selectedCode.value = routes.value[0]?.code || ''
    }
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function loadDetail() {
  if (!selectedCode.value) { detail.value = null; return }
  loadingDetail.value = true
  try {
    detail.value = await api.getPresetRoute(selectedCode.value, {
      visit_date: visitDate.value,
      // 加段在本地切换，避免每次勾选都打接口
      include_addon: false,
    })
  } catch { detail.value = null } finally {
    loadingDetail.value = false
  }
}

onMounted(async () => {
  await loadList()
  await loadDetail()
})
watch(visitDate, async () => { await loadList(); await loadDetail() })
watch(selectedCode, loadDetail)

async function oneClickGenerate() {
  if (!detail.value) return
  if (gen.value.budget <= 0) { toast('请输入有效预算', true); return }
  submitting.value = true
  try {
    const trip = await api.generateTrip({
      days: gen.value.days,
      budget: gen.value.budget,
      mode: gen.value.mode,
      preferences: [],
      party_type: gen.value.mode === 'premium' ? 'couple' : 'family',
      seed: Math.floor(Math.random() * 9999),
      preset_route_code: detail.value.code,
      visit_date: visitDate.value,
      include_addon: includeAddon.value,
    })
    toast('游学行程已生成')
    router.push({ path: `/trip/${trip.trip_id}` })
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}

function goPlan() {
  router.push({ path: '/plan' })
}
</script>

<template>
  <div class="container study-page">
    <!-- Hero -->
    <section class="study-hero">
      <div class="hero-copy">
        <div class="eyebrow">🎓 预设主题路线 · G7</div>
        <h1>跟着一条线，读懂花溪</h1>
        <p class="hero-sub">
          官方编排的游学动线：逐站讲解、研学任务卡、拍照提示与入校政策一次给全。
          选好出行日期，系统会自动判断校史馆是否开放、樱花是否当季，不满足就帮你降级或换站。
        </p>
        <div class="hero-tags">
          <span>🏫 百年贵大</span><span>🚶 全程步行</span>
          <span>📝 研学任务卡</span><span>🗓 日期感知</span>
        </div>
      </div>
      <div class="date-card">
        <label for="visit-date">出行日期</label>
        <input id="visit-date" v-model="visitDate" type="date" />
        <div v-if="detail" class="date-summary" :class="detail.day.tone">
          <strong>{{ detail.day.date }} · 周{{ detail.day.weekday }} · {{ detail.day.day_type }}</strong>
          <span>{{ detail.day.note }}</span>
        </div>
        <div class="date-hint">日期只影响讲解与到站建议，不会阻断生成</div>
      </div>
    </section>

    <div v-if="loading" class="card loading-box">线路加载中…</div>

    <template v-else-if="routes.length">
      <!-- 线路卡片 -->
      <section class="section">
        <div class="section-head">
          <div>
            <h2 class="section-title">主题线路</h2>
            <div class="section-sub">点选线路查看逐站讲解；每站都可按日期自动调整</div>
          </div>
        </div>
        <div class="route-grid">
          <button
            v-for="r in routes" :key="r.code"
            class="route-card" :class="{ on: selectedCode === r.code }"
            @click="selectedCode = r.code"
          >
            <div class="rc-top">
              <span class="rc-badge">{{ r.theme_name }}</span>
              <span class="rc-dur">约 {{ r.duration_hours }} 小时</span>
            </div>
            <h3>{{ r.title }}</h3>
            <p>{{ r.subtitle }}</p>
            <div class="rc-meta">
              <span>👥 {{ r.target_group }}</span>
              <span>📍 {{ r.stop_count }} 站</span>
              <span>🧭 {{ r.difficulty }}</span>
            </div>
          </button>
        </div>
      </section>

      <template v-if="detail">
        <!-- 线路概览 + 预约 -->
        <section class="section detail-block">
          <div class="detail-grid">
            <div class="card intro-card">
              <h2 class="section-title">{{ detail.title }}</h2>
              <p class="intro-text">{{ detail.summary }}</p>
              <div class="stat-row">
                <div><b>{{ mustStops.length }}</b><span>必走站点</span></div>
                <div><b>{{ fmtMin(totalMinutes) }}</b><span>预计用时</span></div>
                <div><b>{{ detail.total_walk_min }} 分</b><span>校内步行</span></div>
                <div><b>¥0</b><span>站点门票</span></div>
              </div>
              <div class="season-line" v-if="detail.season_window?.start">
                🌸 花期窗口 {{ detail.season_window.start }} — {{ detail.season_window.end }}；
                错季自动替换为常年常绿景观
              </div>
              <div class="mode-tips">
                <div class="mt-title">四种模式怎么走这条线</div>
                <div v-for="m in MODE_KEYS" :key="m" class="mt-row">
                  <span>{{ MODE_EMOJI[m] }} {{ MODE_LABEL[m] }}</span>
                  <span>{{ detail.mode_tips?.[m] || '按模式节奏自由补全' }}</span>
                </div>
              </div>
            </div>

            <div class="card reservation-card">
              <div class="res-head">⚠️ 入校前必读</div>
              <p>{{ detail.reservation_note }}</p>
              <div class="res-action" v-if="detail.reservation">
                📌 {{ (detail.reservation as any).channel }} · 建议提前
                {{ (detail.reservation as any).lead_days || 1 }} 天办理
              </div>
              <div class="res-transit">🚌 {{ detail.transit_note }}</div>
              <div class="gate-note-list" v-if="detail.gate_notes.length">
                <div class="gn-title">本次日期的自动调整（{{ detail.gate_notes.length }}）</div>
                <div v-for="(n, i) in detail.gate_notes" :key="i" class="gn-item">{{ n }}</div>
              </div>
              <div class="res-foot">政策校验日期：{{ detail.policy_checked_at || '未登记' }}</div>
            </div>
          </div>
        </section>

        <!-- 逐站讲解 -->
        <section class="section">
          <div class="section-head">
            <div>
              <h2 class="section-title">逐站讲解与研学任务</h2>
              <div class="section-sub">按站点顺序行走；衔接口径为校内实测步行时长，不走外部路径规划</div>
            </div>
            <label class="addon-toggle">
              <input type="checkbox" v-model="includeAddon" />
              并入全天深度版（南校区文保建筑群 +90 分钟）
            </label>
          </div>

          <div v-if="loadingDetail" class="card loading-box">站点加载中…</div>
          <div v-else class="stop-list">
            <article
              v-for="(s, idx) in activeStops" :key="s.seq"
              class="stop-card card" :class="{ addon: s.is_addon, optional: !s.must_visit }"
            >
              <div class="stop-rail">
                <div class="stop-no">{{ s.seq }}</div>
                <div v-if="idx < activeStops.length - 1" class="stop-line"></div>
              </div>
              <div class="stop-body">
                <div class="stop-head">
                  <div>
                    <h3>{{ s.narration_title }}</h3>
                    <div class="stop-place">
                      📍 {{ s.name }}
                      <span v-if="s.gate.replaced" class="replaced-tag">
                        原为「{{ s.original_name }}」
                      </span>
                      <span v-if="s.is_addon" class="addon-tag">深度加段</span>
                      <span v-if="!s.must_visit" class="optional-tag">弹性站</span>
                    </div>
                  </div>
                  <span class="gate-badge" :class="gateMeta(s.gate.status).cls">
                    {{ gateMeta(s.gate.status).icon }} {{ gateMeta(s.gate.status).label }}
                  </span>
                </div>

                <div class="stop-facts">
                  <span>⏱ 停留 {{ s.effective_stay_min || s.stay_min }} 分</span>
                  <span>🚶 上一站步行 {{ s.walk_in_min }} 分</span>
                  <span>🕐 {{ s.slot === 'morning' ? '上午' : '下午' }}</span>
                  <span v-if="s.gate.suggest_arrival">建议 {{ s.gate.suggest_arrival }} 到站</span>
                  <span v-if="s.gate.effective_stay_min && s.gate.effective_stay_min !== s.stay_min"
                        class="fact-warn">已压缩时长</span>
                </div>

                <p class="narration">{{ s.narration_text }}</p>

                <div class="stop-cards">
                  <div v-for="(t, ti) in s.task_cards" :key="ti" class="task-card">
                    <span class="tc-label">📝 {{ t.title || '研学任务' }}<i v-if="t.type"> · {{ t.type }}</i></span>
                    <span>{{ t.content }}</span>
                  </div>
                  <div v-if="s.photo_tip" class="photo-card">
                    <span class="tc-label">📷 拍照提示</span><span>{{ s.photo_tip }}</span>
                  </div>
                </div>

                <div v-if="s.gate.notes.length" class="gate-notes">
                  <div v-for="(n, ni) in s.gate.notes" :key="ni">↳ {{ n }}</div>
                </div>
                <div v-if="s.visit_policy" class="visit-policy">🏛 {{ s.visit_policy }}</div>
              </div>
            </article>
          </div>
        </section>

        <!-- 来源与待核 -->
        <section class="section sources">
          <button class="src-toggle" @click="expandedSources = !expandedSources">
            信息来源与待核字段（{{ detail.sources.length }} 项，其中
            {{ detail.unverified_sources.length }} 项待核准）{{ expandedSources ? ' ▲' : ' ▼' }}
          </button>
          <div v-if="expandedSources" class="src-list card">
            <div v-for="(s, i) in detail.sources" :key="i" class="src-row">
              <span :class="s.verified ? 'src-ok' : 'src-warn'">{{ s.verified ? '已核验' : '待核准' }}</span>
              <div><b>{{ s.item }}</b><span>{{ s.source }}</span>
                <p v-if="s.note">{{ s.note }}</p>
              </div>
            </div>
          </div>
        </section>

        <!-- 一键成程 -->
        <section class="section generate-block">
          <div class="card gen-card">
            <div class="gen-copy">
              <h2>一键成程：半天游学 + 半天自由游</h2>
              <p>
                游学站点按序预占第 1 天，剩余槽位由「{{ MODE_LABEL[gen.mode] }}」模式自动补全花溪资源；
                预算、时间窗、用餐与住宿仍由引擎统一校验。
              </p>
            </div>
            <div class="gen-form">
              <div class="gf-row">
                <label>自由游模式</label>
                <div class="mode-chips">
                  <button v-for="m in MODE_KEYS" :key="m"
                          class="chip" :class="{ on: gen.mode === m }" @click="gen.mode = m">
                    {{ MODE_EMOJI[m] }} {{ MODE_LABEL[m] }}
                  </button>
                </div>
              </div>
              <div class="gf-row gf-inline">
                <label>天数 <input v-model.number="gen.days" type="number" min="1" max="7" /></label>
                <label>总预算 ¥ <input v-model.number="gen.budget" type="number" min="100" step="100" /></label>
              </div>
              <button class="btn btn-primary gen-btn" :disabled="submitting" @click="oneClickGenerate">
                {{ submitting ? '生成中…' : '生成游学行程 →' }}
              </button>
              <button class="btn btn-soft gen-alt" @click="goPlan">只要普通定制行程</button>
            </div>
          </div>
        </section>
      </template>
    </template>

    <div v-else class="card empty-box">
      <h3>暂无启用的主题路线</h3>
      <p>线路可能处于季节性停用状态，可在管理后台「预设路线」中重新启用。</p>
      <button class="btn btn-soft" @click="goPlan">去定制普通行程</button>
    </div>
  </div>
</template>

<style scoped>
.study-page { padding-top: 28px; }
.section { margin-top: 34px; }
.section-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.section-title { font-size: 22px; font-weight: 700; color: var(--ink); margin: 0 0 4px; }
.section-sub { font-size: 13px; color: var(--muted); }
.card { background: #fff; border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 2px 12px rgba(28, 60, 46, .05); }
.loading-box, .empty-box { padding: 40px; text-align: center; color: var(--muted); }
.empty-box h3 { color: var(--ink); margin-bottom: 8px; }

/* Hero */
.study-hero {
  display: grid; grid-template-columns: 1.5fr 1fr; gap: 26px; align-items: center;
  padding: 34px; border-radius: 18px;
  background: linear-gradient(120deg, #eaf5ee 0%, #f4f8f4 55%, #fff7e8 100%);
  border: 1px solid var(--line);
}
.eyebrow { font-size: 12px; font-weight: 700; color: var(--brand); letter-spacing: .6px; }
.hero-copy h1 { font-size: 32px; color: var(--brand-dark); margin: 10px 0 12px; }
.hero-sub { font-size: 14px; line-height: 1.8; color: #4c5d54; max-width: 620px; }
.hero-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.hero-tags span { background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 5px 12px; font-size: 12px; color: #4c5d54; }
.date-card { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 20px; box-shadow: 0 4px 16px rgba(28,60,46,.06); }
.date-card label { display: block; font-size: 13px; font-weight: 600; color: var(--ink); margin-bottom: 8px; }
.date-card input { width: 100%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; font-size: 15px; color: var(--ink); background: #fff; }
.date-summary { margin-top: 14px; border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.date-summary strong { font-size: 13px; }
.date-summary span { font-size: 12px; line-height: 1.6; }
.date-summary.ok { background: #eef8f1; color: #1e6b45; }
.date-summary.warn { background: #fff5e6; color: #95591a; }
.date-hint { font-size: 11px; color: var(--muted); margin-top: 10px; }

/* 线路卡 */
.route-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.route-card { text-align: left; background: #fff; border: 1.5px solid var(--line); border-radius: 14px; padding: 18px; cursor: pointer; transition: all .15s ease; font: inherit; color: inherit; }
.route-card:hover { border-color: var(--brand); transform: translateY(-2px); }
.route-card.on { border-color: var(--brand); background: var(--brand-light); box-shadow: 0 4px 14px rgba(47,125,92,.12); }
.rc-top { display: flex; justify-content: space-between; align-items: center; }
.rc-badge { font-size: 11px; font-weight: 700; color: var(--brand); background: var(--brand-light); border-radius: 999px; padding: 3px 10px; }
.rc-dur { font-size: 12px; color: var(--muted); }
.route-card h3 { font-size: 17px; margin: 12px 0 6px; color: var(--ink); }
.route-card p { font-size: 13px; color: var(--muted); line-height: 1.6; min-height: 40px; }
.rc-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; font-size: 12px; color: #5b6b64; }

/* 概览 */
.detail-grid { display: grid; grid-template-columns: 1.25fr 1fr; gap: 16px; }
.intro-card, .reservation-card { padding: 22px; }
.intro-text { font-size: 14px; line-height: 1.85; color: #4c5d54; }
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 18px 0; padding: 14px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.stat-row div { display: flex; flex-direction: column; gap: 3px; }
.stat-row b { font-size: 17px; color: var(--brand-dark); }
.stat-row span { font-size: 11px; color: var(--muted); }
.season-line { font-size: 13px; color: #95591a; background: #fff8ec; border-radius: 8px; padding: 10px 12px; }
.mode-tips { margin-top: 16px; }
.mt-title { font-size: 13px; font-weight: 700; color: var(--ink); margin-bottom: 8px; }
.mt-row { display: grid; grid-template-columns: 110px 1fr; gap: 10px; font-size: 12px; color: #5b6b64; padding: 5px 0; border-bottom: 1px dashed var(--line); }
.mt-row span:first-child { font-weight: 600; color: var(--ink); }
.res-head { font-size: 15px; font-weight: 700; color: #95591a; margin-bottom: 10px; }
.reservation-card > p { font-size: 13px; line-height: 1.8; color: #4c5d54; }
.res-action { margin-top: 12px; background: #fff5e6; color: #95591a; border-radius: 8px; padding: 10px 12px; font-size: 12px; line-height: 1.6; }
.res-transit { margin-top: 10px; font-size: 12px; line-height: 1.7; color: var(--muted); }
.gate-note-list { margin-top: 14px; border-top: 1px dashed var(--line); padding-top: 12px; }
.gn-title { font-size: 12px; font-weight: 700; color: var(--ink); margin-bottom: 6px; }
.gn-item { font-size: 12px; color: #95591a; line-height: 1.7; }
.res-foot { margin-top: 14px; font-size: 11px; color: var(--muted); }

/* 站点 */
.addon-toggle { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink); cursor: pointer; }
.stop-list { display: flex; flex-direction: column; gap: 14px; }
.stop-card { display: grid; grid-template-columns: 54px 1fr; gap: 6px; padding: 20px 20px 20px 14px; }
.stop-card.addon { background: #fbfcfb; border-style: dashed; }
.stop-card.optional { opacity: .9; }
.stop-rail { display: flex; flex-direction: column; align-items: center; }
.stop-no { width: 34px; height: 34px; border-radius: 50%; background: var(--brand); color: #fff; font-weight: 700; display: grid; place-items: center; font-size: 14px; }
.stop-card.addon .stop-no { background: #8aa79a; }
.stop-line { flex: 1; width: 2px; background: var(--line); margin-top: 8px; min-height: 30px; }
.stop-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.stop-head h3 { font-size: 16px; color: var(--ink); margin: 2px 0 5px; }
.stop-place { font-size: 12px; color: var(--muted); }
.replaced-tag, .addon-tag, .optional-tag { margin-left: 8px; border-radius: 999px; padding: 2px 8px; font-size: 11px; }
.replaced-tag { background: #fff1dc; color: #95591a; }
.addon-tag { background: #eaf1ed; color: var(--brand-dark); }
.optional-tag { background: #f0f2f1; color: var(--muted); }
.gate-badge { white-space: nowrap; font-size: 11px; font-weight: 600; border-radius: 999px; padding: 4px 10px; }
.gate-badge.ok { background: #eaf7ef; color: #1e6b45; }
.gate-badge.info { background: #e9f1fb; color: #2d5f9e; }
.gate-badge.warn { background: #fff1dc; color: #95591a; }
.stop-facts { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 10px; }
.stop-facts span { font-size: 11px; color: #5b6b64; background: #f4f7f5; border-radius: 6px; padding: 4px 9px; }
.stop-facts .fact-warn { background: #fff1dc; color: #95591a; }
.narration { font-size: 13px; line-height: 1.85; color: #41534a; margin: 0 0 12px; }
.stop-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
.task-card, .photo-card { border-radius: 10px; padding: 11px 13px; display: flex; flex-direction: column; gap: 5px; font-size: 12px; line-height: 1.6; }
.task-card { background: #eef7f1; color: #245c42; }
.photo-card { background: #f3f1fb; color: #55468c; }
.tc-label { font-weight: 700; font-size: 12px; }
.tc-label i { font-style: normal; font-weight: 400; opacity: .75; }
.gate-notes { margin-top: 10px; font-size: 12px; color: #95591a; line-height: 1.7; }
.visit-policy { margin-top: 10px; font-size: 11px; color: var(--muted); line-height: 1.6; }

/* 来源 */
.src-toggle { background: none; border: none; color: var(--brand); font-size: 13px; cursor: pointer; padding: 0; }
.src-list { padding: 16px; margin-top: 10px; }
.src-row { display: grid; grid-template-columns: 66px 1fr; gap: 12px; padding: 9px 0; border-bottom: 1px dashed var(--line); font-size: 12px; }
.src-row:last-child { border-bottom: none; }
.src-row > span { border-radius: 6px; padding: 3px 6px; text-align: center; height: fit-content; }
.src-ok { background: #eaf7ef; color: #1e6b45; }
.src-warn { background: #fff1dc; color: #95591a; }
.src-row b { display: block; color: var(--ink); }
.src-row span { color: var(--muted); }
.src-row p { color: #95591a; margin: 4px 0 0; }

/* 一键成程 */
.gen-card { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; padding: 24px; background: linear-gradient(110deg, #f2f9f4, #fff); }
.gen-copy h2 { font-size: 20px; color: var(--brand-dark); margin-bottom: 10px; }
.gen-copy p { font-size: 13px; line-height: 1.8; color: #4c5d54; }
.gf-row { margin-bottom: 12px; }
.gf-row > label { display: block; font-size: 12px; font-weight: 600; color: var(--ink); margin-bottom: 7px; }
.gf-inline { display: flex; gap: 12px; }
.gf-inline label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink); }
.gf-inline input { width: 88px; padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; color: var(--ink); }
.mode-chips { display: flex; flex-wrap: wrap; gap: 7px; }
.chip { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 6px 12px; font-size: 12px; color: #5b6b64; cursor: pointer; }
.chip.on { border-color: var(--brand); background: var(--brand); color: #fff; font-weight: 600; }
.gen-btn { width: 100%; margin-top: 4px; padding: 11px; }
.gen-alt { width: 100%; margin-top: 8px; }

@media (max-width: 900px) {
  .study-hero, .detail-grid, .gen-card { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
