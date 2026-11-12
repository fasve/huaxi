<script setup lang="ts">
/** 高德地图组件：POI 点位 + 按天分组 + 用户实时位置 + 路线规划（精确到出行方式）。
 *  - 只使用高德 JS API 2.0 官方底图，不叠加任何第三方/境外瓦片；
 *  - 坐标统一 GCJ-02；浏览器原生定位的 WGS-84 已在 location.ts 转换；
 *  - 我的位置默认纳入视野（仅限距花溪 60km 内）；人在外地时可一键「定位到我」；
 *  - route 模式下调用高德路径规划插件，按「驾车/公交/步行/骑行」计算点位间的真实道路路径，
 *    并给出每段的转向/换乘分步提示；高德不可达时自动降级为直线距离估算；
 *  - 未配置 key 时显示配置指引，不加载外部脚本、不白屏。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  amapConfigured, escapeHtml, loadAMap, loadRoutePlugins, TRAVEL_MODES,
  type MapPoint, type RouteLeg, type RouteLegSummary, type TravelMode,
} from './amap'
import { distanceMeters, HUAXI_CENTER, useLocation } from '../location'

const props = withDefaults(defineProps<{
  points: MapPoint[]
  height?: number
  polyline?: boolean
  title?: string
  showMe?: boolean
  /** 路线规划模式：用真实道路路径连接点位，并按出行方式计算距离/耗时/转向提示 */
  route?: boolean
  /** 初始出行方式 */
  travelMode?: TravelMode
}>(), {
  height: 360,
  polyline: false,
  title: '花溪地图',
  showMe: true,
  route: false,
  travelMode: 'driving',
})

const emit = defineEmits<{ (e: 'routes', legs: RouteLegSummary[]): void }>()

const { location, locating, sourceText, distanceToHuaxi, ensure, refresh, useHuaxi } = useLocation()

// 花溪区中心（近似，GCJ-02）
const CENTER: [number, number] = HUAXI_CENTER
const GROUP_COLORS = ['#2f7d5c', '#e6803a', '#4a7fd0', '#a05dc0', '#c05050', '#4aa39a', '#b08a3e']

const container = ref<HTMLDivElement | null>(null)
const state = ref<'unset' | 'loading' | 'ready' | 'error'>(amapConfigured ? 'loading' : 'unset')
const errorMsg = ref('')
let map: any = null
let AMap: any = null
let overlays: any[] = []
let poiMarkers: any[] = []
let myMarker: any = null
let accuracyCircle: any = null
let routeOverlays: any[] = []

// ---- 路线规划状态 ----
const travelMode = ref<TravelMode>(props.travelMode)
const routeLegs = ref<RouteLeg[]>([])
const routeLoading = ref(false)
const routeReady = ref(false)
const openLegs = ref<Record<string, boolean>>({})
const dayColors = new Map<number, string>()
const legCache = new Map<string, RouteLeg>()
const lastValid = ref<MapPoint[]>([])
let routeToken = 0

const locLabel = computed(() => location.value?.label || (locating.value ? '正在获取实时位置…' : '定位中…'))
const hasMe = computed(() => !!location.value && location.value.source !== 'default')
const showRouteToggle = computed(() => props.route && state.value === 'ready')

const routeSummary = computed(() => {
  const legs = routeLegs.value
  const dist = legs.reduce((s, l) => s + l.distance, 0)
  const dur = legs.reduce((s, l) => s + l.durationSec, 0)
  const fb = legs.filter((l) => !l.ok).length
  return { dist, dur, count: legs.length, mode: travelMode.value, fallback: fb }
})

const groupedLegs = computed(() => {
  const m = new Map<number, RouteLeg[]>()
  routeLegs.value.forEach((l) => {
    if (!m.has(l.dayIndex)) m.set(l.dayIndex, [])
    m.get(l.dayIndex)!.push(l)
  })
  return [...m.entries()].sort((a, b) => a[0] - b[0])
})

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
function modeIcon(mode: TravelMode): string {
  return TRAVEL_MODES.find((m) => m.key === mode)?.icon || '➡'
}
function modeLabel(mode: TravelMode): string {
  return TRAVEL_MODES.find((m) => m.key === mode)?.label || '路线'
}
const SPEED: Record<TravelMode, number> = { driving: 30, transit: 18, walking: 4.8, riding: 15 } // km/h 估算
function stripTags(s: string): string {
  return String(s).replace(/<[^>]+>/g, '').replace(/&nbsp;/g, '').replace(/\s+/g, ' ').trim()
}
function toPt(p: any): [number, number] {
  return [Number(p?.lng ?? p?.[0]), Number(p?.lat ?? p?.[1])]
}

