import axios from 'axios'
import { ElMessage } from 'element-plus'

// 管理端登录态：账号密码换取标准 JWT（typ=admin，默认 12h），统一 Authorization: Bearer
// 换用新 key：旧版固定令牌不会被误判为已登录会话
export const ADMIN_TOKEN_KEY = 'travel_admin_session'
export const ADMIN_USER_KEY = 'travel_admin_user'
export const ADMIN_NAME_KEY = 'travel_admin_name'
export const ADMIN_EXP_KEY = 'travel_admin_token_exp'

export function getToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
}

export function isLoggedIn(): boolean {
  return getToken().length > 0
}

export function getAdminInfo(): { username: string; displayName: string } {
  return {
    username: localStorage.getItem(ADMIN_USER_KEY) ?? '',
    displayName: localStorage.getItem(ADMIN_NAME_KEY) ?? '管理员',
  }
}

export function setSession(data: LoginResult): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, data.token)
  localStorage.setItem(ADMIN_USER_KEY, data.username)
  localStorage.setItem(ADMIN_NAME_KEY, data.display_name)
  localStorage.setItem(ADMIN_EXP_KEY, String(Date.now() + (data.expires_in || 43200) * 1000))
}

export function clearSession(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
  localStorage.removeItem(ADMIN_USER_KEY)
  localStorage.removeItem(ADMIN_NAME_KEY)
  localStorage.removeItem(ADMIN_EXP_KEY)
}

const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })

http.interceptors.request.use((cfg) => {
  const token = getToken()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const isLoginCall = String(err.config?.url ?? '').includes('/admin/login')
    if (err.response?.status === 401) {
      clearSession()
      if (location.pathname !== '/login') location.href = '/login'
    }
    const detail = err.response?.data?.detail
    // 区分"连不上后端"与"接口报错"，便于排查
    const msg =
      typeof detail === 'string'
        ? detail
        : err.response
          ? `请求失败(${err.response.status})`
          : '无法连接后端服务，请先在 PyCharm 运行 travel-api/run.py'
    // 登录失败由登录页内联展示，避免重复弹窗
    if (!isLoginCall) ElMessage.error(msg)
    return Promise.reject(err)
  },
)

// ---------- 认证 ----------
export interface LoginResult {
  token: string
  token_type?: string
  username: string
  display_name: string
  expires_in: number
}

/** 账号密码登录：成功后由调用方 setSession 保存 JWT */
export async function adminLogin(username: string, password: string): Promise<LoginResult> {
  const { data } = await http.post<LoginResult>('/admin/login', { username, password })
  return data
}

// ---------- 类型 ----------
export interface Poi {
  /** 后端同时返回 id 与 poi_id（同值），此处统一使用 poi_id */
  poi_id: number
  id?: number
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
  visitable: boolean
  /** 图片资源（相对 /static/poi/xxx.jpg） */
  images?: string[]
  /** 图片授权元信息，与 images 同序对应 */
  image_meta?: {
    source: string
    source_name: string
    author: string
    license: string
    license_url: string
  }[]
  tags?: string[]
}

export interface ModeConfig {
  mode: string
  mode_name: string
  description: string
  weights: Record<string, number>
  hard_rules: Record<string, any>
  slot_template: any[]
  version: number
}

export interface Stats {
  poi: {
    total: number; visitable: number; offline: number; online_rate: number
    avg_rating: number
    by_category: { code: string; name: string; count: number }[]
  }
  trip: {
    total: number; saved: number; draft: number
    avg_cost: number; avg_budget: number
    by_mode: { mode: string; name: string; count: number }[]
  }
  tags: { total: number }
  users: { total: number }
  trend: { date: string; count: number }[]
  budget_distribution: { label: string; count: number }[]
  top_pois: { poi_id: number; name: string; count: number }[]
  generated_at: string
}

