<script setup lang="ts">
/** 天气卡片（精致版）：实时实况 + 未来 15 天预报。
 *  - 数据源：Open-Meteo 免密钥公开 API（服务端代理），一次请求同时返回实况与 15 天逐日预报；
 *  - 按用户实时所在坐标查询（浏览器精定位 → WGS-84），不传坐标时看花溪区；
 *  - 图标为自绘 SVG（WeatherIcon），配色按天气类型动态切换（weatherKind）；
 *  - 昼夜以 Open-Meteo 返回的 is_day 为准，比本地时间判断更准确。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api, type ForecastDay, type WeatherInfo } from '../api'
import { useLocation } from '../location'
import WeatherIcon from './WeatherIcon.vue'
import { themeOf } from './weatherKind'

const props = withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const { location, locating, sourceText, distanceToHuaxi, ensure, refresh, useHuaxi } = useLocation()

const data = ref<WeatherInfo | null>(null)
const loading = ref(true)
let seq = 0

const live = computed(() => data.value?.live || null)

/** 是否夜间：优先用数据源的 is_day，其次按本地时间兜底 */
const isNight = computed(() => {
  if (typeof live.value?.is_day === 'boolean') return !live.value.is_day
  const h = new Date().getHours()
  return h < 6 || h >= 19
})

/** 实况配色主题（晴/雨/雪…各自一套渐变） */
const theme = computed(() => themeOf(live.value?.weather || '', isNight.value))

/** 省份 + 城市去重拼接（贵阳市这类省级市直接返回一次） */
const placeTitle = computed(() => {
  const p = (data.value?.province || location.value?.province || '').trim()
  const c = (data.value?.city || location.value?.city || '').trim()
  if (!p) return c || '当前位置'
  if (!c) return p
  return p.includes(c) || c.includes(p) ? c : `${p}${c}`
})
const locLabel = computed(() =>
  location.value?.label || (locating.value ? '正在获取实时位置…' : '定位中…'),
)

/** 15 天列表：直接用后端返回的逐日预报 */
const strip = computed<ForecastDay[]>(() => data.value?.casts || [])

/** 行程页紧凑模式只展示前 6 天，避免卡片过高 */
const visibleDays = computed(() =>
  props.compact ? strip.value.slice(0, 6) : strip.value,
)

/** 今日白天 / 夜间 / 降水概率概览 */
const today = computed(() => {
  const t = strip.value[0]
  if (!t) return null
  return {
    daytemp: t.daytemp,
    nighttemp: t.nighttemp,
    dayweather: t.dayweather,
    nightweather: t.nightweather,
    precip: t.precip,
  }
})

/** 整体温度区间，用于每日温度条在 15 天中的相对位置 */
const tempRange = computed(() => {
  const highs = strip.value.map((d) => Number(d.daytemp)).filter((n) => Number.isFinite(n))
  const lows = strip.value.map((d) => Number(d.nighttemp)).filter((n) => Number.isFinite(n))
  if (!highs.length || !lows.length) return null
  const min = Math.min(...lows)
  const max = Math.max(...highs)
  return { min, max, span: Math.max(max - min, 1) }
})

function barStyle(d: ForecastDay) {
  const r = tempRange.value
  if (!r) return {}
  const hi = d.daytemp === '' ? NaN : Number(d.daytemp)
  const lo = d.nighttemp === '' ? NaN : Number(d.nighttemp)
  if (!Number.isFinite(hi) || !Number.isFinite(lo)) return { display: 'none' }
  const bottom = ((lo - r.min) / r.span) * 100
  const height = Math.max(((hi - lo) / r.span) * 100, 8)
  return { bottom: `${Math.min(bottom, 92)}%`, height: `${height}%` }
}

/** 拉取实况 + 15 天预报（同一接口，一次请求） */
async function loadWeather() {
  const cur = ++seq
  loading.value = true
  try {
    const p = location.value
    const d = await api.getWeather({ lng: p?.wgsLng, lat: p?.wgsLat, days: 15 })
    if (cur !== seq) return
    data.value = d
  } catch {
    if (cur === seq) {
      data.value = { configured: false, message: '无法连接后端天气服务，请确认 travel-api 已启动' }
    }
  } finally {
    if (cur === seq) loading.value = false
  }
}

// 位置变化即刷新（天气按坐标查询，坐标变了结果就变）
watch(() => [location.value?.wgsLng, location.value?.wgsLat], () => {
  if (location.value) loadWeather()
}, { immediate: true })

onMounted(() => { ensure() })

