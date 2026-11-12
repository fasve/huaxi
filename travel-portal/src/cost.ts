/**
 * 出行方式「整体开销」估算模型（前端纯函数）。
 *
 * 设计目标：在选择出行方式时，把每种模式拆成可逐项修改的"小部件"
 * （住宿档位 / 餐饮标准 / 出行交通 / 晚间活动 / 每日景点数 / 游玩节奏），
 * 实时算出"整体开销"并与用户预算对照，让模式选择真正"考虑整体开销"。
 *
 * 说明：本模型是生成前的**预估**，用于帮助用户在选模式阶段判断预算是否够用；
 * 实际行程仍由后端引擎按真实 POI 价格 + 预算硬约束生成（预算不足时优雅降级）。
 * 其中"住宿档位""出行交通"两项会同时回传给后端，真实影响生成结果。
 */

export type ModeKey = 'leisure' | 'blitz' | 'premium' | 'checkin'

export interface CostOption<T extends string> {
  key: T
  label: string
  desc: string
  /** 人均花费（元）：住宿=间夜价；餐饮=每餐；交通=每天；晚间=每天 */
  per: number
}

// ---------------- 小部件选项目录 ----------------

export const HOTEL_TIERS: CostOption<string>[] = [
  { key: 'economy', label: '经济', desc: '青旅 / 快捷', per: 120 },
  { key: 'standard', label: '舒适', desc: '三钻 / 连锁', per: 260 },
  { key: 'comfort', label: '高档', desc: '四钻 / 温泉', per: 520 },
  { key: 'luxury', label: '奢华', desc: '五星 / 度假', per: 1000 },
]

export const DINING_STANDARDS: CostOption<string>[] = [
  { key: 'light', label: '简餐', desc: '粉面 / 快餐', per: 30 },
  { key: 'feature', label: '特色', desc: '黔菜小馆', per: 60 },
  { key: 'time_honored', label: '老字号', desc: '老字号黔菜', per: 110 },
  { key: 'fine', label: '观景宴', desc: '观景 / 温泉餐', per: 220 },
]

export const TRANSPORT_MODES: CostOption<string>[] = [
  { key: 'self_drive', label: '🚗 自驾', desc: '油费停车', per: 80 },
  { key: 'taxi', label: '🚕 打车', desc: '≤2 段打车', per: 120 },
  { key: 'transit', label: '🚌 公交', desc: '公交换乘', per: 20 },
  { key: 'walk_bike', label: '🚶 步行/骑行', desc: '古镇串联', per: 0 },
]

export interface EveningOption extends CostOption<string> {
  slot: string // 对应 hard_rules.evening_slot
}
export const EVENING_OPTIONS: EveningOption[] = [
  { key: 'rest', label: '早点休息', desc: '室内轻休闲', per: 0, slot: 'rest' },
  { key: 'night_scene', label: '夜游打卡', desc: '夜市 / 灯光', per: 40, slot: 'landmark_night' },
  { key: 'fine_dining', label: '观景晚宴', desc: '观景餐厅 / 温泉', per: 200, slot: 'dine_night' },
]

// 价格档上限 → 人均门票均价（估算）
const TICKET_BY_CAP: Record<number, number> = { 2: 25, 3: 45, 4: 80, 5: 140 }

// ---------------- 各模式默认小部件（由后端 hard_rules 口径推导） ----------------

export interface ModeDefaults {
  hotel: string
  dining: string
  transport: string
  evening: string
  daily_poi: number // 默认每日景点数（取 min~max 的中值）
  play_hours: number // 默认每日游玩时长上限（小时）
  ticket_cap: number // 门票价格档上限
  meals_per_day: number // 正餐次数（午+晚；打卡游含小吃计为 3）
}

export const MODE_DEFAULTS: Record<ModeKey, ModeDefaults> = {
  leisure: {
    hotel: 'standard', dining: 'feature', transport: 'transit', evening: 'rest',
    daily_poi: 2, play_hours: 6, ticket_cap: 4, meals_per_day: 2,
  },
  blitz: {
    hotel: 'economy', dining: 'light', transport: 'transit', evening: 'rest',
    daily_poi: 5, play_hours: 12, ticket_cap: 3, meals_per_day: 2,
  },
  premium: {
    hotel: 'luxury', dining: 'fine', transport: 'taxi', evening: 'fine_dining',
    daily_poi: 2, play_hours: 6, ticket_cap: 5, meals_per_day: 2,
  },
  checkin: {
    hotel: 'comfort', dining: 'time_honored', transport: 'walk_bike', evening: 'night_scene',
    daily_poi: 3, play_hours: 9, ticket_cap: 4, meals_per_day: 3,
  },
}

