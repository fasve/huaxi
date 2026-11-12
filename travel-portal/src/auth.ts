/** 游客登录态：本地缓存身份 + 标准 JWT 校验 / 滑动续期（与 api.ts 的 token 读写解耦）。 */
import { ref } from 'vue'
import type { Router } from 'vue-router'
import {
  api, clearToken, getLoginKind, getToken, guestLogin as apiGuestLogin, setToken,
  type AuthResult, type AuthUser,
} from './api'

const USER_KEY = 'travel_portal_user'

export const currentUser = ref<AuthUser | null>(null)

try {
  const cached = localStorage.getItem(USER_KEY)
  currentUser.value = cached ? JSON.parse(cached) as AuthUser : null
} catch {
  currentUser.value = null
}

function cacheUser(user: AuthUser | null) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
  currentUser.value = user
}

function applySession(res: AuthResult) {
  setToken(res.token, res.expires_in, 'account')
  cacheUser(res.user)
}

/** 启动时调用：JWT 临近过期先滑动续期，有效则恢复身份，失效则静默清除。 */
export async function restoreSession(): Promise<void> {
  if (!getToken()) {
    cacheUser(null)
    return
  }
  const exp = Number(localStorage.getItem('travel_portal_token_exp') || 0)
  if (exp && exp - Date.now() < 24 * 60 * 60 * 1000) {
    try {
      const r = await api.refresh()
      setToken(r.token, r.expires_in, getLoginKind() === 'guest' ? 'guest' : 'account')
    } catch {
      // 续期失败交由下面的 me() 判定，不在此弹错
    }
  }
  const wasGuest = getLoginKind() === 'guest'
  try {
    const me = await api.me()
    cacheUser(me)
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    // 401/403 才判定登录态失效；后端暂时连不上时保留本地登录态
    if (status && status < 500) {
      clearToken()
      cacheUser(null)
      // 游客身份：token 失效时自动重登一次，用户无感
      if (wasGuest) {
        try {
          await apiGuestLogin()
          return
        } catch {
          // 重登失败保持未登录状态
        }
      }
    }
  }
}

export async function login(account: string, password: string): Promise<AuthUser> {
  const res = await api.login({ account, password })
  applySession(res)
  return res.user
}

export async function register(payload: {
  username: string; password: string; nickname?: string; phone?: string
}): Promise<AuthUser> {
  const res = await api.register(payload)
  applySession(res)
  return res.user
}

/** 游客体验：匿名 JWT 身份（不冒充微信登录），换设备不同步。 */
export async function loginAsGuest(): Promise<AuthUser> {
  const me = await apiGuestLogin()
  cacheUser(me)
  return me
}

export async function logout(): Promise<void> {
  try {
    await api.logout()
  } catch {
    // 会话已过期时也要清掉本地状态
  }
  clearToken()
  cacheUser(null)
}

/** 需要登录的操作前置校验：未登录跳登录页并带上返回地址。 */
export function requireLogin(router: Router, redirect?: string): boolean {
  if (currentUser.value) return true
  router.push({ path: '/login', query: redirect ? { redirect } : {} })
  return false
}