export interface AdminTrip {
  trip_id: string
  mode: string
  mode_name: string
  days: number
  budget: number
  total_cost: number
  status: string
  seed: number
  preferences: string[]
  poi_count: number
  created_at: string
}

export interface TagItem {
  id: number
  code: string
  name: string
  poi_count: number
}

export interface TagSynonym {
  id: number
  alias: string
  canonical_code: string
  canonical_name: string
  note: string
}

export interface PriceBand {
  id: number
  name: string
  min_price: number
  max_price: number
  price_level: number
  enabled: boolean
  description: string
}

export interface EffectiveRule {
  id: number
  poi_id: number
  kind: 'price' | 'hours'
  value: Record<string, any>
  valid_from: string
  valid_to: string
  note: string
  enabled: boolean
}

export interface ModeVersion {
  id: number
  mode: string
  version: number
  status: string
  traffic_pct: number
  note: string
  weights: Record<string, number>
  hard_rules: Record<string, any>
  description: string
  created_at: string
}

export interface ReminderItem {
  id: number
  trip_id: string
  visit_date: string
  remind_at: string
  status: string
  openid: string
  last_error: string
  message: string
}

export interface UserItem {
  id: number
  openid: string
  nickname: string
  role: string
  status: number
  trip_count: number
  created_at: string
}

export interface SystemHealth {
  status: string
  database: {
    host: string; port: number; name: string; connected: boolean
    tables: number; poi_count: number; trip_count: number
  }
  cache: { mode_entries: number; poi_entries: number }
  images?: {
    total_pois: number
    with_images: number
    with_meta: number
    static_dir: string
    files: number
    providers?: {
      name: string; display_name: string; license_type: string
      available: boolean; reason: string; requires_key: boolean
    }[]
  }
  features: {
    route_api: boolean
    ai_polish: boolean
    /** P1/P2 增强运行态 */
    route_api_key?: boolean
    ai_polish_configured?: boolean
    subscribe_msg?: boolean
    subscribe_configured?: boolean
    geo_locate?: boolean
    preset_routes?: boolean
    mock_login: boolean
    /** G4 认证运行态（真实 code2session + 自签 JWT） */
    auth_mode?: string
    jwt_alg?: string
    jwt_expire_hours?: number
    jwt_secret?: boolean
    wechat_credentials?: boolean
    legacy_hmac?: boolean
    /** 天气数据源标识（当前为 open-meteo） */
    weather_provider?: string
    /** 高德是否已配置（仅用于逆地理 / IP 地名解析） */
    amap_geocode?: boolean
    /** 是否提供 15 天预报 */
    forecast_15d?: boolean
  }
}

/** 权重归一化：后端要求 9 维静态权重和 = 1.0，保存前自动调整 */
export function normalizeWeights(weights: Record<string, number>): Record<string, number> {
  const keys = Object.keys(weights).filter((k) => k !== 'budget_fit')
  const sum = keys.reduce((s, k) => s + (weights[k] || 0), 0)
  if (sum <= 0) return { ...weights }
  const out: Record<string, number> = {}
  for (const k of keys) out[k] = Number(((weights[k] || 0) / sum).toFixed(4))
  if ('budget_fit' in weights) out.budget_fit = weights.budget_fit
  // 消除浮点尾差
  const diff = 1 - Object.entries(out).filter(([k]) => k !== 'budget_fit')
    .reduce((s, [, v]) => s + v, 0)
  if (keys.length) out[keys[0]] = Number((out[keys[0]] + diff).toFixed(4))
  return out
}

