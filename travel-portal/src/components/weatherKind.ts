/** 天气类型归类与主题配色（WeatherIcon 与 WeatherCard 共用，保证图标与配色一致）。 */

export type WeatherKind =
  | 'sun' | 'moon' | 'partly' | 'overcast'
  | 'rain' | 'heavyrain' | 'thunder' | 'snow' | 'fog'

/** 按天气文案归类；night=true 时晴天显示月亮 */
export function classify(text: string, night = false): WeatherKind {
  const t = (text || '').trim()
  if (/雷/.test(t)) return 'thunder'
  if (/雪|冰雹|冻雨|霰|米雪/.test(t)) return 'snow'
  if (/雨/.test(t)) return /暴雨|大雨|特大|强/.test(t) ? 'heavyrain' : 'rain'
  if (/雾|霾|沙|尘|浮尘/.test(t)) return 'fog'
  if (/阴/.test(t)) return 'overcast'
  if (/多云|少云|晴间/.test(t)) return 'partly'
  if (/晴/.test(t)) return night ? 'moon' : 'sun'
  return night ? 'moon' : 'partly'
}

/** 每种天气对应一组主题变量（hero 渐变、强调色、图标底色） */
export const WEATHER_THEME: Record<WeatherKind, {
  hero: string
  accent: string
  chip: string
}> = {
  sun: {
    hero: 'linear-gradient(135deg, #ffb457 0%, #ff8f43 52%, #f2793c 100%)',
    accent: '#d9691f',
    chip: 'rgba(255,255,255,.22)',
  },
  moon: {
    hero: 'linear-gradient(135deg, #5b74b8 0%, #46589a 55%, #3b4a86 100%)',
    accent: '#3b4a86',
    chip: 'rgba(255,255,255,.18)',
  },
  partly: {
    hero: 'linear-gradient(135deg, #7fb4e8 0%, #5c93d6 52%, #4a7fc4 100%)',
    accent: '#3f6fae',
    chip: 'rgba(255,255,255,.2)',
  },
  overcast: {
    hero: 'linear-gradient(135deg, #8496a8 0%, #66788c 55%, #566779 100%)',
    accent: '#4d5c6b',
    chip: 'rgba(255,255,255,.18)',
  },
  rain: {
    hero: 'linear-gradient(135deg, #5b86b8 0%, #3f6a9e 55%, #345a8a 100%)',
    accent: '#33578a',
    chip: 'rgba(255,255,255,.18)',
  },
  heavyrain: {
    hero: 'linear-gradient(135deg, #416fa8 0%, #2c5386 55%, #23446e 100%)',
    accent: '#254670',
    chip: 'rgba(255,255,255,.16)',
  },
  thunder: {
    hero: 'linear-gradient(135deg, #6a6fa8 0%, #4c5088 55%, #3d4172 100%)',
    accent: '#3d4172',
    chip: 'rgba(255,255,255,.16)',
  },
  snow: {
    hero: 'linear-gradient(135deg, #9fd0e8 0%, #7cb4d6 55%, #6498bf 100%)',
    accent: '#4d80a8',
    chip: 'rgba(255,255,255,.22)',
  },
  fog: {
    hero: 'linear-gradient(135deg, #a3b0b4 0%, #869598 55%, #74858a 100%)',
    accent: '#5f7176',
    chip: 'rgba(255,255,255,.2)',
  },
}

export function themeOf(text: string, night = false) {
  const kind = classify(text, night)
  return { kind, ...WEATHER_THEME[kind] }
}