function removeMyLocation() {
  if (!map) return
  for (const o of [myMarker, accuracyCircle]) {
    if (!o) continue
    try { map.remove(o) } catch { /* overlay 可能已被销毁 */ }
  }
  myMarker = null
  accuracyCircle = null
}

function renderMyLocation() {
  if (!map || !AMap) return
  removeMyLocation()
  const p = location.value
  if (!props.showMe || !hasMe.value || !p) return

  if (p.accuracy === 'precise' && p.accuracyMeters > 20 && p.accuracyMeters < 3000) {
    try {
      accuracyCircle = new AMap.Circle({
        center: [p.lng, p.lat],
        radius: Math.min(p.accuracyMeters, 1000),
        fillColor: '#2a7fff', fillOpacity: 0.08,
        strokeColor: '#2a7fff', strokeOpacity: 0.3, strokeWeight: 1,
        map,
      })
    } catch { accuracyCircle = null }
  }

  const dot = `<div style="width:24px;height:24px;border-radius:50%;background:rgba(42,127,255,.18);display:flex;align-items:center;justify-content:center">
    <div style="width:12px;height:12px;border-radius:50%;background:#2a7fff;border:2px solid #fff;box-sizing:border-box;box-shadow:0 1px 5px rgba(0,0,0,.35)"></div>
  </div>`
  myMarker = new AMap.Marker({
    position: [p.lng, p.lat],
    content: dot,
    offset: new AMap.Pixel(-12, -12),
    title: '我的实时位置',
    zIndex: 200,
    map,
  })
  const info = new AMap.InfoWindow({
    content: `<div style="padding:8px 12px;font:13px/1.7 'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2d27;min-width:150px">
      <b style="font-size:14px;color:#2a7fff">我的实时位置</b>
      <div style="color:#7c8a84;margin-top:2px">${escapeHtml(p.label)}</div>
      <div style="color:#7c8a84">${escapeHtml(sourceText.value)} · 距花溪约 ${distanceToHuaxi.value} km</div>
    </div>`,
    offset: new AMap.Pixel(0, -14),
  })
  myMarker.on('click', () => info.open(map, myMarker.getPosition()))
}

function clearRouteOverlays() {
  if (!map) return
  for (const o of routeOverlays) {
    try { map.remove(o) } catch { /* ignore */ }
  }
  routeOverlays = []
}

function clearOverlays() {
  if (!map) return
  removeMyLocation()
  for (const o of overlays) {
    try { map.remove(o) } catch { /* overlay 可能已被销毁 */ }
  }
  overlays = []
  poiMarkers = []
  clearRouteOverlays()
}

function fitPois() {
  if (!map) return
  if (poiMarkers.length) {
    try { map.setFitView(poiMarkers, false, [50, 50, 50, 50], 14) }
    catch { map.setZoomAndCenter(12, CENTER) }
  } else {
    map.setZoomAndCenter(12, CENTER)
  }
}

// ---------- 路线规划：单段计算 ----------

function fallbackFields(mode: TravelMode, from: MapPoint, to: MapPoint) {
  const d = distanceMeters(from.lng, from.lat, to.lng, to.lat)
  const dur = Math.round((d / 1000) / SPEED[mode] * 3600)
  const label = modeLabel(mode)
  return {
    distance: Math.round(d),
    durationSec: dur,
    steps: [{
      instruction: `未获取到实时路线，按「${label}」直线距离约 ${fmtDist(d)}、约 ${fmtDur(dur)} 估算`,
      distance: Math.round(d),
      durationSec: dur,
    }],
    path: [[from.lng, from.lat], [to.lng, to.lat]] as Array<[number, number]>,
  }
}