// ---------- 接口 ----------
export const api = {
  // 账号
  getMe() {
    return http.get<{ username: string; display_name: string; last_login_at: string | null }>('/admin/me')
  },
  logout() {
    return http.post('/admin/logout')
  },
  changePassword(old_password: string, new_password: string) {
    return http.post<{ message: string }>('/admin/password', { old_password, new_password })
  },

  // ---------- 问答管理（知识库 / 对话审计 / 模型配置） ----------
  listQaKnowledge(params: Record<string, unknown>) {
    return http.get<{ total: number; items: QaKnowledgeItem[] }>('/admin/qa/knowledge', { params })
  },
  createQaKnowledge(data: Partial<QaKnowledgeItem>) {
    return http.post<QaKnowledgeItem>('/admin/qa/knowledge', data)
  },
  updateQaKnowledge(id: number, data: Partial<QaKnowledgeItem>) {
    return http.put<QaKnowledgeItem>(`/admin/qa/knowledge/${id}`, data)
  },
  deleteQaKnowledge(id: number) {
    return http.delete(`/admin/qa/knowledge/${id}`)
  },
  listQaConversations(params: Record<string, unknown>) {
    return http.get<{ total: number; items: QaConversationItem[] }>('/admin/qa/conversations', { params })
  },
  getQaConversation(id: string) {
    return http.get<QaConversationDetail>(`/admin/qa/conversations/${id}`)
  },
  deleteQaConversation(id: string) {
    return http.delete(`/admin/qa/conversations/${id}`)
  },
  getQaStats() {
    return http.get<QaStats>('/admin/qa/stats')
  },
  getQaConfig() {
    return http.get<QaModelConfig>('/admin/qa/config')
  },
  updateQaConfig(data: Partial<QaModelConfig>) {
    return http.put<QaModelConfig>('/admin/qa/config', data)
  },
  testQaConfig(data?: Partial<QaModelConfig>) {
    return http.post<QaConfigTestResult>('/admin/qa/config/test', data || {})
  },


  // 资源
  listPois(params: Record<string, unknown>) {
    return http.get<{ total: number; items: Poi[] }>('/admin/pois', { params }).then((res) => {
      // 后端兼容返回 id / poi_id 两个字段，这里统一成 poi_id
      res.data.items = (res.data.items || []).map((p) => ({
        ...p,
        poi_id: p.poi_id ?? p.id ?? 0,
      }))
      return res
    })
  },
  createPoi(data: Partial<Poi>) {
    return http.post('/admin/pois', data)
  },
  updatePoi(id: number, data: Partial<Poi>) {
    return http.put(`/admin/pois/${id}`, data)
  },
  deletePoi(id: number) {
    return http.delete(`/admin/pois/${id}`)
  },
  toggleVisitable(id: number, visitable: boolean) {
    return http.patch(`/admin/pois/${id}/visitable`, null, { params: { visitable } })
  },
  importFile(file: File) {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/admin/pois/import', fd)
  },
  exportUrl() {
    return '/api/v1/admin/pois/export'
  },

  // 图片资源
  /** 上传本地图片，返回 /static/poi/xxx 相对地址 */
  uploadImage(file: File) {
    const fd = new FormData()
    fd.append('file', file)
    return http.post<{
      url: string; filename: string; size: number
      meta: { source: string; source_name: string; author: string; license: string; license_url: string }
    }>('/admin/pois/images/upload', fd)
  },
  /** 联网抓取实景图片（新增资源时一键取图），返回来源与授权信息 */
  fetchImages(params: { name: string; sub_type?: string; category?: string; count?: number }) {
    return http.get<{
      items: { url: string; source: string; source_name: string; author: string; license: string; license_url: string }[]
      count: number
    }>('/admin/pois/images/fetch', { params })
  },
  /** 对已存在资源联网补图 */
  fetchPoiImages(id: number, count = 3) {
    return http.post<{ poi_id: number; images: string[]; added: number }>(
      `/admin/pois/${id}/images/fetch`, null, { params: { count } },
    )
  },
  /** 把外部图片直链下载到本地，返回本地相对地址 */
  localizeImage(url: string) {
    return http.post<{
      url: string; width: number; height: number
      meta: { source: string; source_name: string; author: string; license: string; license_url: string }
    }>('/admin/pois/images/localize', null, { params: { url } })
  },
  /** 各图片源的可用性与授权类型 */
  listImageProviders() {
    return http.get<{
      items: { name: string; display_name: string; license_type: string; available: boolean; reason: string; requires_key: boolean }[]
      usable: string[]
      keys: { name: string; env_name: string; configured: boolean; masked: string }[]
    }>('/admin/pois/images/providers', { timeout: 30000 })
  },
  /** 配置图片源 API Key（写入服务端 .env，不回传明文） */
  setImageProviderKey(name: string, value: string) {
    return http.post<{
      ok: boolean
      keys: { name: string; env_name: string; configured: boolean; masked: string }[]
    }>('/admin/pois/images/keys', { name, value })
  },

  // 模式配置
  listModes() {
    return http.get<ModeConfig[]>('/admin/mode-configs')
  },
  updateMode(mode: string, data: {
    weights?: Record<string, number>
    hard_rules?: Record<string, any>
    description?: string
  }) {
    const payload: Record<string, unknown> = { ...data }
    if (data.weights) payload.weights = normalizeWeights(data.weights)
    return http.put(`/admin/mode-configs/${mode}`, payload)
  },
  listModeVersions(mode: string) {
    return http.get<{ mode: string; items: ModeVersion[] }>(`/admin/mode-configs/${mode}/versions`)
  },
  rollbackMode(mode: string, version: number) {
    return http.post(`/admin/mode-configs/${mode}/rollback/${version}`)
  },
  createGray(mode: string, data: {
    weights: Record<string, number>
    hard_rules?: Record<string, any>
    description?: string
    traffic_pct: number
    note?: string
  }) {
    return http.post(`/admin/mode-configs/${mode}/gray`, {
      ...data, weights: normalizeWeights(data.weights),
    })
  },
  promoteGray(mode: string, version: number) {
    return http.post(`/admin/mode-configs/${mode}/gray/${version}/promote`)
  },
  deleteGray(mode: string, version: number) {
    return http.delete(`/admin/mode-configs/${mode}/gray/${version}`)
  },

  // 运营概览
  getStats() {
    return http.get<Stats>('/admin/stats/overview')
  },

  // 行程管理
  listTrips(params: Record<string, unknown>) {
    return http.get<{ total: number; items: AdminTrip[] }>('/admin/trips', { params })
  },
  getTripDetail(id: string) {
    return http.get<any>(`/admin/trips/${id}`)
  },
  deleteTrip(id: string) {
    return http.delete(`/admin/trips/${id}`)
  },

  // 标签字典
  listTags() {
    return http.get<{ total: number; items: TagItem[] }>('/admin/tags')
  },
  createTag(data: { code: string; name: string }) {
    return http.post('/admin/tags', data)
  },
  updateTag(id: number, data: { code: string; name: string }) {
    return http.put(`/admin/tags/${id}`, data)
  },
  deleteTag(id: number) {
    return http.delete(`/admin/tags/${id}`)
  },
  listTagSynonyms() {
    return http.get<{ items: TagSynonym[] }>('/admin/tags/synonyms')
  },
  createTagSynonym(data: { alias: string; canonical_code: string; note?: string }) {
    return http.post('/admin/tags/synonyms', data)
  },
  deleteTagSynonym(id: number) {
    return http.delete(`/admin/tags/synonyms/${id}`)
  },
  mergeTags(data: { from_code: string; to_code: string }) {
    return http.post('/admin/tags/merge', data)
  },

  // 价格分档 / 生效时间（A3）
  listPriceBands() {
    return http.get<{ items: PriceBand[] }>('/admin/price-bands')
  },
  createPriceBand(data: Omit<PriceBand, 'id'>) {
    return http.post('/admin/price-bands', data)
  },
  updatePriceBand(id: number, data: Omit<PriceBand, 'id'>) {
    return http.put(`/admin/price-bands/${id}`, data)
  },
  deletePriceBand(id: number) {
    return http.delete(`/admin/price-bands/${id}`)
  },
  applyPriceBands(category?: string) {
    return http.post<{ updated: number; category: string }>('/admin/price-bands/apply', { category })
  },
  listEffectiveRules(poiId: number) {
    return http.get<{ items: EffectiveRule[] }>(`/admin/pois/${poiId}/effective-rules`)
  },
  createEffectiveRule(data: Omit<EffectiveRule, 'id'>) {
    return http.post('/admin/effective-rules', data)
  },
  deleteEffectiveRule(id: number) {
    return http.delete(`/admin/effective-rules/${id}`)
  },

  // 订阅提醒运维（T8）
  listReminders(status?: string) {
    return http.get<{
      total: number
      counts: Record<string, number>
      items: ReminderItem[]
    }>('/admin/reminders', { params: status ? { status } : {} })
  },
  runReminders() {
    return http.post<{ sent: number; failed: number; skipped: number; due: number; message: string }>(
      '/admin/reminders/run',
    )
  },

  // 用户
  listUsers(params: Record<string, unknown>) {
    return http.get<{ total: number; items: UserItem[] }>('/admin/users', { params })
  },
  toggleUser(id: number, status: number) {
    return http.patch(`/admin/users/${id}/status`, { status })
  },

  // 预设主题路线（A7：站点编排查看 / 季节性开关 / 政策周更校验）
  listPresetRoutes() {
    return http.get<{ items: any[] }>('/admin/preset-routes').then((r) => r.data)
  },
  getPresetRoute(code: string, visitDate?: string) {
    return http.get<any>(`/admin/preset-routes/${encodeURIComponent(code)}`, {
      params: visitDate ? { visit_date: visitDate } : {},
    }).then((r) => r.data)
  },
  patchPresetRoute(code: string, data: { enabled?: boolean; policy_checked_at?: string }) {
    return http.patch(`/admin/preset-routes/${encodeURIComponent(code)}`, data)
      .then((r) => r.data)
  },

  // 系统运维
  getHealth() {
    return http.get<SystemHealth>('/admin/system/health')
  },
  clearCache() {
    return http.post('/admin/system/cache/clear')
  },
  health() {
    return http.get('/health')
  },
}

