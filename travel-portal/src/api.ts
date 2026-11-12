import axios, { type AxiosRequestConfig } from 'axios'

/** 极简 Toast：无 UI 库依赖，供所有页面直接调用 */
export function toast(msg: string, isErr = false) {
  const el = document.createElement('div')
  el.className = 'toast' + (isErr ? ' err' : '')
  el.textContent = msg
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 2600)
}

const TOKEN_KEY = 'travel_portal_token'
const EXP_KEY = 'travel_portal_token_exp'
const KIND_KEY = 'travel_portal_login_kind' // account | guest
const DEVICE_KEY = 'travel_portal_device'   // PC 匿名游客的稳定设备标识

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function getLoginKind() {
  return localStorage.getItem(KIND_KEY) || ''
}
/** 同一设备重登仍为同一匿名游客身份，已保存行程不会丢 */
export function getDeviceId(): string {
  let id = localStorage.getItem(DEVICE_KEY) || ''
  if (!id) {
    id = 'pc_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 12)
    localStorage.setItem(DEVICE_KEY, id)
  }
  return id
}
export function setToken(token: string, expiresIn = 0, kind: 'account' | 'guest' = 'account') {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(KIND_KEY, kind)
  localStorage.setItem(EXP_KEY, String(Date.now() + (expiresIn || 604800) * 1000))
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(EXP_KEY)
  localStorage.removeItem(KIND_KEY)
}

const http = axios.create({ baseURL: '/api/v1', timeout: 20000 })

http.interceptors.request.use((cfg) => {
  const token = getToken()
  if (token) cfg.headers.Authorization = 'Bearer ' + token
  return cfg
})

http.interceptors.response.use(
  (res) => res,
  async (err) => {
    const cfg = err.config as (AxiosRequestConfig & { _authRetry?: boolean }) | undefined
    const url = String(cfg?.url || '')
    // 刷新页面时静默校验会话 / 定位失败自动兜底，都不应弹错误提示
    if (url.includes('/auth/me') || url.includes('/location/resolve')) {
      return Promise.reject(err)
    }
    // 游客模式 JWT 失效：自动重走匿名登录并重放原请求（设计方案 7.5 的 401 重登重放）
    if (err.response?.status === 401 && cfg && !cfg._authRetry
      && !url.includes('/auth/') && getLoginKind() === 'guest') {
      cfg._authRetry = true
      try {
        await guestLogin()
        return await http.request(cfg)
      } catch {
        // 重登失败落到下面的统一提示
      }
    }
    const detail = err.response?.data?.detail
    const msg = typeof detail === 'string'
      ? detail
      : err.response
        ? `请求失败(${err.response.status})`
        : '无法连接后端服务，请确认 travel-api 已启动'
    toast(msg, true)
    return Promise.reject(err)
  },
)

/** PC 游客模式：签发 typ=anonymous 的标准 JWT（不冒充微信登录，无需 AppID） */
export async function guestLogin(): Promise<AuthUser> {
  const { data } = await http.post<{ token: string; expires_in: number }>(
    '/auth/anonymous', { device_id: getDeviceId() },
  )
  setToken(data.token, data.expires_in, 'guest')
  return http.get<AuthUser>('/auth/me').then((r) => r.data)
}

// ---------- 类型 ----------
export interface AuthUser {
  user_id: number
  username: string
  nickname: string
  phone: string
  is_guest: boolean
  created_at: string
}

export interface AuthResult {
  token: string
  token_type: 'Bearer'
  expires_in: number
  user: AuthUser
}

export interface RefreshResult {
  token: string
  token_type: 'Bearer'
  expires_in: number
  user_id: number
  is_new: boolean
}

export interface Poi {
  id: number
  name: string
  category: string
  sub_type: string
  address: string
  longitude: number
  latitude: number
  suggest_duration_min: number
  ticket_price: number
  price_level: number
  rating: number
  review_count?: number
  hot_score?: number
  visitable: boolean
  /** 图片资源（相对 /static/poi/xxx.jpg） */
  images?: string[]
  /** 封面图（后端行程接口返回的单张图片） */
  image?: string
  tags?: string[]
  open_time?: string[][]
}

