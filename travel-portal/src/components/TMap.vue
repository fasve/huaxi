<script setup lang="ts">
/** 腾讯地图组件（GL JS API）：POI 点位 + 按天分组连线 + 用户实时位置 + 路线规划。
 *
 * 与旧的高德版保持同一套 props / emit，页面无需改逻辑：
 *  - 底图为腾讯 GL 矢量底图（GCJ-02，与小程序 <map> 同一坐标口径）；
 *  - route=true 时调用腾讯 WebService direction/v1（JSONP），返回真实道路折线与分步提示；
 *  - 骑行腾讯路线服务不提供，自动降级为直线 + 速度估算，并标注「估算」；
 *  - 未配置 key 时只提示配置，不加载外部脚本、不白屏。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  escapeHtml, fetchDirection, loadQQMap, qqmapConfigured,
  TRAVEL_MODES, type TravelMode,
} from './qqmap'
import type { MapPoint, RouteLegSummary } from './amap'
import { distanceMeters, HUAXI_CENTER, useLocation } from '../location'

const props = withDefaults(defineProps<{
  points: MapPoint[]
  height?: number
  polyline?: boolean
  title?: string
  showMe?: boolean
  route?: boolean
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

const CENTER: [number, number] = HUAXI_CENTER
const GROUP_COLORS = ['#2f7d5c', '#e6803a', '#4a7fd0', '#a05dc0', '#c05050', '#4aa39a', '#b08a3e']

const container = ref<HTMLDivElement | null>(null)
const state = ref<'unset' | 'loading' | 'ready' | 'error'>(qqmapConfigured ? 'loading' : 'unset')
const errorMsg = ref('')

let map: any = null
let TMap: any = null
let markerLayer: any = null
let lineLayer: any = null
let circleLayer: any = null
let meLayer: any = null
let infoWindow: any = null

// ---- 路线状态 ----
const travelMode = ref<TravelMode>(props.travelMode)
const routeLoading = ref(false)
const routeReady = ref(false)
const openLegs = ref<Record<string, boolean>>({})

interface Leg {
  dayIndex: number
  fromSeq: number
  toSeq: number
  fromName: string
  toName: string
  mode: TravelMode
  distance: number
  durationSec: number
  ok: boolean
  steps: { instruction: string; distance: number; durationSec: number }[]
  path: Array<[number, number]>
}
const legs = ref<Leg[]>([])

const locLabel = computed(() => location.value?.label || (locating.value ? '正在获取实时位置…' : '定位中…'))
const hasMe = computed(() => !!location.value && location.value.source !== 'default')
const showRouteToggle = computed(() => props.route && state.value === 'ready')

const summary = computed(() => {
  const dist = legs.value.reduce((s, l) => s + l.distance, 0)
  const dur = legs.value.reduce((s, l) => s + l.durationSec, 0)
  return { dist, dur, count: legs.value.length, fallback: legs.value.filter((l) => !l.ok).length }
})

const groupedLegs = computed(() => {
  const m = new Map<number, Leg[]>()
  legs.value.forEach((l) => {
    if (!m.has(l.dayIndex)) m.set(l.dayIndex, [])
    m.get(l.dayIndex)!.push(l)
  })
  return [...m.entries()].sort((a, b) => a[0] - b[0])
})

const SPEED: Record<TravelMode, number> = { driving: 30, transit: 18, walking: 4.8, riding: 15 }

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
function legKey(day: number, from: number, to: number): string {
  return `${day}:${from}:${to}`
}
function toggleLeg(day: number, from: number, to: number) {
  const k = legKey(day, from, to)
  openLegs.value[k] = !openLegs.value[k]
}

/** 分组：同名 group 的点连成一条线；无 group 时按序连。 */
function groups(): Map<string, MapPoint[]> {
  const m = new Map<string, MapPoint[]>()
  props.points.forEach((p, i) => {
    const k = p.group || (props.polyline ? '全部' : String(i))
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(p)
  })
  return m
}