// ---------- 问答管理类型 ----------
export interface QaKnowledgeItem {
  id: number
  title: string
  content: string
  category: QaKnowledgeCategory
  tags: string[]
  enabled: boolean
  created_at?: string | null
  updated_at?: string | null
  [k: string]: unknown
}

export type QaKnowledgeCategory = 'faq' | 'tip' | 'policy'

export interface QaConversationItem {
  id: string
  title: string
  user_id?: number | null
  message_count?: number
  degraded_count?: number
  created_at?: string | null
  updated_at?: string | null
  [k: string]: unknown
}

export interface QaConversationDetail {
  id: string
  title: string
  messages: Array<{
    id: number
    role: string
    content: string
    refs?: Array<{ kind?: string; ref_id?: string; name?: string; [k: string]: unknown }>
    aigc?: boolean
    degraded?: boolean
    latency_ms?: number
    created_at?: string | null
  }>
  [k: string]: unknown
}

export interface QaStats {
  conversations?: number
  messages?: number
  today_questions?: number
  ai_answers?: number
  degraded_answers?: number
  degraded_rate?: number
  avg_latency_ms?: number
  knowledge_count?: number
  [k: string]: unknown
}

export interface QaModelConfig {
  provider?: string
  base_url?: string
  model?: string
  masked_key?: string
  has_key?: boolean
  thinking?: string
  timeout?: number
  max_tokens?: number
  temperature?: number
  enabled?: boolean
  [k: string]: unknown
}

export interface QaConfigTestResult {
  ok: boolean
  message?: string
  latency_ms?: number
  model?: string
  [k: string]: unknown
}