// ---------- 天气（后端代理 Open-Meteo，免密钥；key 不出现在前端） ----------
export interface WeatherLive {
  weather: string
  temperature: string
  feels_like?: string
  humidity: string
  winddirection: string
  windpower: string
  wind_speed?: string
  precipitation?: string
  cloud_cover?: string
  is_day?: boolean
}
export interface WeatherCast {
  date: string
  week: string
  dayweather: string
  nightweather: string
  daytemp: string
  nighttemp: string
  icon?: string
  precip?: number | null
}
export interface WeatherInfo {
  configured: boolean
  available?: boolean
  message?: string
  error?: string
  notice?: string
  source?: string
  provider?: string
  adcode?: string
  city?: string
  province?: string
  reporttime?: string
  latitude?: number
  longitude?: number
  live?: WeatherLive | null
  casts?: WeatherCast[]
  forecast_days?: number
}

/** 15 天逐日预报（Open-Meteo 免密钥公开 API 的服务端代理） */
export interface ForecastDay {
  date: string
  week: string
  dayweather: string
  nightweather: string
  icon?: string
  daytemp: string
  nighttemp: string
  precip?: number | null
}
export interface ForecastInfo {
  available: boolean
  message?: string
  source?: string
  days?: number
  items?: ForecastDay[]
}

/** 服务端位置解析结果：坐标走 POST body，精确位置不出现在访问日志 URL 上 */
export interface LocationInfo {
  configured: boolean
  message?: string
  source?: 'browser' | 'ip' | 'default'
  lng?: number
  lat?: number
  accuracy?: 'precise' | 'city' | 'none'
  adcode?: string
  province?: string
  city?: string
  district?: string
  formatted?: string
}

// ---------- 预设主题路线 / 游学（G7 / T9） ----------

/** 行程槽位上的游学保底站附加信息 */
export interface PresetItemMeta {
  seq: number
  is_study_stop?: boolean
  narration_title: string
  narration_text: string
  task_card?: { title?: string; type?: string; content?: string }
  photo_tip?: string
  gate_status?: string
  gate_notes?: string[]
  walk_in_min?: number
  stay_min?: number
}

export interface PresetRouteSummary {
  code: string
  title: string
  subtitle: string
  theme: string
  theme_name: string
  target_group: string
  duration_hours: number
  full_day_hours?: number
  season_window: Record<string, string>
  difficulty: string
  enabled: boolean
  version: number
  summary: string
  cover_image?: string
  reservation_note: string
  transit_note: string
  mode_tips: Record<string, string>
  sources: { item: string; source: string; verified: boolean; note?: string }[]
  policy_checked_at: string
  unverified_sources: string[]
  stop_count: number
  day: {
    date: string; weekday: string; day_type: string; tone: string
    indoor_venues_open: boolean; note: string
  }
  visit_date: string
  reservation_required: boolean
}

export interface PresetStop {
  seq: number
  poi_id: number
  effective_poi_id: number
  name: string
  original_name: string
  sub_type: string
  address: string
  longitude?: number | null
  latitude?: number | null
  image?: string | null
  visit_policy: string
  stay_min: number
  effective_stay_min: number
  walk_in_min: number
  slot: string
  must_visit: boolean
  is_addon: boolean
  narration_title: string
  narration_text: string
  original_narration?: string
  task_cards: { title?: string; type?: string; content?: string }[]
  photo_tip: string
  date_gate: Record<string, unknown>[]
  gate: {
    status: string
    notes: string[]
    actions: string[]
    effective_poi_id: number | null
    effective_stay_min: number | null
    effective_narration: string | null
    suggest_arrival: string | null
    reservation: Record<string, unknown> | null
    gate_details: { type: string; label: string; passed: boolean; message: string }[]
    effective_name: string
    original_name: string
    replaced: boolean
  }
}

export interface PresetRouteDetail extends PresetRouteSummary {
  stops: PresetStop[]
  addon_stops: PresetStop[]
  total_stay_min: number
  total_walk_min: number
  estimated_minutes: number
  degraded_count: number
  gate_notes: string[]
  reservation: Record<string, unknown> | null
}