const unavailable = computed(() =>
  !data.value || !data.value.configured || !!data.value.error,
)
const hint = computed(() => data.value?.error || data.value?.message || '天气数据暂不可用')

function fmtTime(s?: string): string {
  if (!s) return ''
  // Open-Meteo 返回 ISO 本地时间，如 2026-11-10T11:30
  return s.replace('T', ' ').slice(0, 16)
}
function md(date: string): string {
  return date.length >= 10 ? date.slice(5) : date
}
function dayLabel(d: ForecastDay, i: number): string {
  if (i === 0) return '今天'
  if (i === 1) return '明天'
  if (i === 2) return '后天'
  return d.week || ''
}

/** 横向滚动：鼠标滚轮纵向滚动映射为横向滑动 */
function onWheel(e: WheelEvent) {
  const el = e.currentTarget as HTMLElement
  if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
  const before = el.scrollLeft
  el.scrollLeft += e.deltaY
  if (el.scrollLeft !== before) e.preventDefault()
}
</script>

<template>
  <div class="card weather-card" :class="{ compact }">
    <!-- 顶部渐变主视觉 -->
    <div class="wx-hero" :style="{ background: theme.hero }">
      <div class="wx-deco wx-deco-a"></div>
      <div class="wx-deco wx-deco-b"></div>

      <div class="wx-top">
        <div class="wx-loc">
          <span class="wx-pin">📍</span>
          <div class="wx-loc-text">
            <b>{{ placeTitle }}</b>
            <span>{{ sourceText }}<template v-if="locating"> · 定位中</template><template v-else-if="location?.source === 'default'"> · 未获取到实时位置</template></span>
          </div>
        </div>
        <div class="wx-actions">
          <button type="button" class="wx-btn" :disabled="locating" @click="refresh">重新定位</button>
          <button type="button" class="wx-btn ghost" @click="useHuaxi">切回花溪</button>
        </div>
      </div>

      <div class="wx-main">
        <div class="wx-left">
          <div class="wx-temp">
            <template v-if="live?.temperature">{{ live.temperature }}</template>
            <template v-else>--</template>
            <span class="wx-unit">°</span>
          </div>
          <div class="wx-desc">
            <span class="wx-desc-main">{{ live?.weather || '暂无实况' }}</span>
            <span class="wx-desc-sub">
              <template v-if="live?.feels_like">体感 {{ live.feels_like }}° · </template>
              实时实况 · 更新 {{ fmtTime(data?.reporttime) || '—' }}
            </span>
          </div>
        </div>
        <div class="wx-icon">
          <WeatherIcon :weather="live?.weather || ''" :night="isNight" :size="compact ? 64 : 96" />
        </div>
        <div v-if="!compact && today" class="wx-today">
          <div class="wx-today-row">
            <span class="wx-today-tag">白天</span>
            <b>{{ today.daytemp }}°</b>
            <span class="small">{{ today.dayweather }}</span>
          </div>
          <div class="wx-today-row">
            <span class="wx-today-tag night">夜间</span>
            <b>{{ today.nighttemp }}°</b>
            <span class="small">{{ today.nightweather }}</span>
          </div>
          <div v-if="today.precip != null" class="wx-today-row">
            <span class="wx-today-tag rain">降水</span>
            <b>{{ today.precip }}%</b>
            <span class="small">概率</span>
          </div>
        </div>
      </div>

      <div v-if="live" class="wx-metrics">
        <div class="wx-chip">💧 湿度 <b>{{ live.humidity || '--' }}%</b></div>
        <div class="wx-chip">🌬️ {{ live.winddirection || '--' }}风 <b>{{ live.windpower || '--' }} 级</b></div>
        <div v-if="live.cloud_cover" class="wx-chip">☁️ 云量 <b>{{ live.cloud_cover }}%</b></div>
        <div class="wx-chip">📍 距花溪 <b>{{ distanceToHuaxi }} km</b></div>
      </div>
    </div>

    <!-- 主体：实况异常提示 / 15 天预报 -->
    <div class="wx-body">
      <div v-if="loading" class="wx-loading muted small">天气加载中…</div>

      <div v-else-if="unavailable" class="wx-unset">
        <div class="wx-unset-icon">🛰️</div>
        <div>
          <b>天气服务暂不可用</b>
          <p class="small muted">{{ hint }}</p>
          <p v-if="!compact" class="small muted">
            天气数据来自 Open-Meteo 公开 API（免密钥），若无法连接请确认 travel-api 已启动且本机可访问外网。
          </p>
        </div>
      </div>

      <template v-else>
        <div class="wx-fc-head">
          <b>{{ compact ? '未来 6 天' : '未来 15 天' }}</b>
          <span class="small muted">
            <template v-if="loading">预报加载中…</template>
            <template v-else-if="compact">{{ data?.source || '逐日预报' }} · 完整 15 天见首页</template>
            <template v-else>{{ data?.source || '逐日预报' }} · 横向滑动查看</template>
          </span>
        </div>

        <div class="wx-days" @wheel="onWheel">
          <div v-for="(d, i) in visibleDays" :key="d.date" class="wx-day">
            <div class="d-week">{{ dayLabel(d, i) }}</div>
            <div class="d-date small muted">{{ md(d.date) }}</div>
            <WeatherIcon class="d-icon" :weather="d.dayweather" :size="compact ? 30 : 38" />
            <div class="d-text small">{{ d.dayweather }}</div>
            <div v-if="d.precip != null && d.precip >= 20" class="d-precip">
              <span class="d-precip-dot"></span>{{ d.precip }}%
            </div>
            <div class="d-temp">
              <b>{{ d.daytemp }}°</b>
              <span>{{ d.nighttemp }}°</span>
            </div>
            <div class="d-bar">
              <i :style="barStyle(d)"></i>
            </div>
          </div>

          <div v-if="!visibleDays.length" class="wx-days-empty small muted">
            {{ loading ? '15 天预报加载中…' : '暂无预报数据' }}
          </div>
        </div>
      </template>

      <div v-if="!compact" class="wx-foot small muted">
        数据来源：Open-Meteo 公开天气 API（免密钥，实况 + 15 天预报同一数据源） · 天气数据仅供参考，出行前请留意实时预警
      </div>
    </div>
  </div>