function parseTransit(plan: any) {
  const steps: RouteLeg['steps'] = []
  const path: Array<[number, number]> = []
  for (const seg of plan.segments || []) {
    if (seg.walking && !seg.transit) {
      for (const s of seg.walking.steps || []) {
        steps.push({
          instruction: stripTags(s.instruction || '步行'),
          distance: s.distance || 0,
          durationSec: s.time || 0,
          path: (s.path || []).map(toPt),
        })
        ;(s.path || []).forEach((p: any) => path.push(toPt(p)))
      }
    } else if (seg.transit) {
      const t = seg.transit
      const busline = t.bus?.buslines?.[0]
      const lineName = t.line?.name || ''
      const blName = busline?.name || ''
      const name = blName || lineName || '公交/地铁'
      const dep = t.departure_stop?.name || ''
      const arr = t.arrival_stop?.name || ''
      let instr = `乘坐 ${name}`
      if (lineName && lineName !== name) instr += `（${lineName}）`
      if (dep) instr += `，从「${dep}」上车`
      if (arr) instr += `，到「${arr}」下车`
      const segPath = (busline?.path || t.path || []).map(toPt)
      steps.push({ instruction: instr, distance: t.distance || 0, durationSec: t.time || 0, path: segPath })
      segPath.forEach((p: [number, number]) => path.push(p))
    }
  }
  return { steps, path }
}

function parseRoute(mode: TravelMode, result: any): Omit<RouteLeg, 'dayIndex' | 'fromSeq' | 'toSeq' | 'fromId' | 'toId' | 'fromName' | 'toName' | 'mode' | 'ok'> | null {
  if (mode === 'transit') {
    const plan = result?.plans?.[0]
    if (!plan) return null
    const { steps, path } = parseTransit(plan)
    return {
      distance: plan.distance || 0,
      durationSec: plan.time || 0,
      cost: plan.cost,
      steps,
      path,
    }
  }
  const route = result?.routes?.[0]
  if (!route) return null
  const steps: RouteLeg['steps'] = (route.steps || []).map((s: any) => ({
    instruction: stripTags(s.instruction || ''),
    distance: s.distance || 0,
    durationSec: s.time || 0,
    path: (s.path || []).map(toPt),
  }))
  const path = (route.steps || []).flatMap((s: any) => (s.path || []).map(toPt))
  return { distance: route.distance || 0, durationSec: route.time || 0, steps, path }
}

async function planOne(mode: TravelMode, from: MapPoint, to: MapPoint): Promise<RouteLeg> {
  const cacheKey = `${mode}:${from.id}:${to.id}`
  const cached = legCache.get(cacheKey)
  if (cached) return { ...cached }
  const base: RouteLeg = {
    dayIndex: 0, fromSeq: 0, toSeq: 0, fromId: from.id, toId: to.id, fromName: from.name, toName: to.name,
    mode, distance: 0, durationSec: 0, steps: [], path: [], ok: false,
  }
  try {
    const A = await loadRoutePlugins()
    const res = await new Promise<any>((resolve, reject) => {
      const opts: any = {}
      if (mode === 'transit') opts.city = '贵阳市'
      const ctorKey = mode === 'transit' ? 'Transfer'
        : mode === 'driving' ? 'Driving'
        : mode === 'walking' ? 'Walking' : 'Riding'
      const svc = new A[ctorKey](opts)
      svc.search([from.lng, from.lat], [to.lng, to.lat], (status: string, result: any) => {
        if (status === 'complete' && result) resolve(result)
        else reject(new Error(String(result?.info || status)))
      })
    })
    const parsed = parseRoute(mode, res)
    if (!parsed) {
      const leg = { ...base, ...fallbackFields(mode, from, to) }
      legCache.set(cacheKey, leg)
      return leg
    }
    const leg = { ...base, ...parsed, ok: true }
    legCache.set(cacheKey, leg)
    return leg
  } catch {
    const leg = { ...base, ...fallbackFields(mode, from, to) }
    legCache.set(cacheKey, leg)
    return leg
  }
}

async function runPool<T>(items: T[], size: number, fn: (t: T) => Promise<void>) {
  let i = 0
  const workers = Array.from({ length: Math.min(size, Math.max(1, items.length)) }, async () => {
    while (i < items.length) {
      const idx = i++
      await fn(items[idx])
    }
  })
  await Promise.all(workers)
}