export interface TripItem {
  slot: string
  slot_name: string
  poi_id: number | null
  name: string
  category: string
  start_time: string
  duration_min: number
  cost: number
  longitude?: number | null
  latitude?: number | null
  /** 封面图（相对 /static/poi/xxx.jpg） */
  image?: string | null
  /** 游学保底站的逐站讲解与任务卡；空对象 = 普通点位 */
  preset?: PresetItemMeta | Record<string, never>
}

export interface DayPlan {
  day_index: number
  theme: string
  day_budget: number
  day_cost: number
  /** 出行首日推算的日期与星期（攻略解析 / 判官卡片用，后端可选返回） */
  date?: string | null
  week?: string | null
  items: TripItem[]
}

export interface Trip {
  trip_id: string
  mode: string
  mode_name: string
  days: number
  budget: number
  total_cost: number
  budget_usage: number
  score: number
  hotel: {
    poi_id?: number | null
    name: string
    category?: string
    longitude: number
    latitude: number
    ticket_price: number
    sub_type?: string
  } | null
  hotel_nights: number
  days_plan: DayPlan[]
  relax_log: { label: string }[]
  explanation: { label: string }[]
  /** 本次行程实际使用的权重（0~1，和为 1） */
  custom_weights?: Record<string, number>
  /** 权重画像（含标签与百分比） */
  weight_profile?: WeightProfileItem[]
  /** 是否偏离模式默认权重 */
  is_personalized?: boolean
  /** 出行首日（攻略解析/对话创建时后端可选返回） */
  start_date?: string | null
  /** 节奏微调 */
  pace_config?: PaceConfig & { preset_route?: PresetRouteDetail }
  /** 本次行程注入的预设主题路线详情（含逐站讲解与 date_gate 结论） */
  preset_route?: PresetRouteDetail | null
  /** 出行日期（date_gate 判定依据） */
  visit_date?: string | null
}

// ---------- 个性化 ----------

export interface WeightDimension {
  key: string
  label: string
  icon: string
  desc: string
  hint: string
}

export interface WeightProfileItem extends WeightDimension {
  weight: number
  percent: number
}

export interface WeightPreset {
  key: string
  label: string
  icon: string
  desc: string
  weights: Record<string, number>
}

export interface EveningPreference {
  key: string
  label: string
  icon: string
  desc: string
  evening_slot: string
  day_end: string
}

export interface PaceConfig {
  daily_poi_max?: number
  play_hours_max?: number
  evening?: string
}

export interface WeightMetadata {
  dimensions: WeightDimension[]
  presets: WeightPreset[]
  evening_preferences: EveningPreference[]
  modes: Record<string, {
    mode_name: string
    weights: Record<string, number>
    slider_defaults: Record<string, number>
    daily_poi_max: number
    play_hours_max: number
    evening_slot: string
  }>
}

export interface PreviewItem {
  poi_id: number
  name: string
  category: string
  sub_type: string
  rating: number
  ticket_price: number
  suggest_duration_min: number
  score: number
  base_score: number
  rank: number
  base_rank: number
  image?: string | null
}

export interface ChangedItem {
  poi_id: number
  name: string
  direction: 'up' | 'down'
  image?: string | null
}

export interface WeightPreview {
  mode: string
  weights: Record<string, number>
  profile: WeightProfileItem[]
  base_weights: Record<string, number>
  is_personalized: boolean
  items: PreviewItem[]
  changed: ChangedItem[]
}

export interface Mode {
  mode: string
  mode_name: string
  description: string
  budget_hint: string
  weights: Record<string, number>
  hard_rules_brief: Record<string, unknown>
}

export interface CompareResult {
  mode: string
  mode_name: string
  total_cost: number
  budget_usage: number
  score: number
  poi_count: number
  poi_per_day: number
  hotel: string
  hotel_nights: number
  free_poi_ratio: number
  relax_count: number
  days_plan: { day_index: number; theme: string; poi_names: string[] }[]
}

