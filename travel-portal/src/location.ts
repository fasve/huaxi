/** 游客端实时位置（全局单例，所有页面/组件共享一份状态）。
 *
 * 链路：浏览器精定位 → 服务端逆地理拿 adcode/地名
 *      → 拒绝授权或服务不可用时 IP 城市级定位 → 仍失败则回退花溪区默认位置。
 *
 * 坐标系（两套并存，按用途区分）：
 * - WGS-84：浏览器原生定位坐标系，**天气查询（Open-Meteo）必须用这套**，否则偏移约 500 米；
 * - GCJ-02：高德底图坐标系，**地图渲染与逆地理编码用这套**。
 * 因此同时保存 wgsLng/wgsLat 与 lng/lat（GCJ-02），由各调用方按需取用。
 *
 * 隐私与合规：
 * - 精确坐标只存在当前浏览器会话的 sessionStorage，不入库、不关联账号、不上报日志服务端；
 * - 传给后端的坐标放在 POST 请求体，不出现在 URL / 访问日志里，后端只做一次逆地理后即丢弃；
 * - 底图与坐标统一使用高德 GCJ-02 坐标系，未叠加任何第三方或境外瓦片；
 * - 位置可随时「切回花溪」，定位跟随可随时停止，不静默持续采集。
 */
import { computed, ref } from 'vue'
import { api, type LocationInfo } from './api'

export type LocationSource = 'browser' | 'ip' | 'default'

export interface UserLocation {
  /** GCJ-02 经度（高德底图 / 逆地理编码用） */
  lng: number
  /** GCJ-02 纬度 */
  lat: number
  /** WGS-84 经度（天气查询 Open-Meteo 用） */
  wgsLng: number
  /** WGS-84 纬度 */
  wgsLat: number
  source: LocationSource
  accuracy: 'precise' | 'city' | 'none'
  accuracyMeters: number
  adcode: string
  province: string
  city: string
  district: string
  label: string
  updatedAt: number
}

export const HUAXI_CENTER: [number, number] = [106.6700, 26.4200]      // GCJ-02
export const HUAXI_ADCODE = '520111'

const HUAXI: UserLocation = {
  lng: HUAXI_CENTER[0],
  lat: HUAXI_CENTER[1],
  wgsLng: 106.6619,
  wgsLat: 26.4138,
  source: 'default',
  accuracy: 'none',
  accuracyMeters: 0,
  adcode: HUAXI_ADCODE,
  province: '贵州',
  city: '贵阳市',
  district: '花溪区',
  label: '花溪区（默认位置）',
  updatedAt: 0,
}

const STORE_KEY = 'travel_portal_location'
const MAX_AGE = 30 * 60 * 1000
const MOVE_THRESHOLD = 100 // 米，位移超过才更新，避免定位抖动反复请求

// ---------- WGS-84 → GCJ-02（浏览器原生定位是 WGS-84，高德底图/服务是 GCJ-02） ----------
const PI = Math.PI
const AXIS = 6378245.0
const EE = 0.00669342162296594323

function outOfChina(lng: number, lat: number): boolean {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271
}
function transformLat(x: number, y: number): number {
  let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3
  ret += (20 * Math.sin(y * PI) + 40 * Math.sin(y / 3 * PI)) * 2 / 3
  ret += (160 * Math.sin(y / 12 * PI) + 320 * Math.sin(y * PI / 30)) * 2 / 3
  return ret
}
function transformLng(x: number, y: number): number {
  let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3
  ret += (20 * Math.sin(x * PI) + 40 * Math.sin(x / 3 * PI)) * 2 / 3
  ret += (150 * Math.sin(x / 12 * PI) + 300 * Math.sin(x / 30 * PI)) * 2 / 3
  return ret
}
export function wgs84ToGcj02(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat] // 境外不做偏移
  let dLat = transformLat(lng - 105.0, lat - 35.0)
  let dLng = transformLng(lng - 105.0, lat - 35.0)
  const radLat = lat / 180.0 * PI
  let magic = Math.sin(radLat)
  magic = 1 - EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180.0) / ((AXIS * (1 - EE)) / (magic * sqrtMagic) * PI)
  dLng = (dLng * 180.0) / (AXIS / sqrtMagic * Math.cos(radLat) * PI)
  return [Number((lng + dLng).toFixed(6)), Number((lat + dLat).toFixed(6))]
}

