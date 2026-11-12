/** 腾讯位置服务（JS API GL + WebService 路线规划）加载器与工具。
 *
 * 为什么换腾讯：
 *  - 小程序端 <map> 本来就是腾讯引擎，PC 端统一到腾讯可让两端底图、坐标口径、版权信息一致；
 *  - 腾讯 GL JS 支持矢量底图与 MultiMarker/MultiPolyline，点位数百级也不卡；
 *  - 路线规划走 WebService 的 direction/v1（JSONP 调用，免后端代理、免跨域）。
 *
 * key 类型说明：
 *  - `VITE_QQMAP_JS_KEY` 需要「Web端 (JS API GL)」类型的 key，并配置域名白名单；
 *  - 同一个 key 也带 WebServiceAPI 额度时，本文件的 JSONP 路线请求可直接复用。
 */

export const QQMAP_KEY = ((import.meta.env.VITE_QQMAP_JS_KEY as string | undefined) || '').trim()

/** 路线规划用的 WebService key（可与 JS key 不同；不填则复用 JS key） */
export const QQMAP_WS_KEY = (((import.meta.env.VITE_QQMAP_WS_KEY as string | undefined) || '').trim()) || QQMAP_KEY

/** 腾讯 key 形如 EDCBZ-TPACQ-TNC5G-BDL7X-VISXQ-PVFSJ（5 段 5 位 + 末段 5~6 位，可含数字） */
const KEY_RE = /^[A-Z0-9]{5}(-[A-Z0-9]{5}){4}-[A-Z0-9]{5,6}$/
export const qqmapConfigured = KEY_RE.test(QQMAP_KEY)
export const directionsConfigured = KEY_RE.test(QQMAP_WS_KEY)

let loader: Promise<any> | null = null

/** 动态加载 GL JS（幂等）。返回 window.TMap。 */
export function loadQQMap(): Promise<any> {
  const w = window as any
  if (w.TMap) return Promise.resolve(w.TMap)
  if (!qqmapConfigured) return Promise.reject(new Error('未配置腾讯地图 JS API key'))
  if (loader) return loader
  loader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://map.qq.com/api/gljs?v=1.exp&key=${encodeURIComponent(QQMAP_KEY)}`
    script.async = true
    script.onload = () => (w.TMap ? resolve(w.TMap) : reject(new Error('腾讯地图 JS API 已加载但未初始化')))
    script.onerror = () => reject(new Error('腾讯地图 JS API 加载失败，请检查网络与域名白名单'))
    document.head.appendChild(script)
  })
  return loader
}

// ---------------- 路线规划（WebService direction/v1，JSONP） ----------------

export type TravelMode = 'driving' | 'transit' | 'walking' | 'riding'

export const TRAVEL_MODES: { key: TravelMode; label: string; icon: string; hint: string }[] = [
  { key: 'driving', label: '驾车', icon: '🚗', hint: '自驾 / 打车' },
  { key: 'transit', label: '公交', icon: '🚌', hint: '公交 / 地铁' },
  { key: 'walking', label: '步行', icon: '🚶', hint: '步行可达' },
  { key: 'riding', label: '骑行', icon: '🚲', hint: '共享单车 / 骑行' },
]

export interface RouteStep {
  instruction: string
  distance: number
  durationSec: number
}

export interface DirectionResult {
  ok: boolean
  /** 折线点 [lng, lat] 数组（腾讯返回的是 lat,lng 顺序，这里已转换） */
  path: Array<[number, number]>
  distance: number
  durationSec: number
  steps: RouteStep[]
  error?: string
}

/** 腾讯返回的压缩折线 → [[lng,lat]]：前两个是绝对值，其后是相对前前一个点的偏移（÷1e6）。 */
export function decodePolyline(coors: number[] | undefined): Array<[number, number]> {
  if (!coors || coors.length < 4) return []
  const abs: number[] = [coors[0], coors[1]]
  for (let i = 2; i < coors.length; i++) abs[i] = abs[i - 2] + coors[i] / 1e6
  const out: Array<[number, number]> = []
  for (let i = 0; i < abs.length; i += 2) out.push([abs[i + 1], abs[i]]) // lat,lng → lng,lat
  return out
}

let seq = 0
function jsonp(url: string, timeout = 12000): Promise<any> {
  return new Promise((resolve, reject) => {
    const cb = `__qqmap_cb_${Date.now()}_${seq++}`
    const w = window as any
    const script = document.createElement('script')
    const cleanup = () => {
      delete w[cb]
      script.remove()
      clearTimeout(timer)
    }
    const timer = setTimeout(() => {
      cleanup()
      reject(new Error('路线请求超时'))
    }, timeout)
    w[cb] = (data: any) => {
      cleanup()
      resolve(data)
    }
    script.src = `${url}${url.includes('?') ? '&' : '?'}output=jsonp&callback=${cb}`
    script.onerror = () => {
      cleanup()
      reject(new Error('路线请求失败（网络或配额）'))
    }
    document.head.appendChild(script)
  })
}

const MODE_PATH: Record<Exclude<TravelMode, 'riding'>, string> = {
  driving: 'driving',
  walking: 'walking',
  transit: 'transit',
}

/**
 * 查询两点间真实道路路线。
 *  - 骑行：腾讯路线服务暂不提供，返回 ok=false，由调用方按直线距离估算；
 *  - 公交：transit 必须带 from/to，返回首条方案。
 */
export async function fetchDirection(
  from: [number, number],
  to: [number, number],
  mode: TravelMode,
): Promise<DirectionResult> {
  if (!directionsConfigured) return { ok: false, path: [], distance: 0, durationSec: 0, steps: [], error: '未配置路线 key' }
  if (mode === 'riding') return { ok: false, path: [], distance: 0, durationSec: 0, steps: [], error: '骑行暂不支持' }

  const url = `https://apis.map.qq.com/ws/direction/v1/${MODE_PATH[mode]}/?from=${from[1]},${from[0]}&to=${to[1]},${to[0]}&key=${QQMAP_WS_KEY}`
  try {
    const data = await jsonp(url)
    if (data?.status !== 0) {
      return { ok: false, path: [], distance: 0, durationSec: 0, steps: [], error: data?.message || '路线服务返回异常' }
    }
    const route = (data.result?.routes || [])[0]
    if (!route) return { ok: false, path: [], distance: 0, durationSec: 0, steps: [], error: '无可用路线' }
    return {
      ok: true,
      path: decodePolyline(route.polyline),
      distance: Number(route.distance) || 0,
      durationSec: Number(route.duration) || 0,
      steps: (route.steps || []).map((s: any) => ({
        instruction: String(s.instruction || '').replace(/<[^>]+>/g, ''),
        distance: Number(s.distance) || 0,
        durationSec: Number(s.duration) || 0,
      })),
    }
  } catch (e: any) {
    return { ok: false, path: [], distance: 0, durationSec: 0, steps: [], error: e?.message || '路线请求失败' }
  }
}

export function escapeHtml(s: string): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
}