</template>

<style scoped>
.weather-card { padding: 0; overflow: hidden; }

/* ---------- 主视觉 ---------- */
.wx-hero {
  position: relative; padding: 20px 24px 18px; color: #fff; overflow: hidden;
}
.wx-deco { position: absolute; border-radius: 50%; background: rgba(255,255,255,.10); pointer-events: none; }
.wx-deco-a { width: 190px; height: 190px; right: -60px; top: -80px; }
.wx-deco-b { width: 120px; height: 120px; right: 70px; bottom: -70px; background: rgba(255,255,255,.07); }

.wx-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.wx-loc { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.wx-pin { font-size: 15px; opacity: .9; }
.wx-loc-text { display: flex; flex-direction: column; line-height: 1.4; }
.wx-loc-text b { font-size: 13.5px; font-weight: 700; letter-spacing: .3px; }
.wx-loc-text span { font-size: 11.5px; opacity: .8; }
.wx-actions { display: inline-flex; gap: 6px; }
.wx-btn {
  border: 1px solid rgba(255,255,255,.45); background: rgba(255,255,255,.16); color: #fff;
  border-radius: 7px; padding: 4px 11px; font-size: 12px; cursor: pointer; white-space: nowrap;
  backdrop-filter: blur(4px);
}
.wx-btn:hover { background: rgba(255,255,255,.28); }
.wx-btn:disabled { opacity: .6; cursor: default; }
.wx-btn.ghost { background: transparent; }

.wx-main { display: flex; align-items: center; gap: 26px; margin: 14px 0 6px; }
.wx-left { min-width: 0; }
.wx-city { font-size: 13px; opacity: .88; letter-spacing: .4px; }
.wx-temp {
  font-size: 62px; font-weight: 800; line-height: 1.02; letter-spacing: -2px;
  text-shadow: 0 2px 10px rgba(0,0,0,.12);
}
.wx-unit { font-size: 30px; font-weight: 600; vertical-align: super; margin-left: 2px; opacity: .9; }
.wx-desc { display: flex; flex-direction: column; margin-top: 6px; }
.wx-desc-main { font-size: 16px; font-weight: 600; }
.wx-desc-sub { font-size: 12px; opacity: .82; margin-top: 2px; }
.wx-icon { filter: drop-shadow(0 6px 14px rgba(0,0,0,.18)); margin-left: -6px; }

/* 今日白天 / 夜间 / 降水概览 */
.wx-today {
  display: flex; flex-direction: column; gap: 7px; flex: none;
  padding: 12px 16px; border-radius: 12px; margin-left: auto;
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.18);
  backdrop-filter: blur(4px); min-width: 172px;
}
.wx-today-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.wx-today-row b { font-size: 15px; font-weight: 700; }
.wx-today-row .small { opacity: .82; }
.wx-today-tag {
  font-size: 11px; padding: 1px 7px; border-radius: 6px;
  background: rgba(255,255,255,.24); white-space: nowrap;
}
.wx-today-tag.night { background: rgba(0,0,0,.18); }
.wx-today-tag.rain { background: rgba(120,190,255,.32); }