/** GCJ-02 → WGS-84 反向换算（迭代逼近，误差 < 1m）。
 *  用于把高德 IP 定位返回的 GCJ-02 坐标还原成 Open-Meteo 需要的 WGS-84。 */
export function gcj02ToWgs84(lng: number, lat: number): [number, number] {
  if (outOfChina(lng, lat)) return [lng, lat]
  let wLng = lng
  let wLat = lat
  for (let i = 0; i < 6; i++) {
    const [gLng, gLat] = wgs84ToGcj02(wLng, wLat)
    const dx = gLng - lng
    const dy = gLat - lat
    if (Math.abs(dx) < 1e-7 && Math.abs(dy) < 1e-7) break
    wLng -= dx
    wLat -= dy
  }
  return [Number(wLng.toFixed(6)), Number(wLat.toFixed(6))]
}

/** 球面距离（米），用于「我离花溪有多远」与位移阈值判断 */
export function distanceMeters(aLng: number, aLat: number, bLng: number, bLat: number): number {
  const rad = (d: number) => d * PI / 180
  const dLat = rad(bLat - aLat)
  const dLng = rad(bLng - aLng)
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(rad(aLat)) * Math.cos(rad(bLat)) * Math.sin(dLng / 2) ** 2
  return 2 * 6371000 * Math.asin(Math.sqrt(h))
}

// ---------- 本机会话缓存 ----------
function readCache(): UserLocation | null {
  try {
    const raw = sessionStorage.getItem(STORE_KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as UserLocation
    if (!Number.isFinite(v.lng) || !Number.isFinite(v.lat)) return null
    if (Date.now() - (v.updatedAt || 0) > MAX_AGE) return null
    // 旧版本缓存没有 WGS-84 坐标（天气查询需要），此处补齐
    if (!Number.isFinite(v.wgsLng) || !Number.isFinite(v.wgsLat)) {
      const [wLng, wLat] = gcj02ToWgs84(v.lng, v.lat)
      v.wgsLng = wLng
      v.wgsLat = wLat
    }
    return v
  } catch {
    return null
  }
}
function writeCache(v: UserLocation) {
  try {
    // 只存必要的城市级信息与坐标，不存 formatted_address 详细门牌
    sessionStorage.setItem(STORE_KEY, JSON.stringify(v))
  } catch { /* 隐私模式下 sessionStorage 可能不可写，忽略 */ }
}

// ---------- 全局状态 ----------
const location = ref<UserLocation | null>(readCache())
const locating = ref(false)
const error = ref('')
let detectPromise: Promise<void> | null = null
let watchId: number | null = null
let manualMode = false
let generation = 0 // 用户中途「切回花溪 / 重新定位」时，丢弃仍在飞行的旧定位结果

const sourceText = computed(() => ({
  browser: '浏览器精定位',
  ip: 'IP 城市级定位',
  default: '默认位置',
}[location.value?.source || 'default']))

const distanceToHuaxi = computed(() => {
  const p = location.value
  if (!p) return 0
  return Math.round(distanceMeters(p.lng, p.lat, HUAXI_CENTER[0], HUAXI_CENTER[1]) / 1000)
})

function build(
  gcjLng: number, gcjLat: number,
  wgsLng: number, wgsLat: number,
  source: LocationSource,
  accuracy: UserLocation['accuracy'],
  accuracyMeters: number,
  info: LocationInfo | null,
): UserLocation {
  const ok = !!info?.configured
  const district = ok ? (info?.district || '') : ''
  const city = ok ? (info?.city || '') : ''
  let label = HUAXI.label
  if (source === 'browser') {
    label = ok ? (district || city || '我的位置') : '我的位置'
  } else if (source === 'ip') {
    label = ok ? (city || info?.province || '当前城市') : HUAXI.label
  }
  return {
    lng: gcjLng, lat: gcjLat,
    wgsLng, wgsLat,
    source, accuracy, accuracyMeters,
    adcode: ok && info?.adcode ? info.adcode : HUAXI_ADCODE,
    province: ok ? (info?.province || '') : '',
    city,
    district,
    label,
    updatedAt: Date.now(),
  }
}

function apply(v: UserLocation) {
  location.value = v
  writeCache(v)
}

function browserPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('当前浏览器不支持定位'))
      return
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      timeout: 8000,
      maximumAge: 5 * 60 * 1000,
    })
  })
}