function drawLeg(leg: RouteLeg) {
  if (!map || !AMap) return
  const color = dayColors.get(leg.dayIndex) || '#2f7d5c'
  if (leg.path.length >= 2) {
    const line = new AMap.Polyline({
      path: leg.path,
      strokeColor: color,
      strokeWeight: 6,
      strokeOpacity: 0.92,
      lineJoin: 'round',
      isOutline: true,
      outlineColor: '#ffffff',
      zIndex: 50,
      map,
    })
    routeOverlays.push(line)
  }
  let pos: [number, number] = leg.path.length ? leg.path[Math.floor(leg.path.length / 2)] : [0, 0]
  const pill = `<div style="display:flex;align-items:center;gap:4px;background:${color};color:#fff;font:600 11px/1 'PingFang SC','Microsoft YaHei',sans-serif;padding:3px 8px;border-radius:999px;box-shadow:0 1px 4px rgba(0,0,0,.25);white-space:nowrap;border:1.5px solid #fff">${modeIcon(leg.mode)} ${fmtDist(leg.distance)}·${fmtDur(leg.durationSec)}</div>`
  const badge = new AMap.Marker({
    position: pos,
    content: pill,
    offset: new AMap.Pixel(-26, -12),
    zIndex: 60,
    map,
  })
  routeOverlays.push(badge)
}

async function computeRoutes(valid: MapPoint[]) {
  if (!map || !AMap) return
  const token = ++routeToken
  clearRouteOverlays()
  routeReady.value = false
  routeLegs.value = []
  openLegs.value = {}

  // 按 group 分组并保持顺序（group 形如 "Day N"）
  const groups = new Map<string, MapPoint[]>()
  valid.forEach((p) => {
    const g = p.group || '全部'
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(p)
  })
  const groupsArr: { dayIndex: number; list: MapPoint[] }[] = []
  groups.forEach((list, g) => {
    const dayIdx = parseInt(String(g).replace(/\D/g, ''), 10) || (groupsArr.length + 1)
    groupsArr.push({ dayIndex: dayIdx, list })
  })
  // 按天分配颜色
  dayColors.clear()
  const sortedDays = [...new Set(groupsArr.map((x) => x.dayIndex))].sort((a, b) => a - b)
  sortedDays.forEach((d, i) => dayColors.set(d, GROUP_COLORS[i % GROUP_COLORS.length]))

  const tasks: { from: MapPoint; to: MapPoint; dayIndex: number; fromSeq: number; toSeq: number }[] = []
  groupsArr.forEach(({ dayIndex, list }) => {
    for (let i = 0; i < list.length - 1; i++) {
      tasks.push({ from: list[i], to: list[i + 1], dayIndex, fromSeq: i, toSeq: i + 1 })
    }
  })
  if (!tasks.length) { routeReady.value = true; return }

  routeLoading.value = true
  const legs: RouteLeg[] = []
  await runPool(tasks, 5, async (t) => {
    const leg = await planOne(travelMode.value, t.from, t.to)
    leg.dayIndex = t.dayIndex
    leg.fromSeq = t.fromSeq
    leg.toSeq = t.toSeq
    if (token !== routeToken) return
    legs.push(leg)
    drawLeg(leg)
  })
  if (token !== routeToken) return
  legs.sort((a, b) => a.dayIndex - b.dayIndex || a.fromSeq - b.fromSeq)
  routeLegs.value = legs
  routeLoading.value = false
  routeReady.value = true
  // 视野包络路线
  try { map.setFitView([...poiMarkers, ...routeOverlays], false, [50, 50, 50, 50], 14) } catch { /* keep */ }
  // 通知父组件（用于时间轴交通提示）
  emit('routes', legs.map((l) => ({
    dayIndex: l.dayIndex, fromSeq: l.fromSeq, toSeq: l.toSeq,
    fromName: l.fromName, toName: l.toName, mode: l.mode,
    distance: l.distance, durationSec: l.durationSec, cost: l.cost, ok: l.ok,
  })))
}

function setMode(m: TravelMode) {
  if (travelMode.value === m) return
  travelMode.value = m
  routeLegs.value = []
  if (state.value === 'ready' && props.route) void computeRoutes(lastValid.value)
}

function toggleLeg(day: number, from: number, to: number) {
  const k = `${day}:${from}:${to}`
  openLegs.value = { ...openLegs.value, [k]: !openLegs.value[k] }
}

// ---------- 主渲染 ----------

