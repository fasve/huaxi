/** 待计划篮子：跨页面收藏「想去的点位」，在行程页一键排入某一天（localStorage 持久化）。 */
export interface BasketItem {
  poi_id: number
  name: string
  category: string
  image?: string | null
  address?: string
  /** 用户在行程页选择的排入天（默认 1） */
  targetDay?: number
}

const KEY = 'travel.basket.v1'

export function getBasket(): BasketItem[] {
  try {
    const raw = localStorage.getItem(KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function save(list: BasketItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30)))
  } catch {
    /* 忽略存储失败（隐私模式等） */
  }
}

/** 加入篮子；已存在则返回 false */
export function addToBasket(item: BasketItem): boolean {
  const list = getBasket()
  if (list.some((x) => x.poi_id === item.poi_id)) return false
  list.unshift({ ...item, targetDay: 1 })
  save(list)
  return true
}

export function removeFromBasket(poiId: number): void {
  save(getBasket().filter((x) => x.poi_id !== poiId))
}

export function basketCount(): number {
  return getBasket().length
}
