/** 高德地图 JS API 2.0 加载器与共享类型。
 *
 * 密钥只从 Vite 环境变量读取（.env.local，已 gitignore），代码内不含任何可用 key。
 * 安全密钥必须在 JS API 脚本插入之前写入 window._AMapSecurityConfig，否则会报 INVALID_USER_SCODE。
 */
export interface MapPoint {
  id: string | number
  name: string
  lng: number
  lat: number
  category?: string
  address?: string
  label?: string
  group?: string
}

const HEX32 = /^[0-9a-fA-F]{32}$/
export const AMAP_KEY = ((import.meta.env.VITE_AMAP_JS_KEY as string | undefined) || '').trim()
export const AMAP_SECURITY = ((import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined) || '').trim()
export const amapConfigured = HEX32.test(AMAP_KEY)
export const securityConfigured = HEX32.test(AMAP_SECURITY)

let loader: Promise<any> | null = null

export function loadAMap(): Promise<any> {
  const w = window as any
  if (w.AMap) return Promise.resolve(w.AMap)
  if (!amapConfigured) return Promise.reject(new Error('未配置高德地图 JS API key'))
  if (loader) return loader

  loader = new Promise((resolve, reject) => {
    if (securityConfigured) {
      w._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY }
    }
    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.async = true
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(AMAP_KEY)}`
    script.onload = () => {
      if (w.AMap) resolve(w.AMap)
      else {
        loader = null
        reject(new Error('高德 JS API 已加载但未初始化，请检查 key 类型与安全密钥'))
      }
    }
    script.onerror = () => {
      loader = null
      reject(new Error('高德 JS API 加载失败，请检查网络、key 类型与 Referer 白名单'))
    }
    document.head.appendChild(script)
  })
  return loader
}

/** InfoWindow 内容是动态 HTML，POI 名称需转义，避免注入。 */
export function escapeHtml(s: string): string {
  const map: Record<string, string> = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }
  return String(s).replace(/[&<>"']/g, (ch) => map[ch] || ch)
}

// ---------- 路线规划（高德路径规划插件：驾车 / 公交 / 步行 / 骑行） ----------

/** 四种出行方式。与高德 JS API 的 AMap.Driving / Transfer / Walking / Riding 一一对应。 */
export type TravelMode = 'driving' | 'transit' | 'walking' | 'riding'

export const TRAVEL_MODES: { key: TravelMode; label: string; icon: string; hint: string }[] = [
  { key: 'driving', label: '驾车', icon: '🚗', hint: '自驾 / 打车' },
  { key: 'transit', label: '公交', icon: '🚌', hint: '公交 / 地铁' },
  { key: 'walking', label: '步行', icon: '🚶', hint: '步行可达' },
  { key: 'riding', label: '骑行', icon: '🚲', hint: '共享单车 / 骑行' },
]

/** 单条转向/换乘步骤。 */
export interface RouteStep {
  instruction: string
  distance: number
  durationSec: number
  path?: Array<[number, number]>
}

/** 一段路线（相邻两个点位之间）的完整信息（含用于绘制的 path）。 */
export interface RouteLeg {
  dayIndex: number
  fromSeq: number
  toSeq: number
  fromId: string | number
  toId: string | number
  fromName: string
  toName: string
  mode: TravelMode
  distance: number
  durationSec: number
  cost?: number
  steps: RouteStep[]
  path: Array<[number, number]>
  /** true = 高德真实路线；false = 网络/配额不可达时的直线距离估算兜底 */
  ok: boolean
}

/** 传给父组件（行程时间轴）的精简摘要。 */
export interface RouteLegSummary {
  dayIndex: number
  fromSeq: number
  toSeq: number
  fromName: string
  toName: string
  mode: TravelMode
  distance: number
  durationSec: number
  cost?: number
  ok: boolean
}

let routePluginsReady: Promise<any> | null = null

/** 加载四个路径规划插件（幂等）。返回 AMap 全局对象。 */
export function loadRoutePlugins(): Promise<any> {
  const w = window as any
  if (!amapConfigured) return Promise.reject(new Error('未配置高德地图 JS API key'))
  if (routePluginsReady) return routePluginsReady
  const ensure = w.AMap ? Promise.resolve(w.AMap) : loadAMap()
  routePluginsReady = ensure.then((AMap) => new Promise<any>((resolve) => {
    AMap.plugin(['AMap.Driving', 'AMap.Transfer', 'AMap.Walking', 'AMap.Riding'], () => resolve(AMap))
  }))
  return routePluginsReady
}