function render() {
  if (!map || !AMap || !container.value) return
  clearOverlays()
  const valid = props.points.filter(
    (p) => Number.isFinite(p.lng) && Number.isFinite(p.lat) && p.lng > 0 && p.lat > 0,
  )
  lastValid.value = valid

  valid.forEach((p) => {
    const marker = new AMap.Marker({
      position: [p.lng, p.lat],
      title: p.name,
      map,
      ...(p.label ? { label: { content: p.label, direction: 'top' } } : {}),
    })
    const detail = [p.category, p.address]
      .filter((v): v is string => Boolean(v))
      .map(escapeHtml)
      .join(' · ')
    const info = new AMap.InfoWindow({
      content: `<div style="padding:8px 12px;font:13px/1.7 'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2d27;min-width:140px">
        <b style="font-size:14px">${escapeHtml(p.name)}</b>
        ${detail ? `<div style="color:#7c8a84;margin-top:2px">${detail}</div>` : ''}
      </div>`,
      offset: new AMap.Pixel(0, -28),
    })
    marker.on('click', () => info.open(map, marker.getPosition()))
    overlays.push(marker)
    poiMarkers.push(marker)
  })

  if (props.route && valid.length > 1) {
    void computeRoutes(valid)
  } else if (props.polyline && valid.length > 1) {
    const groups = new Map<string, MapPoint[]>()
    valid.forEach((p) => {
      const g = p.group || '全部'
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(p)
    })
    let i = 0
    groups.forEach((list) => {
      if (list.length < 2) return
      overlays.push(new AMap.Polyline({
        path: list.map((p) => [p.lng, p.lat]),
        strokeColor: GROUP_COLORS[i++ % GROUP_COLORS.length],
        strokeWeight: 4,
        strokeOpacity: 0.85,
        lineJoin: 'round',
        map,
      }))
    })
  }

  renderMyLocation()
  fitPois()

  const p = location.value
  if (p && hasMe.value && myMarker
      && distanceMeters(p.lng, p.lat, CENTER[0], CENTER[1]) < 60000) {
    try { map.setFitView([...poiMarkers, myMarker], false, [50, 50, 50, 50], 14) } catch { /* keep */ }
  }
}

function focusMe() {
  const p = location.value
  if (!map || !p) { refresh(); return }
  map.setZoomAndCenter(14, [p.lng, p.lat])
  if (myMarker) {
    try { myMarker.setAnimation('AMAP_ANIMATION_DROP') } catch { /* ignore */ }
  }
}

onMounted(async () => {
  ensure() // 定位与地图加载并行，不阻塞底图渲染
  if (!amapConfigured) return
  try {
    AMap = await loadAMap()
    if (!container.value) return
    map = new AMap.Map(container.value, {
      zoom: 12,
      center: CENTER,
      viewMode: '2D',
      resizeEnable: true,
    })
    state.value = 'ready'
    render()
  } catch (e) {
    state.value = 'error'
    errorMsg.value = (e as Error).message
  }
})

watch(() => props.points, () => {
  if (state.value === 'ready') render()
}, { deep: true })

watch(() => [location.value?.lng, location.value?.lat, location.value?.source], () => {
  if (state.value === 'ready') renderMyLocation()
})

onBeforeUnmount(() => {
  clearOverlays()
  if (map) {
    try { map.destroy() } catch { /* ignore */ }
    map = null
  }
})
</script>

