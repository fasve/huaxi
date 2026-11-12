<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, tripToText, type Poi, type Trip, type TripItem,
         type PresetItemMeta, toast } from '../api'
import { requireLogin } from '../auth'
import { getBasket, removeFromBasket, type BasketItem } from '../basket'
import WeatherCard from '../components/WeatherCard.vue'
import TMap from '../components/TMap.vue'
import type { MapPoint, RouteLegSummary } from '../components/amap'

const route = useRoute()
const router = useRouter()
const tripId = computed(() => String(route.params.id || ''))
const trip = ref<Trip | null>(null)
const loading = ref(true)

/** 槽位是否为游学保底站；返回逐站讲解与任务卡，普通点位返回 null */
function presetOf(it: TripItem): PresetItemMeta | null {
  const p = it.preset
  return p && 'seq' in p && p.seq ? (p as PresetItemMeta) : null
}

/** 行程点位：酒店作为每天出发点，之后按行程顺序串联，地图上按出行方式规划路线 */
const mapPoints = computed<MapPoint[]>(() => {
  const out: MapPoint[] = []
  const hotel = trip.value?.hotel
  trip.value?.days_plan.forEach((d) => {
    const group = `Day ${d.day_index}`
    // 酒店 → 当天出发点
    if (hotel?.longitude && hotel?.latitude) {
      out.push({
        id: `${d.day_index}-hotel`,
        name: hotel.name,
        lng: hotel.longitude,
        lat: hotel.latitude,
        address: `Day ${d.day_index} · 住宿`,
        label: `${d.day_index}-住`,
        group,
      })
    }
    d.items.forEach((it, idx) => {
      if (it.longitude && it.latitude) {
        out.push({
          id: `${d.day_index}-${idx}`,
          name: it.name,
          lng: it.longitude,
          lat: it.latitude,
          address: `Day ${d.day_index} · ${it.start_time} · ${it.slot_name}`,
          label: `${d.day_index}-${idx + 1}`,
          group,
        })
      }
    })
  })
  return out
})

// 路线规划结果（来自地图组件），用于时间轴每段之间的交通提示
const routeLegsMap = ref<Record<string, RouteLegSummary>>({})
function onRoutes(legs: RouteLegSummary[]) {
  const m: Record<string, RouteLegSummary> = {}
  legs.forEach((l) => { m[`${l.dayIndex}:${l.fromSeq}:${l.toSeq}`] = l })
  routeLegsMap.value = m
}
function legBetween(dayIndex: number, idx: number) {
  if (idx <= 0) return undefined
  return routeLegsMap.value[`${dayIndex}:${idx - 1}:${idx}`]
}
const TM_ICON: Record<string, string> = { driving: '🚗', transit: '🚌', walking: '🚶', riding: '🚲' }
function fmtDist(m: number): string {
  return m >= 1000 ? (m / 1000).toFixed(1) + 'km' : Math.round(m) + 'm'
}
function fmtDur(s: number): string {
  if (s >= 3600) {
    const h = Math.floor(s / 3600)
    const m = Math.round((s % 3600) / 60)
    return m ? `${h}小时${m}分` : `${h}小时`
  }
  if (s >= 60) return Math.round(s / 60) + '分'
  return Math.max(1, Math.round(s)) + '秒'
}
const saving = ref(false)
const busy = ref(false)

// 槽位替换弹层
const replaceFor = ref<{ day: number; slot: string } | null>(null)
const candidates = ref<Poi[]>([])
const candidateLoading = ref(false)

const SLOT_ICON: Record<string, string> = {
  morning: '🌅', lunch: '🍜', afternoon: '☀️', dinner: '🍲', evening: '🌙',
}