export interface GeneratePayload {
  days: number
  budget: number
  mode: string
  preferences: string[]
  party_type: string
  seed: number
  /** 个性化权重（0~100 原始滑块值）；省略即沿用模式默认 */
  weights?: Record<string, number>
  /** 节奏微调 */
  pace?: PaceConfig
  /** 开销偏好（住宿档位 / 出行方式），影响整体开销与实际生成 */
  cost_prefs?: Record<string, unknown>
  /** 预设主题路线 code；命中时站点按 seq 预占第 1 天，其余槽位按 mode 自由补全 */
  preset_route_code?: string
  /** 出行日期 YYYY-MM-DD；驱动 date_gate（开放日 / 花期 / 预约提醒）判定 */
  visit_date?: string
  /** 是否并入全天深度版加段 */
  include_addon?: boolean
}

export const MODE_ORDER = ['leisure', 'blitz', 'premium', 'checkin']
export const MODE_EMOJI: Record<string, string> = {
  leisure: '🌿', blitz: '⚡', premium: '✨', checkin: '📸',
}
export const CATEGORY_NAME: Record<string, string> = {
  scenic: '景点', food: '美食', hotel: '住宿', leisure: '休闲', study: '游学',
}

export const PREFERENCES = [
  { code: 'nature', label: '自然风光' },
  { code: 'heritage', label: '历史人文' },
  { code: 'food', label: '美食探店' },
  { code: 'photospot', label: '拍照出片' },
  { code: 'night_view', label: '夜景夜游' },
  { code: 'parent_child', label: '亲子友好' },
  { code: 'outdoor', label: '户外徒步' },
  { code: 'relax', label: '休闲放松' },
]

export const PARTY_TYPES = [
  { code: 'couple', label: '情侣 / 朋友' },
  { code: 'family', label: '家庭亲子' },
  { code: 'solo', label: '独自出行' },
  { code: 'group', label: '团队出行' },
]

