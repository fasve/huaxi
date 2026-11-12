// 出行方式「整体开销」估算模型（小程序版）
//
// 与 PC 端 travel-portal/src/cost.ts 同一套口径，纯前端纯函数：
// 把每种模式拆成可逐项修改的「小部件」（住宿档位 / 餐饮标准 / 交通 / 晚间 / 每日点数 / 节奏），
// 实时算出整体开销并与预算对照，让选模式阶段就能判断预算够不够。
//
// 其中「住宿档位」「出行交通」会随 cost_prefs 回传后端，真实影响生成结果；
// 其余仅用于预估（后端仍按真实 POI 价格 + 预算硬约束生成）。

const HOTEL_TIERS = [
  { key: 'economy', label: '经济', desc: '青旅 / 快捷', per: 120 },
  { key: 'standard', label: '舒适', desc: '三钻 / 连锁', per: 260 },
  { key: 'comfort', label: '高档', desc: '四钻 / 温泉', per: 520 },
  { key: 'luxury', label: '奢华', desc: '五星 / 度假', per: 1000 },
];

const DINING_STANDARDS = [
  { key: 'light', label: '简餐', desc: '粉面 / 快餐', per: 30 },
  { key: 'feature', label: '特色', desc: '黔菜小馆', per: 60 },
  { key: 'time_honored', label: '老字号', desc: '老字号黔菜', per: 110 },
  { key: 'fine', label: '观景宴', desc: '观景 / 温泉餐', per: 220 },
];

const TRANSPORT_MODES = [
  { key: 'self_drive', label: '🚗 自驾', desc: '油费停车', per: 80 },
  { key: 'taxi', label: '🚕 打车', desc: '≤2 段打车', per: 120 },
  { key: 'transit', label: '🚌 公交', desc: '公交换乘', per: 20 },
  { key: 'walk_bike', label: '🚶 步行/骑行', desc: '古镇串联', per: 0 },
];

// slot 与后端 hard_rules.evening_slot 对齐
const EVENING_OPTIONS = [
  { key: 'rest', label: '早点休息', desc: '室内轻休闲', per: 0, slot: 'rest' },
  { key: 'night_scene', label: '夜游打卡', desc: '夜市 / 灯光', per: 40, slot: 'landmark_night' },
  { key: 'fine_dining', label: '观景晚宴', desc: '观景餐厅 / 温泉', per: 200, slot: 'dine_night' },
];

// 价格档上限 → 人均门票均价（估算）
const TICKET_BY_CAP = { 2: 25, 3: 45, 4: 80, 5: 140 };

// 各模式默认小部件（由后端 hard_rules 口径推导，与 PC 端一致）
const MODE_DEFAULTS = {
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
};

function cloneDefaults(mode) {
  const d = MODE_DEFAULTS[mode] || MODE_DEFAULTS.leisure;
  return {
    hotel: d.hotel, dining: d.dining, transport: d.transport, evening: d.evening,
    daily_poi: d.daily_poi, play_hours: d.play_hours,
    ticket_cap: d.ticket_cap, meals_per_day: d.meals_per_day,
  };
}

function perOf(list, key) {
  for (let i = 0; i < list.length; i += 1) {
    if (list[i].key === key) return list[i].per;
  }
  return 0;
}

/** 整体开销估算（与 PC cost.ts: estimateCost 同口径） */
function estimateCost(parts, days, budget) {
  const nights = Math.max(0, days - 1);
  const hotel = perOf(HOTEL_TIERS, parts.hotel) * nights;
  // 观景晚宴已含晚餐，正餐次数 -1，避免重复计费
  const diningMeals = parts.evening === 'fine_dining'
    ? Math.max(1, parts.meals_per_day - 1)
    : parts.meals_per_day;
  const dining = perOf(DINING_STANDARDS, parts.dining) * diningMeals * days;
  const ticketUnit = TICKET_BY_CAP[parts.ticket_cap];
  const tickets = (ticketUnit === undefined ? 60 : ticketUnit) * parts.daily_poi * days;
  const transport = perOf(TRANSPORT_MODES, parts.transport) * days;
  const evening = perOf(EVENING_OPTIONS, parts.evening) * days;
  const total = Math.round(hotel + dining + tickets + transport + evening);

  const usage = budget > 0 ? total / budget : 0;
  let fit = 'within';
  let statusText = '';
  let suggestion = '';
  if (usage <= 1.0) {
    fit = 'within';
    statusText = '整体开销约 ¥' + total + '，在预算内（占 ' + Math.round(usage * 100) + '%）';
    suggestion = '当前组合与预算匹配，可直接生成；生成后引擎仍会按真实价格与预算硬约束微调。';
  } else if (usage <= 1.1) {
    fit = 'slight';
    statusText = '整体开销约 ¥' + total + '，略超预算 ' + Math.round(total - budget)
      + ' 元（占 ' + Math.round(usage * 100) + '%）';
    suggestion = '该模式本身允许小幅上浮；想压回预算内可下调住宿档位或餐饮标准，或缩短天数。';
  } else {
    fit = 'over';
    statusText = '整体开销约 ¥' + total + '，超出预算 ' + Math.round(total - budget)
      + ' 元（占 ' + Math.round(usage * 100) + '%）';
    suggestion = '建议：① 降低住宿档位 / 餐饮标准；② 减少每日景点数或游玩节奏；'
      + '③ 该模式与预算差距较大时，可改选更省钱的旅行方式。引擎生成时会自动降级以尽量不超支。';
  }

  return {
    hotel: hotel, dining: dining, tickets: tickets, transport: transport, evening: evening,
    total: total, nights: nights, usage: usage, fit: fit,
    usagePercent: Math.round(usage * 100),
    statusText: statusText, suggestion: suggestion,
  };
}

/** 把「小部件」选择翻译为后端生成载荷片段（pace + cost_prefs） */
function partsToPayload(parts) {
  let hotelTier = 0;
  for (let i = 0; i < HOTEL_TIERS.length; i += 1) {
    if (HOTEL_TIERS[i].key === parts.hotel) hotelTier = i;
  }
  let eveningSlot = 'rest';
  for (let i = 0; i < EVENING_OPTIONS.length; i += 1) {
    if (EVENING_OPTIONS[i].key === parts.evening) eveningSlot = EVENING_OPTIONS[i].slot;
  }
  return {
    pace: {
      daily_poi_max: parts.daily_poi,
      play_hours_max: parts.play_hours,
      evening: eveningSlot,
    },
    cost_prefs: {
      hotel_tier: Math.max(0, hotelTier),
      transport: parts.transport,
    },
  };
}

module.exports = {
  HOTEL_TIERS,
  DINING_STANDARDS,
  TRANSPORT_MODES,
  EVENING_OPTIONS,
  MODE_DEFAULTS,
  cloneDefaults,
  estimateCost,
  partsToPayload,
};