.wx-metrics { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.wx-chip {
  background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.18);
  border-radius: 999px; padding: 4px 11px; font-size: 12px; color: #fff;
  backdrop-filter: blur(4px); white-space: nowrap;
}
.wx-chip b { font-weight: 700; }

/* ---------- 主体 ---------- */
.wx-body { padding: 16px 24px 18px; }
.wx-loading { padding: 18px 0; text-align: center; }
.wx-unset { display: flex; gap: 14px; align-items: flex-start; }
.wx-unset-icon { font-size: 28px; line-height: 1; }
.wx-unset p { margin: 4px 0 0; line-height: 1.7; }
.wx-unset code { background: #f1f4f2; padding: 1px 6px; border-radius: 5px; font-size: 12px; }

.wx-fc-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 10px; margin-bottom: 12px; flex-wrap: wrap;
}
.wx-fc-head b { font-size: 14.5px; }

.wx-days {
  display: flex; gap: 8px; overflow-x: auto; padding: 4px 2px 10px;
  scroll-snap-type: x proximity; scrollbar-width: thin;
}
.wx-days::-webkit-scrollbar { height: 6px; }
.wx-days::-webkit-scrollbar-thumb { background: #d8e2dc; border-radius: 3px; }
.wx-days::-webkit-scrollbar-track { background: #f4f7f5; border-radius: 3px; }

.wx-day {
  flex: 0 0 76px; scroll-snap-align: start;
  background: #f8faf9; border: 1px solid #eef3f0; border-radius: 12px;
  padding: 10px 6px 12px; text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  transition: transform .15s ease, box-shadow .15s ease;
}
.wx-day:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(47,125,92,.12); }
.d-week { font-size: 12.5px; font-weight: 700; color: var(--ink); }
.d-date { font-size: 10.5px; }
.d-icon { margin: 2px 0; }
.d-text {
  color: var(--muted); max-width: 100%; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.d-precip {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 10.5px; color: #3f86c9; background: #eaf3fb;
  border-radius: 999px; padding: 1px 6px; line-height: 1.5;
}
.d-precip-dot { width: 4px; height: 4px; border-radius: 50%; background: #3f86c9; }
.d-temp { display: flex; flex-direction: column; align-items: center; line-height: 1.25; }
.d-temp b { font-size: 14px; font-weight: 700; color: var(--brand-dark); }
.d-temp span { font-size: 12px; color: #8b9a94; }

/* 温度条：在 15 天整体区间内的相对位置 */
.d-bar {
  position: relative; width: 6px; height: 44px; border-radius: 3px;
  background: linear-gradient(180deg, #eef2f7 0%, #f7f1ea 100%); margin-top: 2px;
}
.d-bar i {
  position: absolute; left: 0; right: 0; border-radius: 3px;
  background: linear-gradient(180deg, #f4a261 0%, #e6803a 55%, #d9603a 100%);
}

.wx-days-empty { padding: 24px 0; text-align: center; width: 100%; }
.wx-foot { margin-top: 10px; line-height: 1.6; }

/* ---------- 紧凑模式（行程详情页） ---------- */
.compact .wx-hero { padding: 14px 18px 14px; }
.compact .wx-temp { font-size: 40px; }
.compact .wx-unit { font-size: 20px; }
.compact .wx-desc-main { font-size: 14px; }
.compact .wx-city { font-size: 12px; }
.compact .wx-metrics { margin-top: 10px; }
.compact .wx-body { padding: 12px 18px 14px; }
.compact .wx-day { flex: 0 0 66px; padding: 8px 4px 10px; }
.compact .wx-foot { display: none; }

@media (max-width: 640px) {
  .wx-temp { font-size: 48px; }
  .wx-body { padding: 14px 16px 16px; }
  .wx-hero { padding: 16px 16px 14px; }
  .wx-main { flex-wrap: wrap; gap: 14px; }
  .wx-today { width: 100%; min-width: 0; }
}
@media print {
  .weather-card { box-shadow: none; border: 1px solid #ddd; }
  .wx-hero { border-radius: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .wx-btn, .wx-actions { display: none; }
}
</style>