export const api = {
  // 游客账号
  register: (payload: { username: string; password: string; nickname?: string; phone?: string }) =>
    http.post<AuthResult>('/auth/register', payload).then((r) => r.data),
  login: (payload: { account: string; password: string }) =>
    http.post<AuthResult>('/auth/login', payload).then((r) => r.data),
  me: () => http.get<AuthUser>('/auth/me').then((r) => r.data),
  /** JWT 滑动续期：旧 token 立即作废，返回新的 7 天 token */
  refresh: () => http.post<RefreshResult>('/auth/refresh', {}).then((r) => r.data),
  logout: () => http.post('/auth/logout', {}).then((r) => r.data),

  // 高德位置解析（服务端代理，仅用于把坐标翻译成区县地名）
  resolveLocation: (payload: { lng?: number; lat?: number }) =>
    http.post<LocationInfo>('/location/resolve', payload).then((r) => r.data),
  // 天气：Open-Meteo（免密钥）。lng/lat 必须为 WGS-84 坐标
  getWeather: (params?: { lng?: number; lat?: number; days?: number }) =>
    http.get<WeatherInfo>('/weather', { params }).then((r) => r.data),
  getForecast: (params: { lng?: number; lat?: number; days?: number }) =>
    http.get<ForecastInfo>('/weather/forecast', { params }).then((r) => r.data),

  getModes: () => http.get<Mode[]>('/trip-modes').then((r) => r.data),
  /** 预设主题路线列表（含按出行日期计算的 date_gate 概览） */
  getPresetRoutes: (params?: { theme?: string; target_group?: string; visit_date?: string }) =>
    http.get<{ items: PresetRouteSummary[] }>('/preset-routes', { params }).then((r) => r.data),
  /** 预设主题路线详情：逐站讲解 / 研学任务卡 / 日期闸门结论 */
  getPresetRoute: (code: string, params?: { visit_date?: string; include_addon?: boolean }) =>
    http.get<PresetRouteDetail>(`/preset-routes/${encodeURIComponent(code)}`, { params })
      .then((r) => r.data),
  /** 个性化：权重维度 / 预设 / 晚间偏好元数据 */
  getWeightMetadata: () =>
    http.get<WeightMetadata>('/weight-metadata').then((r) => r.data),
  /** 个性化：权重预览（不落库） */
  previewWeights: (payload: {
    mode: string
    weights: Record<string, number>
    preferences?: string[]
    pace?: PaceConfig
    top_k?: number
  }) => http.post<WeightPreview>('/trips/preview', payload).then((r) => r.data),
  /** 个性化：按权重重排既有行程 */
  reweightTrip: (tripId: string, payload: { weights: Record<string, number>; pace?: PaceConfig }) =>
    http.post<Trip>(`/trips/${tripId}/reweight`, payload).then((r) => r.data),
  getTags: () => http.get<{ code: string; name: string }[]>('/tags').then((r) => r.data),
  listPois: (params: Record<string, unknown>) =>
    http.get<{ total: number; items: Poi[] }>('/pois', { params }).then((r) => r.data),
  getPoi: (id: number) => http.get<Poi>(`/pois/${id}`).then((r) => r.data),
  generateTrip: (payload: GeneratePayload) =>
    http.post<Trip>('/trips/generate', payload).then((r) => r.data),
  compare: (payload: Omit<GeneratePayload, 'mode'>) =>
    http.post<{ results: CompareResult[]; note: string }>('/trips/compare', payload)
      .then((r) => r.data),
  getTrip: (id: string) => http.get<Trip>(`/trips/${id}`).then((r) => r.data),
  rebalance: (tripId: string, payload: Record<string, unknown>) =>
    http.post<Trip>(`/trips/${tripId}/rebalance`, payload).then((r) => r.data),
  slotCandidates: (tripId: string, day: number, slot: string) =>
    http.get<{ items: Poi[] }>(`/trips/${tripId}/days/${day}/slots/${slot}/candidates`)
      .then((r) => r.data),
  saveTrip: (tripId: string) =>
    http.post(`/trips/${tripId}/save`, {}).then((r) => r.data),
  /** 待计划篮子：把收藏的点位排入某一天（后端重算时间轴与费用） */
  addTripItem: (tripId: string, poiId: number, day: number) =>
    http.post<Trip>(`/trips/${tripId}/items/add`, { poi_id: poiId, day })
      .then((r) => r.data),
  /** 行程编辑：删除某个行程项 */
  deleteTripItem: (tripId: string, itemId: number) =>
    http.delete<Trip>(`/trips/${tripId}/items/${itemId}`).then((r) => r.data),
  /** 行程判官：点位密度 / 折返 / 开放时间 / 重复 / 预算体检 */
  diagnoseTrip: (tripId: string) =>
    http.get(`/trips/${tripId}/diagnose`).then((r) => r.data),
  /** 路线优化：同日点位重排减少通勤 */
  optimizeTrip: (tripId: string) =>
    http.post<Trip>(`/trips/${tripId}/optimize`, {}).then((r) => r.data),
  myTrips: () =>
    http.get<{ total: number; items: any[] }>('/trips').then((r) => r.data),
  deleteTrip: (tripId: string) =>
    http.delete(`/trips/${tripId}`).then((r) => r.data),

  // ---------- 专属问答「问小旅」 ----------
  qaStatus: () => http.get<QaStatus>('/qa/status').then((r) => r.data),
  qaSuggestions: () => http.get<{ items: string[] }>('/qa/suggestions').then((r) => r.data),
  qaChatSync: (payload: { message: string; conversation_id?: string; trip_id?: string }) =>
    http.post<QaAnswer>('/qa/chat/sync', payload).then((r) => r.data),
  qaConversations: () =>
    http.get<{ items: QaConversation[] }>('/qa/conversations').then((r) => r.data),
  qaConversation: (id: string) =>
    http.get<{ id: string; title: string; messages: QaMsg[] }>(`/qa/conversations/${id}`)
      .then((r) => r.data),
  qaDeleteConversation: (id: string) =>
    http.delete(`/qa/conversations/${id}`).then((r) => r.data),
  qaJudge: (payload: { trip_id: string; conversation_id?: string }) =>
    http.post<{ conversation_id: string; message_id?: number; answer: string; diagnose: DiagnoseResult }>(
      '/qa/judge', payload).then((r) => r.data),
  /** 对话式改行程：一句话 → 结构化 ops → 本地确定性重算 */
  chatEditTrip: (tripId: string, text: string) =>
    http.post<{ trip: Trip; reply: string; changes: string[]; ops: unknown[] }>(
      `/trips/${tripId}/chat-edit`, { text }).then((r) => r.data),
  /** 智能解析：粘贴攻略文本 → 匹配点位 → 生成行程 */
  parseGuideTrip: (payload: {
    text: string; start_date?: string | null; mode?: string; budget?: number | null
    conversation_id?: string | null
  }) => http.post<{
    trip: Trip; matched: string[]; unmatched: string[]; days: number
    note: string; answer: string; conversation_id?: string
  }>('/trips/parse-guide', payload).then((r) => r.data),
}