function pinSvg(color: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="34" viewBox="0 0 26 34">
<path d="M13 33C13 33 25 20.5 25 12.5C25 5.6 19.6 0 13 0C6.4 0 1 5.6 1 12.5C1 20.5 13 33 13 33Z"
 fill="${color}" stroke="#ffffff" stroke-width="2"/><circle cx="13" cy="12.5" r="4.6" fill="#ffffff"/></svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

function latLng(p: MapPoint): any {
  return new TMap.LatLng(Number(p.lat), Number(p.lng))
}

function clearLayers() {
  for (const layer of [markerLayer, lineLayer, circleLayer, meLayer]) {
    if (layer) { try { layer.setMap(null) } catch { /* ignore */ } }
  }
  markerLayer = lineLayer = circleLayer = meLayer = null
}

function drawPois() {
  if (!map || !TMap) return
  const pts = props.points || []
  if (!pts.length) return

  const styles: Record<string, any> = {}
  let gi = 0
  groups().forEach((_list, g) => {
    const color = GROUP_COLORS[gi % GROUP_COLORS.length]
    gi += 1
    styles['m_' + g] = new TMap.MarkerStyle({ width: 26, height: 34, anchor: { x: 13, y: 34 }, src: pinSvg(color) })
  })

  const geometries = pts.map((p) => ({
    id: String(p.id),
    styleId: 'm_' + (p.group || String(props.points.indexOf(p))),
    position: latLng(p),
    properties: { title: p.name, address: p.address || '', label: p.label || '' },
  }))
  markerLayer = new TMap.MultiMarker({ map, styles, geometries })
  markerLayer.on('click', (evt: any) => {
    const geo = evt.geometry as any
    const pr = geo?.properties || {}
    if (!infoWindow) {
      infoWindow = new TMap.InfoWindow({ map, offset: { x: 0, y: -36 }, enableCustom: false })
    }
    infoWindow.setContent(
      `<div style="padding:2px 4px;font-size:13px;line-height:1.6"><b>${escapeHtml(pr.title || '')}</b>`
      + (pr.address ? `<br/><span style="color:#7c8a84">${escapeHtml(pr.address)}</span>` : '')
      + (pr.label ? `<br/><span style="color:#2f7d5c">${escapeHtml(pr.label)}</span>` : '')
      + '</div>',
    )
    infoWindow.setPosition(geo.position)
    infoWindow.setVisible(true)
  })
}

function drawLines(paths: Array<{ id: string; styleId: string; path: Array<[number, number]> }>) {
  if (!map || !TMap) return
  if (lineLayer) { try { lineLayer.setMap(null) } catch { /* ignore */ } lineLayer = null }
  if (!paths.length) return
  const styles: Record<string, any> = {}
  paths.forEach((p, idx) => {
    if (styles[p.styleId]) return
    styles[p.styleId] = new TMap.PolylineStyle({
      color: p.styleId === 'route' ? '#2f7d5c' : GROUP_COLORS[idx % GROUP_COLORS.length],
      width: 5, borderWidth: 1, borderColor: '#ffffff', lineCap: 'round',
    })
  })
  const geometries = paths.map((p) => ({
    id: p.id,
    styleId: p.styleId,
    paths: p.path.map(([lng, lat]) => new TMap.LatLng(lat, lng)),
  }))
  lineLayer = new TMap.MultiPolyline({ map, styles, geometries })
}

function drawMe() {
  if (!map || !TMap) return
  const loc = location.value
  if (meLayer) { try { meLayer.setMap(null) } catch { /* ignore */ } meLayer = null }
  if (circleLayer) { try { circleLayer.setMap(null) } catch { /* ignore */ } circleLayer = null }
  if (!props.showMe || !loc || loc.source === 'default') return
  const center = new TMap.LatLng(Number(loc.lat), Number(loc.lng))
  circleLayer = new TMap.MultiCircle({
    map,
    styles: { acc: new TMap.CircleStyle({ color: 'rgba(42,127,255,0.12)', showBorder: true, borderColor: '#2a7fff', borderWidth: 1 }) },
    geometries: [{ id: 'acc', styleId: 'acc', center, radius: Math.max(60, Number(loc.accuracy) || 80) }],
  })
  meLayer = new TMap.MultiMarker({
    map,
    styles: { me: new TMap.MarkerStyle({ width: 18, height: 18, anchor: { x: 9, y: 9 }, src: dotSvg() }) },
    geometries: [{ id: 'me', styleId: 'me', position: center }],
  })
}

function dotSvg(): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18"><circle cx="9" cy="9" r="7" fill="#2a7fff" stroke="#ffffff" stroke-width="3"/></svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

function fitPoints(extra?: any) {
  if (!map || !TMap || !props.points.length) return
  const lats = props.points.map((p) => Number(p.lat))
  const lngs = props.points.map((p) => Number(p.lng))
  const sw = new TMap.LatLng(Math.min(...lats), Math.min(...lngs))
  const ne = new TMap.LatLng(Math.max(...lats), Math.max(...lngs))
  try {
    map.fitBounds(new TMap.LatLngBounds(sw, ne), { padding: 60 })
  } catch {
    try {
      map.setCenter(new TMap.LatLng((Math.min(...lats) + Math.max(...lats)) / 2, (Math.min(...lngs) + Math.max(...lngs)) / 2))
      map.setZoom(13)
    } catch { /* ignore */ }
  }
  void extra
}

function fitPois() { fitPoints() }

function focusMe() {
  const loc = location.value
  if (!map || !TMap || !loc) return
  try {
    map.setCenter(new TMap.LatLng(Number(loc.lat), Number(loc.lng)))
    map.setZoom(15)
  } catch { /* ignore */ }
}

/** 直线连线（route 关闭或路线未就绪时） */
function drawStraightLines() {
  const paths: Array<{ id: string; styleId: string; path: Array<[number, number]> }> = []
  let i = 0
  groups().forEach((list) => {
    if (list.length < 2) return
    paths.push({
      id: 'l' + i,
      styleId: 'g' + (i % GROUP_COLORS.length),
      path: list.map((p) => [Number(p.lng), Number(p.lat)] as [number, number]),
    })
    i++
  })
  drawLines(paths)
}

/** 按出行方式规划每一段（顺序请求，避免并发打满配额） */
async function planRoutes() {
  if (!props.route || state.value !== 'ready') return
  const token = ++routeToken
  routeLoading.value = true
  routeReady.value = false
  const out: Leg[] = []
  const paths: Array<{ id: string; styleId: string; path: Array<[number, number]> }> = []
  const byDay = new Map<number, MapPoint[]>()
  props.points.forEach((p) => {
    const d = Number((p as any).dayIndex ?? 1)
    if (!byDay.has(d)) byDay.set(d, [])
    byDay.get(d)!.push(p)
  })

  let n = 0
  for (const [day, list] of [...byDay.entries()].sort((a, b) => a[0] - b[0])) {
    for (let i = 0; i < list.length - 1; i++) {
      const a = list[i]
      const b = list[i + 1]
      const from: [number, number] = [Number(a.lng), Number(a.lat)]
      const to: [number, number] = [Number(b.lng), Number(b.lat)]
      const straight = distanceMeters(Number(a.lng), Number(a.lat), Number(b.lng), Number(b.lat))
      const r = await fetchDirection(from, to, travelMode.value)
      if (token !== routeToken) return
      const ok = r.ok && r.path.length > 1
      const distance = ok ? r.distance : straight
      const durationSec = ok ? r.durationSec : (straight / 1000 / SPEED[travelMode.value]) * 3600
      out.push({
        dayIndex: day,
        fromSeq: i + 1,
        toSeq: i + 2,
        fromName: a.name,
        toName: b.name,
        mode: travelMode.value,
        distance,
        durationSec,
        ok,
        steps: r.steps,
        path: ok ? r.path : [from, to],
      })
      paths.push({ id: 'r' + n++, styleId: 'route', path: ok ? r.path : [from, to] })
    }
  }
  if (token !== routeToken) return
  legs.value = out
  drawLines(paths)
  routeLoading.value = false
  routeReady.value = true
  emit('routes', out.map((l) => ({
    dayIndex: l.dayIndex,
    fromSeq: l.fromSeq,
    toSeq: l.toSeq,
    fromName: l.fromName,
    toName: l.toName,
    mode: l.mode,
    distance: l.distance,
    durationSec: l.durationSec,
    ok: l.ok,
  })) as RouteLegSummary[])
}

let routeToken = 0

function setMode(mode: TravelMode) {
  if (travelMode.value === mode) return
  travelMode.value = mode
  planRoutes()
}

async function initMap() {
  if (!qqmapConfigured) { state.value = 'unset'; return }
  state.value = 'loading'
  try {
    TMap = await loadQQMap()
    if (!container.value) return
    map = new TMap.Map(container.value, {
      center: new TMap.LatLng(CENTER[1], CENTER[0]),
      zoom: 12,
      pitch: 0,
      rotation: 0,
      viewMode: '2D',
      baseMap: { type: 'vector', features: ['base', 'point'] },
    })
    state.value = 'ready'
    drawPois()
    drawMe()
    if (props.route) planRoutes()
    else drawStraightLines()
    fitPoints()
  } catch (e: any) {
    state.value = 'error'
    errorMsg.value = e?.message || '腾讯地图初始化失败'
  }
}

onMounted(async () => {
  if (props.showMe) { try { await ensure() } catch { /* 定位失败不阻塞地图 */ } }
  await initMap()
})

onBeforeUnmount(() => {
  clearLayers()
  try { map?.destroy() } catch { /* ignore */ }
  map = null
})

watch(() => props.points, () => {
  if (state.value !== 'ready') return
  drawPois()
  if (props.route) planRoutes()
  else { drawStraightLines(); fitPoints() }
}, { deep: true })

watch(travelMode, () => { if (props.route) planRoutes() })

watch(() => location.value, () => { if (state.value === 'ready') drawMe() }, { deep: true })
</script>

<template>
  <div class="amap-card card no-print">
    <div class="amap-head">
      <b>🗺️ {{ title }}</b>
      <div class="amap-tools">
        <span class="small muted">{{ points.length }} 个点位 · 腾讯地图</span>
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
        在 <code>travel-portal/.env.local</code> 填入腾讯位置服务的 JS API key：
        <code>VITE_QQMAP_JS_KEY=你的key</code>，重启 <code>npm run dev</code> 后生效。
      </p>
      <p class="small muted">
        申请入口：腾讯位置服务控制台 → 应用管理 → 添加 Key（启用「Web端 (JS API GL)」）；
        并在 key 设置里把 <code>localhost</code> 与正式域名加入域名白名单。
      </p>
    </div>

    <div v-else class="amap-canvas" :style="{ height: height + 'px' }">
      <div ref="container" class="amap-inner"></div>
      <div v-if="state === 'loading'" class="amap-cover small muted">地图加载中…</div>
      <div v-else-if="state === 'error'" class="amap-cover err small">
        <b>{{ errorMsg }}</b>
        <span class="small muted">常见原因：key 未启用 JS API GL、域名白名单未包含 localhost、或配额未分配</span>
      </div>
      <div v-else-if="route && routeLoading" class="amap-cover small muted">正在规划路线…</div>
      <div v-else-if="!hasMe" class="amap-hint small">未获取到实时位置，地图以花溪区为中心 · 点「重新定位」重试</div>
    </div>

    <div v-if="route && routeReady" class="route-panel">
      <div class="rp-summary">
        <b>{{ modeIcon(travelMode) }} {{ modeLabel(travelMode) }}</b>
        <span>全程 {{ fmtDist(summary.dist) }} · 约 {{ fmtDur(summary.dur) }} · {{ summary.count }} 段</span>
        <span v-if="summary.fallback" class="rp-fallback">⚠ {{ summary.fallback }} 段为估算</span>
      </div>
      <div class="rp-scroll">
        <div v-for="[day, list] in groupedLegs" :key="day" class="rp-day">
          <div class="rp-day-head">Day {{ day }}</div>
          <div v-for="leg in list" :key="leg.fromSeq + '-' + leg.toSeq" class="rp-leg">
            <div class="rp-leg-head" @click="toggleLeg(leg.dayIndex, leg.fromSeq, leg.toSeq)">
              <span class="rp-arrow">{{ modeIcon(leg.mode) }}</span>
              <span class="rp-route">{{ leg.fromName }} → {{ leg.toName }}</span>
              <span class="rp-meta">{{ fmtDist(leg.distance) }} · {{ fmtDur(leg.durationSec) }}</span>
              <span class="rp-caret">{{ openLegs[legKey(leg.dayIndex, leg.fromSeq, leg.toSeq)] ? '▾' : '▸' }}</span>
            </div>
            <div v-if="openLegs[legKey(leg.dayIndex, leg.fromSeq, leg.toSeq)]" class="rp-steps">
              <div v-for="(s, i) in leg.steps" :key="i" class="rp-step">
                <span class="rp-step-no">{{ i + 1 }}</span>
                <span class="rp-step-txt">
                  {{ s.instruction }}
                  <span class="small muted"> · {{ fmtDist(s.distance) }}<template v-if="s.durationSec"> · {{ fmtDur(s.durationSec) }}</template></span>
                </span>
              </div>
              <div v-if="!leg.ok" class="rp-note">未获取到实时路线（腾讯路线服务对该方式不可用或超限），以上为直线距离估算，实际以地图为准。</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="amap-foot small muted">
      底图服务：腾讯地图 JS API GL · GCJ-02 坐标系；蓝色圆点为你的实时位置，仅存于本机会话，不上传或入库；演示资源坐标为花溪区近似值
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
  display: flex; align-items: center; gap: 8px; padding: 9px 14px; cursor: pointer; font-size: 13px;
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