<template>
  <div class="amap-card card no-print">
    <div class="amap-head">
      <b>🗺️ {{ title }}</b>
      <div class="amap-tools">
        <span class="small muted">{{ points.length }} 个点位 · 高德地图</span>
        <!-- 出行方式切换（路线模式下显示） -->
        <div v-if="showRouteToggle" class="mode-switch">
          <button
            v-for="m in TRAVEL_MODES" :key="m.key" type="button"
            class="mode-btn" :class="{ on: travelMode === m.key }"
            :title="m.hint" @click="setMode(m.key)"
          >{{ m.icon }} {{ m.label }}</button>
        </div>
        <button type="button" class="map-btn" @click="fitPois">看景点</button>
        <button type="button" class="map-btn" @click="focusMe">定位到我</button>
      </div>
    </div>

    <!-- 实时位置状态条 -->
    <div class="me-bar">
      <span class="loc-dot" :class="location?.source"></span>
      <b>我的位置：{{ locLabel }}</b>
      <span class="small muted">{{ sourceText }} · 距花溪约 {{ distanceToHuaxi }} km</span>
      <span class="me-btns">
        <button type="button" class="map-btn" :disabled="locating" @click="refresh">重新定位</button>
        <button type="button" class="map-btn ghost" @click="useHuaxi">切回花溪</button>
      </span>
    </div>

    <div v-if="state === 'unset'" class="amap-unset" :style="{ height: height + 'px' }">
      <div class="unset-emoji">🧭</div>
      <b>地图尚未启用</b>
      <p class="small muted">
        在 <code>travel-portal/.env.local</code> 填入高德「Web端 (JS API)」key 与对应安全密钥，
        重启 <code>npm run dev</code> 后生效。
      </p>
      <p class="small muted">
        申请入口：高德开放平台 → 应用管理 → 我的 Key（服务平台选「Web端 (JS API)」）；
        同时为该 key 配置 Referer 域名白名单。
      </p>
    </div>

    <div v-else class="amap-canvas" :style="{ height: height + 'px' }">
      <div ref="container" class="amap-inner"></div>
      <div v-if="state === 'loading'" class="amap-cover small muted">地图加载中…</div>
      <div v-else-if="state === 'error'" class="amap-cover err small">
        <b>{{ errorMsg }}</b>
        <span class="small muted">常见原因：key 类型不是「Web端 (JS API)」、缺少安全密钥、Referer 白名单未包含 localhost</span>
      </div>
      <div v-else-if="route && routeLoading" class="amap-cover small muted">正在规划路线…</div>
      <div v-else-if="!hasMe" class="amap-hint small">未获取到实时位置，地图以花溪区为中心 · 点「重新定位」重试</div>
    </div>

    <!-- 路线详情面板（路线模式 + 已就绪） -->
    <div v-if="route && routeReady" class="route-panel">
      <div class="rp-summary">
        <b>{{ modeIcon(travelMode) }} {{ modeLabel(travelMode) }}</b>
        <span>全程 {{ fmtDist(routeSummary.dist) }} · 约 {{ fmtDur(routeSummary.dur) }} · {{ routeSummary.count }} 段</span>
        <span v-if="routeSummary.fallback" class="rp-fallback">⚠ {{ routeSummary.fallback }} 段为估算</span>
      </div>
      <div class="rp-scroll">
        <div v-for="[day, legs] in groupedLegs" :key="day" class="rp-day">
          <div class="rp-day-head">Day {{ day }}</div>
          <div v-for="leg in legs" :key="leg.fromSeq + '-' + leg.toSeq" class="rp-leg">
            <div class="rp-leg-head" @click="toggleLeg(leg.dayIndex, leg.fromSeq, leg.toSeq)">
              <span class="rp-arrow">{{ modeIcon(leg.mode) }}</span>
              <span class="rp-route">{{ leg.fromName }} → {{ leg.toName }}</span>
              <span class="rp-meta">
                {{ fmtDist(leg.distance) }} · {{ fmtDur(leg.durationSec) }}
                <template v-if="leg.cost"> · ¥{{ leg.cost }}</template>
              </span>
              <span class="rp-caret">{{ openLegs[leg.dayIndex + ':' + leg.fromSeq + ':' + leg.toSeq] ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openLegs[leg.dayIndex + ':' + leg.fromSeq + ':' + leg.toSeq]" class="rp-steps">
              <div v-for="(s, i) in leg.steps" :key="i" class="rp-step">
                <span class="rp-step-no">{{ i + 1 }}</span>
                <span class="rp-step-txt">
                  {{ s.instruction }}
                  <span class="small muted"> · {{ fmtDist(s.distance) }}<template v-if="s.durationSec"> · {{ fmtDur(s.durationSec) }}</template></span>
                </span>
              </div>
              <div v-if="!leg.ok" class="rp-note">未获取到实时路线，以上为直线距离估算，实际以地图为准。</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="amap-foot small muted">
      底图服务：高德地图 JS API 2.0 · GCJ-02 坐标系；蓝色圆点为你的实时位置，仅存于本机会话，不上传或入库；演示资源坐标为花溪区近似值
    </div>
  </div>
</template>

<style scoped>
.amap-card { padding: 18px; }
.amap-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 10px; flex-wrap: wrap;
}
.amap-head b { font-size: 16px; }
.amap-tools { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.map-btn {
  border: 1px solid #c9dcd2; background: #fff; color: var(--brand-dark, #245e46);
  border-radius: 7px; padding: 4px 10px; font-size: 12px; cursor: pointer; white-space: nowrap;
}
.map-btn:hover { border-color: var(--brand, #2f7d5c); background: #f5f8f6; }
.map-btn:disabled { opacity: .55; cursor: default; }
.map-btn.ghost { color: var(--muted, #7c8a84); }

.mode-switch { display: inline-flex; gap: 4px; padding: 3px; background: #eef3f0; border-radius: 9px; }
.mode-btn {
  border: none; background: transparent; color: #5b6b64; cursor: pointer;
  font-size: 12px; padding: 4px 9px; border-radius: 7px; white-space: nowrap;
}
.mode-btn:hover { background: #e0eae5; }
.mode-btn.on { background: var(--brand, #2f7d5c); color: #fff; font-weight: 700; }

.me-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 12px; margin-bottom: 12px;
  background: #f5f8f6; border: 1px solid #e3ece7; border-radius: 10px;
}
.me-bar b { font-size: 13px; font-weight: 600; }
.me-btns { display: inline-flex; gap: 6px; margin-left: auto; }
.loc-dot {
  width: 9px; height: 9px; border-radius: 50%; background: #9aa9a2; flex: none;
  box-shadow: 0 0 0 3px rgba(154,169,162,.18);
}
.loc-dot.browser { background: #2a7fff; box-shadow: 0 0 0 3px rgba(42,127,255,.18); }
.loc-dot.ip { background: #e6a03a; box-shadow: 0 0 0 3px rgba(230,160,58,.18); }

.amap-canvas, .amap-unset { position: relative; border-radius: 12px; overflow: hidden; }
.amap-inner { width: 100%; height: 100%; }
.amap-hint {
  position: absolute; left: 12px; bottom: 12px; z-index: 2;
  background: rgba(255,255,255,.92); padding: 5px 10px; border-radius: 7px; color: #7c8a84;
}
.amap-unset {
  background: linear-gradient(135deg, #f3f7f5, #e8f0ec);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: 8px; padding: 24px; border: 1px dashed #c9dcd2;
}
.unset-emoji { font-size: 40px; }
.amap-unset p { margin: 0; max-width: 520px; line-height: 1.7; }
.amap-unset code { background: #fff; padding: 1px 6px; border-radius: 5px; font-size: 12px; }
.amap-cover {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 8px;
  background: rgba(246, 248, 247, .96); text-align: center; padding: 20px;
}
.amap-cover.err b { color: #b74133; }
.amap-foot { margin-top: 12px; line-height: 1.6; }

/* 路线详情面板 */
.route-panel { margin-top: 14px; border: 1px solid #e3ece7; border-radius: 12px; overflow: hidden; }
.rp-summary {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 14px; background: #f5f8f6; font-size: 13px; color: #3d4a44;
  border-bottom: 1px solid #e3ece7;
}
.rp-summary b { font-size: 14px; }
.rp-fallback { color: #b5742a; font-size: 12px; }
.rp-scroll { max-height: 280px; overflow: auto; }
.rp-day { padding: 6px 0; }
.rp-day-head {
  font-size: 12px; font-weight: 700; color: var(--brand-dark, #245e46);
  padding: 8px 14px 4px; background: #fbfdfc;
}
.rp-leg { border-top: 1px solid #eef2f0; }
.rp-leg-head {
  display: flex; align-items: center; gap: 8px; padding: 9px 14px; cursor: pointer;
  font-size: 13px;
}
.rp-leg-head:hover { background: #f7faf8; }
.rp-arrow { flex: none; }
.rp-route { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #1f2d27; }
.rp-meta { color: #5b6b64; white-space: nowrap; font-variant-numeric: tabular-nums; }
.rp-caret { color: #9aa9a2; flex: none; }
.rp-steps { padding: 4px 14px 10px 30px; background: #fcfdfc; }
.rp-step { display: flex; gap: 8px; padding: 4px 0; font-size: 12.5px; line-height: 1.6; color: #3d4a44; }
.rp-step-no {
  flex: none; width: 18px; height: 18px; border-radius: 50%; background: #e8f0ec; color: var(--brand-dark, #245e46);
  font-size: 11px; text-align: center; line-height: 18px; margin-top: 1px;
}
.rp-note { margin-top: 6px; font-size: 12px; color: #b5742a; }

@media (max-width: 700px) {
  .amap-head { flex-direction: column; align-items: flex-start; }
  .rp-meta { font-size: 12px; }
}
</style>