/** 打印 / 导出共用的行程纯文本 */
export function tripToText(trip: Trip): string {
  const lines: string[] = []
  lines.push(`花溪旅行 · ${trip.mode_name} ${trip.days} 天行程单`)
  lines.push(`人均预算 ¥${trip.budget} ｜ 预估花费 ¥${trip.total_cost} ｜ 预算使用率 ${Math.round(trip.budget_usage * 100)}%`)
  if (trip.hotel) lines.push(`住宿：${trip.hotel.name} × ${trip.hotel_nights} 晚`)
  if (trip.relax_log?.length) lines.push(`提示：${trip.relax_log.map((r) => r.label).join('；')}`)
  lines.push('')
  for (const day of trip.days_plan) {
    lines.push(`── Day ${day.day_index} ${day.theme}（¥${day.day_cost}）──`)
    for (const it of day.items) {
      lines.push(`  ${it.start_time}  ${it.slot_name}  ${it.name}  约${it.duration_min}分钟  ${it.cost > 0 ? '¥' + it.cost : '免费'}`)
    }
    lines.push('')
  }
  lines.push('数据口径：花溪区本地演示种子数据 · 行程仅供参考')
  return lines.join('\n')
}

// ---------- 专属问答类型与 SSE 客户端 ----------

export interface QaRef { kind: string; ref_id: string; name: string; summary?: string; poi_id?: number | null }

export interface QaStatus {
  enabled: boolean
  configured: boolean
  provider: string
  model: string
  masked_key: string
  aigc_label: string
}

export interface QaConversation {
  id: string
  title: string
  created_at?: string | null
  updated_at?: string | null
  message_count?: number
}

export interface QaMsg {
  id: number
  role: string
  content: string
  refs?: QaRef[]
  aigc?: boolean
  degraded?: boolean
  created_at?: string | null
}

export interface QaAnswer {
  conversation_id: string
  message_id?: number | null
  answer: string
  refs: QaRef[]
  aigc: boolean
  degraded: boolean
  usage?: Record<string, unknown>
  latency_ms: number
  error_code?: string | null
  trip?: Trip | null
}

export interface DiagnoseDay {
  day_index: number
  theme?: string
  play_count?: number
  commute_km?: number
  commute_min?: number
  [k: string]: unknown
}

export interface DiagnoseResult {
  trip_id: string
  total_cost?: number
  budget?: number
  issue_count?: number
  warn_count?: number
  overall?: { level?: string; stars?: number; summary?: string; commute_km?: number } | null
  day_summaries?: DiagnoseDay[]
  days?: DiagnoseDay[]
  suggestions?: Array<{ title: string; detail: string }>
  issues?: Array<{ level: string; title: string; detail: string }>
  summary?: string | null
  [k: string]: unknown
}

export interface QaStreamHandlers {
  onMeta?: (meta: { conversation_id: string; refs: QaRef[]; aigc_label?: string; trip?: Trip | null }) => void
  onDelta?: (text: string) => void
  onDone?: (done: { message_id?: number; aigc: boolean; degraded: boolean; latency_ms?: number; error_code?: string | null; trip?: Trip | null }) => void
}

/** SSE 流式问答：fetch + ReadableStream 逐事件解析（meta / delta / done）。 */
export async function qaChatStream(
  payload: { message: string; conversation_id?: string; trip_id?: string },
  handlers: QaStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const base = (import.meta as any).env?.VITE_API_BASE || '/api/v1'
  const resp = await fetch(`${base}/qa/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => '')
    throw new Error(text || `问答接口 ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const chunk of parts) {
      let event = 'message'
      const dataLines: string[] = []
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let data: any = {}
      try { data = JSON.parse(dataLines.join('\n')) } catch { continue }
      if (event === 'meta') handlers.onMeta?.(data)
      else if (event === 'delta') handlers.onDelta?.(data.text || '')
      else if (event === 'done') handlers.onDone?.(data)
    }
  }
}