async function load() {
  loading.value = true
  try {
    trip.value = await api.getTrip(tripId.value)
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---------- 待计划篮子（发现页收藏 → 行程页排入某天） ----------
const waitBasket = ref<BasketItem[]>([])
const waitDay = ref(1)
const addingWait = ref(false)

function refreshWaitBasket() {
  waitBasket.value = getBasket()
}

function dropWait(poiId: number) {
  removeFromBasket(poiId)
  refreshWaitBasket()
}

async function addWaitToDay() {
  if (!waitBasket.value.length) return
  const count = waitBasket.value.length
  addingWait.value = true
  try {
    for (const it of waitBasket.value) {
      await api.addTripItem(tripId.value, it.poi_id, waitDay.value)
    }
    waitBasket.value.forEach((it) => removeFromBasket(it.poi_id))
    refreshWaitBasket()
    await load()
    toast(`已把 ${count} 个点位排入第 ${waitDay.value} 天`)
  } catch (e: any) {
    toast(e?.message || '排入失败', true)
  } finally {
    addingWait.value = false
  }
}

refreshWaitBasket()

async function redrop(day: number) {
  busy.value = true
  try {
    await api.rebalance(tripId.value, { day_index: day, action: 'redrop' })
    toast(`第 ${day} 天已重新安排`)
    await load()
  } finally {
    busy.value = false
  }
}

async function openReplace(day: number, slot: string) {
  replaceFor.value = { day, slot }
  candidates.value = []
  candidateLoading.value = true
  try {
    const res = await api.slotCandidates(tripId.value, day, slot)
    candidates.value = res.items || []
  } finally {
    candidateLoading.value = false
  }
}

async function applyReplace(poiId: number) {
  if (!replaceFor.value) return
  busy.value = true
  try {
    await api.rebalance(tripId.value, {
      day_index: replaceFor.value.day,
      action: 'replace',
      slot: replaceFor.value.slot,
      poi_id: poiId,
    })
    replaceFor.value = null
    toast('已替换该槽位')
    await load()
  } finally {
    busy.value = false
  }
}

async function saveTrip() {
  if (!requireLogin(router, route.fullPath)) {
    toast('登录后才能保存行程')
    return
  }
  saving.value = true
  try {
    await api.saveTrip(tripId.value)
    toast('已保存到我的行程')
  } finally {
    saving.value = false
  }
}

function printTrip() {
  window.print()
}

function exportTrip() {
  if (!trip.value) return
  const blob = new Blob(['\ufeff' + tripToText(trip.value)], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `花溪行程_${trip.value.mode_name}_${tripId.value}.txt`
  a.click()
  URL.revokeObjectURL(url)
  toast('行程单已导出')
}
</script>

<template>
  <div class="container">
    <div v-if="loading" class="empty">行程加载中…</div>
    <div v-else-if="!trip" class="empty">行程不存在或已被删除</div>

    <template v-else>
      <div class="print-title">
        <h1>花溪旅行 · {{ trip.mode_name }} {{ trip.days }} 天行程单</h1>
        <p>预算 ¥{{ trip.budget }} ｜ 预估花费 ¥{{ trip.total_cost }}</p>
      </div>

      <section class="section">
        <div class="section-head no-print">
          <div>
            <h1 class="section-title">{{ trip.mode_name }} · {{ trip.days }} 天行程</h1>
            <div class="section-sub">行程编号 {{ trip.trip_id }} · 可随时调整任一槽位</div>
          </div>
          <div class="head-links">
            <router-link
              :to="{ path: '/personalize', query: { trip: trip.trip_id, mode: trip.mode, days: trip.days, budget: trip.budget } }"
              class="small brand-text"
            >按权重调整路线 →</router-link>
            <router-link to="/plan" class="small brand-text">← 重新定制</router-link>
          </div>
        </div>

        <!-- 待计划篮子：从发现页加入的点位先放这里，再一键排入某天 -->
        <div v-if="waitBasket.length" class="card wait-card no-print">
          <div class="wait-head">
            <b>待计划 <span class="wait-count">{{ waitBasket.length }}</span></b>
            <span class="small muted">在「发现花溪」点「＋待计划」收藏，再选一天一键排入</span>
          </div>
          <div class="wait-list">
            <div v-for="it in waitBasket" :key="it.poi_id" class="wait-item">
              <span class="wait-name">{{ it.name }}</span>
              <span class="small muted">{{ it.category }}</span>
              <button class="btn btn-sm" @click="dropWait(it.poi_id)">移除</button>
            </div>
          </div>
          <div class="wait-foot">
            <label class="small muted">排入</label>
            <select v-model.number="waitDay" class="select wait-day">
              <option v-for="d in trip.days" :key="d" :value="d">第 {{ d }} 天</option>
            </select>
            <button class="btn btn-primary btn-sm" :disabled="addingWait" @click="addWaitToDay">
              {{ addingWait ? '排入中…' : '一键排入' }}
            </button>
          </div>
        </div>

        <!-- 总览 -->
        <div class="card overview">
          <div class="ov-item"><span class="muted small">旅行模式</span><b>{{ trip.mode_name }}</b></div>
          <div class="ov-item"><span class="muted small">人均预算</span><b>¥{{ trip.budget }}</b></div>
          <div class="ov-item"><span class="muted small">预估总花费</span><b class="brand-text">¥{{ trip.total_cost }}</b></div>
          <div class="ov-item"><span class="muted small">预算使用率</span><b>{{ Math.round(trip.budget_usage * 100) }}%</b></div>
          <div class="ov-item"><span class="muted small">住宿</span>
            <b>{{ trip.hotel ? trip.hotel.name : '不安排' }}</b>
            <span v-if="trip.hotel" class="small muted">× {{ trip.hotel_nights }} 晚</span>
          </div>
          <div class="usage-bar"><div :style="{ width: Math.min(100, Math.round(trip.budget_usage * 100)) + '%' }"></div></div>
        </div>

        <!-- 个性化权重画像 -->
        <div v-if="trip.weight_profile?.length" class="card wp-card no-print">
          <div class="wp-head">
            <b>本次行程的权重画像</b>
            <span v-if="trip.is_personalized" class="tag orange">已个性化</span>
            <span v-else class="tag gray">模式默认</span>
          </div>
          <div class="wp-bar">
            <span v-for="p in trip.weight_profile" :key="p.key"
                  :title="`${p.label} ${p.percent}%`"
                  :style="{ width: p.percent + '%' }"></span>
          </div>
          <div class="wp-legend">
            <span v-for="p in trip.weight_profile" :key="p.key" class="wp-item">
              {{ p.icon }} {{ p.label }} {{ p.percent }}%
            </span>
          </div>
        </div>

        <!-- 游学线路横幅（G7）：一键成程与重新打开行程时都可见 -->
        <div v-if="trip.preset_route" class="study-trip-banner">
          <span class="stb-icon">🎓</span>
          <div class="stb-copy">
            <b>官方预设主题路线 · {{ trip.preset_route.title }}</b>
            <span>
              出行 {{ trip.visit_date || trip.preset_route.visit_date }} ·
              {{ trip.preset_route.day.day_type }} ·
              站点按序预占第 1 天，其余槽位按 {{ trip.mode_name }} 补全
            </span>
          </div>
          <div class="stb-side">
            <span v-if="trip.preset_route.reservation_note" class="stb-warn">⚠️ 需提前入校预约</span>
            <router-link to="/study" class="small brand-text">逐站讲解 →</router-link>
          </div>
        </div>

        <!-- 天气 + 行程地图 -->
        <div class="trip-extras no-print">
          <WeatherCard compact />
          <TMap
            :points="mapPoints" :route="true" :travel-mode="'driving'" :height="420"
            :title="`行程路线 · ${trip.days} 天（按出行方式规划）`"
            @routes="onRoutes"
          />
        </div>

        <!-- 松弛提示 -->
        <div v-if="trip.relax_log?.length" class="relax-card">
          <b>生成提示</b>
          <span v-for="(r, i) in trip.relax_log" :key="i" class="small">· {{ r.label }}</span>
        </div>

        <!-- 每日行程 -->
        <div v-for="day in trip.days_plan" :key="day.day_index" class="card day-card">
          <div class="day-head">
            <div>
              <span class="day-badge">Day {{ day.day_index }}</span>
              <b class="day-theme">{{ day.theme }}</b>
            </div>
            <div class="day-right">
              <span class="day-cost">¥{{ day.day_cost }}</span>
              <button class="btn btn-soft btn-sm no-print" :disabled="busy"
                      @click="redrop(day.day_index)">换一批</button>
            </div>
          </div>

          <div class="timeline">
            <template v-for="(it, idx) in day.items" :key="idx">
              <div v-if="legBetween(day.day_index, idx)" class="tl-transport no-print">
                <span class="tl-tr-line"></span>
                <span class="tl-tr-icon">{{ TM_ICON[legBetween(day.day_index, idx)!.mode] }}</span>
                <span class="tl-tr-txt">
                  {{ fmtDist(legBetween(day.day_index, idx)!.distance) }} · {{ fmtDur(legBetween(day.day_index, idx)!.durationSec) }}
                  <template v-if="legBetween(day.day_index, idx)!.cost"> · ¥{{ legBetween(day.day_index, idx)!.cost }}</template>
                </span>
                <span v-if="!legBetween(day.day_index, idx)!.ok" class="tl-tr-fb">估算</span>
              </div>
              <div class="tl-item">
                <div class="tl-time">{{ it.start_time }}</div>
                <div class="tl-dot"></div>
                <div class="tl-icon">{{ SLOT_ICON[it.slot] || '📍' }}</div>
                <div class="tl-body">
                  <div class="tl-name">{{ it.name }}</div>
                  <div class="small muted">
                    {{ it.slot_name }} · 约 {{ it.duration_min }} 分钟 ·
                    {{ it.cost > 0 ? '¥' + it.cost : '免费' }}
                  </div>
                </div>
                <div v-if="it.image" class="tl-thumb">
                  <img :src="it.image" :alt="it.name" loading="lazy" />
                </div>
                <button
                  v-if="it.slot !== 'lunch' && it.slot !== 'dinner' && !presetOf(it)"
                  class="btn btn-outline btn-sm no-print"
                  @click="openReplace(day.day_index, it.slot)"
                >更换</button>
                <span v-else-if="presetOf(it)" class="stb-locked no-print">🔒 游学保底站</span>
              </div>
              <!-- 游学站的逐站讲解 / 研学任务卡 / date_gate 结论 -->
              <div v-if="presetOf(it)" class="tl-study">
                <div class="tls-head">
                  <span class="tls-seq">第 {{ presetOf(it)!.seq }} 站</span>
                  <b>{{ presetOf(it)!.narration_title }}</b>
                  <span v-if="presetOf(it)!.gate_status && presetOf(it)!.gate_status !== 'open'"
                        class="tls-gate">{{ presetOf(it)!.gate_status === 'replaced' ? '已替换站点' : '日期已降级' }}</span>
                </div>
                <p class="tls-text">{{ presetOf(it)!.narration_text }}</p>
                <div v-if="presetOf(it)!.task_card?.title" class="tls-task">
                  📝 {{ presetOf(it)!.task_card!.title }}：{{ presetOf(it)!.task_card!.content }}
                </div>
                <div v-if="presetOf(it)!.photo_tip" class="tls-photo">📷 {{ presetOf(it)!.photo_tip }}</div>
                <div v-for="(n, ni) in presetOf(it)!.gate_notes || []" :key="ni" class="tls-note">↳ {{ n }}</div>
              </div>
            </template>
          </div>
        </div>

        <!-- 操作栏 -->
        <div class="action-bar no-print">
          <button class="btn btn-primary" :disabled="saving" @click="saveTrip">
            {{ saving ? '保存中…' : '保存到我的行程' }}
          </button>
          <button class="btn btn-outline" @click="printTrip">打印 / 存为 PDF</button>
          <button class="btn btn-outline" @click="exportTrip">导出行程单</button>
          <button class="btn btn-outline" @click="router.push('/compare')">对比其他模式</button>
        </div>
      </section>

      <!-- 候选弹层 -->
      <div v-if="replaceFor" class="mask no-print" @click.self="replaceFor = null">
        <div class="modal">
          <div class="section-head">
            <h2 class="section-title">更换 Day {{ replaceFor.day }} 的槽位</h2>
            <button class="btn btn-sm" @click="replaceFor = null">关闭</button>
          </div>
          <div class="small muted">从同类候选中挑选，替换后自动重排当日时间轴</div>
          <div class="divider"></div>
          <div v-if="candidateLoading" class="empty">候选加载中…</div>
          <div v-else-if="!candidates.length" class="empty">暂无可用候选</div>
          <div v-else class="cand-list">
            <div v-for="c in candidates" :key="c.id" class="cand-item" @click="applyReplace(c.id)">
              <div v-if="c.image" class="cand-thumb">
                <img :src="c.image" :alt="c.name" loading="lazy" />
              </div>
              <div>
                <b>{{ c.name }}</b>
                <div class="small muted">
                  {{ c.sub_type }} · ★ {{ c.rating?.toFixed(1) }} ·
                  {{ c.suggest_duration_min }} 分钟 ·
                  {{ c.ticket_price > 0 ? '¥' + c.ticket_price : '免费' }}
                </div>
              </div>
              <span class="brand-text">选择 →</span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.overview { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; position: relative; padding-bottom: 34px; }
.ov-item { display: flex; flex-direction: column; gap: 4px; }
.ov-item b { font-size: 19px; }
.head-links { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
.wp-card { margin-top: 16px; padding: 18px 22px; }
.wp-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.wp-bar { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: #eef1ef; }
.wp-bar span:nth-child(1) { background: #2f7d5c; }
.wp-bar span:nth-child(2) { background: #4a9c78; }
.wp-bar span:nth-child(3) { background: #e6803a; }
.wp-bar span:nth-child(4) { background: #c9a227; }
.wp-bar span:nth-child(5) { background: #6b8fce; }
.wp-bar span:nth-child(6) { background: #9b7ede; }
.wp-bar span:nth-child(7) { background: #55b8b0; }
.wp-bar span:nth-child(8) { background: #d98c9f; }
.wp-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 12px; }
.wp-item { font-size: 12px; color: #5b6b64; }
.usage-bar { position: absolute; left: 24px; right: 24px; bottom: 18px; height: 6px; background: #eef1ef; border-radius: 999px; overflow: hidden; }
.usage-bar div { height: 100%; background: var(--brand); border-radius: 999px; }
.trip-extras { display: grid; gap: 16px; margin-top: 20px; }
.study-trip-banner {
  display: flex; align-items: center; gap: 14px; margin-top: 18px;
  padding: 14px 18px; border-radius: 12px;
  background: linear-gradient(100deg, #eef7f1, #fff8ea);
  border: 1px solid #dfeae3;
}
.stb-icon { font-size: 26px; }
.stb-copy { flex: 1; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.stb-copy b { font-size: 14px; color: var(--brand-dark); }
.stb-copy span { font-size: 12px; color: #5b6b64; }
.stb-side { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; white-space: nowrap; }
.stb-warn { font-size: 12px; color: #95591a; }
.stb-locked { font-size: 11px; color: var(--brand); white-space: nowrap; }
.tl-study {
  margin: 0 0 12px 60px; padding: 12px 14px; border-radius: 10px;
  background: #f3f9f5; border-left: 3px solid var(--brand);
}
.tls-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; font-size: 13px; color: var(--ink); }
.tls-seq { font-size: 11px; font-weight: 700; color: #fff; background: var(--brand); border-radius: 999px; padding: 2px 9px; }
.tls-gate { font-size: 11px; color: #95591a; background: #fff1dc; border-radius: 999px; padding: 2px 8px; }
.tls-text { font-size: 12px; line-height: 1.75; color: #41534a; margin: 8px 0; }
.tls-task, .tls-photo, .tls-note { font-size: 12px; line-height: 1.7; margin-top: 4px; }
.tls-task { color: #245c42; }
.tls-photo { color: #55468c; }
.tls-note { color: #95591a; }
.relax-card {
  background: #fffaf0; border: 1px solid #f5e4c8; border-radius: 12px;
  padding: 12px 18px; margin-top: 16px; display: flex; gap: 14px; flex-wrap: wrap;
  color: #936a2e; font-size: 13px;
}
.day-card { margin-top: 20px; }
.day-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.day-badge { background: var(--brand); color: #fff; font-size: 12px; padding: 4px 12px; border-radius: 8px; margin-right: 10px; }
.day-theme { font-size: 17px; }
.day-right { display: flex; align-items: center; gap: 14px; }
.day-cost { color: var(--accent); font-weight: 700; }
.timeline { margin-top: 6px; }
.tl-item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.tl-item:last-child { border-bottom: none; }
.tl-time { width: 52px; color: var(--muted); font-size: 13px; }
.tl-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--brand); flex: none; }
.tl-icon { font-size: 20px; width: 30px; text-align: center; }
.tl-body { flex: 1; }
.tl-thumb { width: 72px; height: 54px; border-radius: 8px; overflow: hidden; flex: none; border: 1px solid var(--line); }
.tl-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tl-name { font-weight: 600; }
.tl-transport {
  display: flex; align-items: center; gap: 8px; padding: 2px 0 2px 60px;
  font-size: 12px; color: #5b6b64;
}
.tl-tr-line {
  width: 8px; height: 8px; border-radius: 50%; background: #b9c7c1; flex: none; margin-left: 0;
  box-shadow: 0 0 0 3px rgba(185,199,193,.25);
}
.tl-tr-icon { font-size: 14px; }
.tl-tr-txt { font-variant-numeric: tabular-nums; }
.tl-tr-fb { color: #b5742a; font-size: 11px; border: 1px solid #e7d3ad; border-radius: 5px; padding: 0 5px; }
.action-bar { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 24px; }
.cand-list { max-height: 420px; overflow: auto; }
.cand-item {
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px;
  margin-bottom: 10px; cursor: pointer; transition: all .15s ease;
}
.cand-item:hover { border-color: var(--brand); background: var(--brand-light); }
.cand-thumb { width: 64px; height: 48px; border-radius: 8px; overflow: hidden; flex: none; }
.cand-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
@media (max-width: 800px) { .overview { grid-template-columns: repeat(2, 1fr); } }
@media print {
  .action-bar, .day-head .btn { display: none !important; }
  .print-title { display: block !important; }
  .print-title h1 { font-size: 22px; margin-bottom: 4px; }
}
</style>

/* 待计划篮子 */
.wait-card { margin-top: 16px; padding: 18px 20px; }
.wait-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.wait-count { display: inline-block; min-width: 20px; padding: 1px 7px; border-radius: 999px;
  background: var(--brand, #2f7d5c); color: #fff; font-size: 12px; text-align: center; }
.wait-list { display: flex; flex-direction: column; gap: 8px; }
.wait-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  border: 1px solid #e6efe9; border-radius: 10px; background: #fbfdfb; }
.wait-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wait-foot { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.wait-day { width: 120px; }
@media print { .wait-card { display: none; } }