async function resolveRemote(lng: number, lat: number): Promise<LocationInfo | null> {
  try {
    return await api.resolveLocation({ lng, lat })
  } catch {
    return null
  }
}

function stopWatch() {
  if (watchId !== null && navigator.geolocation) {
    navigator.geolocation.clearWatch(watchId)
    watchId = null
  }
}

/** 位置变化时持续跟随；只在明显位移后更新，避免无意义的请求与界面抖动 */
function startWatch() {
  if (watchId !== null || !navigator.geolocation || manualMode) return
  watchId = navigator.geolocation.watchPosition(
    async (pos) => {
      const wLng = pos.coords.longitude
      const wLat = pos.coords.latitude
      const [lng, lat] = wgs84ToGcj02(wLng, wLat)
      const prev = location.value
      if (prev && distanceMeters(prev.lng, prev.lat, lng, lat) < MOVE_THRESHOLD) return
      if (manualMode || prev?.source !== 'browser') return
      const info = await resolveRemote(lng, lat)
      apply(build(lng, lat, wLng, wLat, 'browser', 'precise', Math.round(pos.coords.accuracy || 0), info))
    },
    () => { /* 跟随失败时保留最后一次成功的位置，不打扰用户 */ },
    { enableHighAccuracy: false, maximumAge: 60 * 1000, timeout: 15000 },
  )
}

async function detect(force = false): Promise<void> {
  if (!force && location.value && Date.now() - location.value.updatedAt < MAX_AGE) {
    startWatch()
    return
  }
  if (detectPromise) return detectPromise
  locating.value = true
  error.value = ''
  const gen = generation
  const cancelled = () => gen !== generation
  const task = (async () => {
    // 1) 浏览器精定位（用户可拒绝；仅在 localhost / HTTPS 下可用）
    try {
      const pos = await browserPosition()
      if (cancelled()) return
      const wLng = pos.coords.longitude
      const wLat = pos.coords.latitude
      const [lng, lat] = wgs84ToGcj02(wLng, wLat)
      const info = await resolveRemote(lng, lat)
      if (cancelled()) return
      apply(build(lng, lat, wLng, wLat, 'browser', 'precise', Math.round(pos.coords.accuracy || 0), info))
      manualMode = false
      startWatch()
      return
    } catch (e) {
      if (!cancelled()) error.value = (e as Error)?.message || '浏览器定位不可用'
    }

    // 2) IP 城市级定位（服务端代理，不需要浏览器授权）
    //    高德返回的是 GCJ-02 坐标，需反算成 WGS-84 才能用于 Open-Meteo 天气查询
    try {
      const info = await api.resolveLocation({})
      if (cancelled()) return
      if (info.configured && Number.isFinite(info.lng) && Number.isFinite(info.lat)) {
        const [wLng, wLat] = gcj02ToWgs84(info.lng!, info.lat!)
        apply(build(info.lng!, info.lat!, wLng, wLat, 'ip', 'city', 0, info))
        error.value = '浏览器定位未授权，已改用 IP 城市级定位'
        manualMode = false
        return
      }
      error.value = info.message || 'IP 定位不可用，已回退花溪区'
    } catch {
      if (!cancelled()) error.value = '定位服务不可用，已回退花溪区'
    }

    // 3) 保证所有下游功能仍可用
    if (cancelled()) return
    apply({ ...HUAXI, updatedAt: Date.now() })
  })().finally(() => {
    if (detectPromise === task) {
      locating.value = false
      detectPromise = null
    }
  })
  detectPromise = task
  return task
}

/** 首次使用时触发；多个组件同时调用只会定位一次 */
function ensure(): Promise<void> {
  return detect(false)
}

/** 用户点「重新定位」：忽略缓存、重新申请浏览器定位并恢复跟随 */
async function refresh(): Promise<void> {
  generation++
  stopWatch()
  detectPromise = null
  location.value = null
  try { sessionStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
  await detect(true)
}

/** 用户点「切回花溪」：停止跟随并按花溪区查看天气 / 景点 */
function useHuaxi(): void {
  generation++
  stopWatch()
  manualMode = true
  detectPromise = null
  locating.value = false
  error.value = ''
  apply({ ...HUAXI, updatedAt: Date.now() })
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', stopWatch)
}

export function useLocation() {
  return {
    location,
    locating,
    error,
    sourceText,
    distanceToHuaxi,
    ensure,
    refresh,
    useHuaxi,
  }
}