// ---------------- 用户当前选择（小部件） ----------------

export interface CostParts {
  hotel: string
  dining: string
  transport: string
  evening: string
  daily_poi: number
  play_hours: number
  ticket_cap: number
  meals_per_day: number
}

export function defaultParts(mode: ModeKey): CostParts {
  const d = MODE_DEFAULTS[mode]
  return {
    hotel: d.hotel, dining: d.dining, transport: d.transport, evening: d.evening,
    daily_poi: d.daily_poi, play_hours: d.play_hours,
    ticket_cap: d.ticket_cap, meals_per_day: d.meals_per_day,
  }
}

// ---------------- 估算 ----------------

export interface CostBreakdown {
  hotel: number
  dining: number
  tickets: number
  transport: number
  evening: number
  total: number
  nights: number
  /** 预算贴合度（total / budget） */
  usage: number
  fit: 'within' | 'slight' | 'over'
  statusText: string
  suggestion: string
}

function optPer<T extends string>(list: CostOption<T>[], key: string): number {
  return list.find((o) => o.key === key)?.per ?? 0
}

export function estimateCost(parts: CostParts, days: number, budget: number): CostBreakdown {
  const nights = Math.max(0, days - 1)
  const hotel = optPer(HOTEL_TIERS, parts.hotel) * nights
  // 观景晚宴已含晚餐，正餐次数 -1，避免重复计费
  const diningMeals = parts.evening === 'fine_dining'
    ? Math.max(1, parts.meals_per_day - 1)
    : parts.meals_per_day
  const dining = optPer(DINING_STANDARDS, parts.dining) * diningMeals * days
  const tickets = (TICKET_BY_CAP[parts.ticket_cap] ?? 60) * parts.daily_poi * days
  const transport = optPer(TRANSPORT_MODES, parts.transport) * days
  const evening = optPer(EVENING_OPTIONS, parts.evening) * days
  const total = Math.round(hotel + dining + tickets + transport + evening)

  const usage = budget > 0 ? total / budget : 0
  let fit: CostBreakdown['fit'] = 'within'
  let statusText = ''
  let suggestion = ''
  if (usage <= 1.0) {
    fit = 'within'
    statusText = `✅ 整体开销约 ¥${total}，在预算内（占 ${Math.round(usage * 100)}%）`
    suggestion = '当前组合与预算匹配，可直接生成；生成后引擎仍会按真实价格与预算硬约束微调。'
  } else if (usage <= 1.1) {
    fit = 'slight'
    statusText = `⚠️ 整体开销约 ¥${total}，略超预算 ${Math.round(total - budget)} 元（占 ${Math.round(usage * 100)}%）`
    suggestion = '该模式本身允许小幅上浮；若想压回预算内，可下调住宿档位或餐饮标准，或缩短天数。'
  } else {
    fit = 'over'
    const over = Math.round(total - budget)
    statusText = `❌ 整体开销约 ¥${total}，超出预算 ${over} 元（占 ${Math.round(usage * 100)}%）`
    suggestion = '建议：① 降低住宿档位 / 餐饮标准；② 减少每日景点数或游玩节奏；③ 该模式与预算差距较大时，可改选更省钱的旅行方式。引擎生成时会自动降级以尽量不超支。'
  }

  return { hotel, dining, tickets, transport, evening, total, nights, usage, fit, statusText, suggestion }
}

// 把用户选择翻译为后端生成载荷片段
export function partsToPayload(parts: CostParts) {
  const hotelTier = HOTEL_TIERS.findIndex((o) => o.key === parts.hotel)
  return {
    pace: {
      daily_poi_max: parts.daily_poi,
      play_hours_max: parts.play_hours,
      evening: EVENING_OPTIONS.find((o) => o.key === parts.evening)?.slot ?? 'rest',
    },
    cost_prefs: {
      hotel_tier: Math.max(0, hotelTier),
      transport: parts.transport,
    },
  }
}
