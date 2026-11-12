<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, MODE_EMOJI, toast } from '../api'
import { currentUser, loginAsGuest, requireLogin } from '../auth'

interface MyTrip {
  trip_id: string
  mode: string
  mode_name: string
  days: number
  budget: number
  total_cost: number
  score: number
  created_at: string
}

const route = useRoute()
const router = useRouter()
const trips = ref<MyTrip[]>([])
const loading = ref(true)

async function load() {
  if (!currentUser.value) {
    trips.value = []
    loading.value = false
    return
  }
  loading.value = true
  try {
    const res = await api.myTrips()
    trips.value = res.items
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(currentUser, load)

function gotoLogin() {
  requireLogin(router, route.fullPath)
}

async function guest() {
  try {
    await loginAsGuest()
    toast('已进入游客模式')
    await load()
  } catch { /* 拦截器已提示 */ }
}

async function remove(id: string) {
  if (!confirm(`确定删除行程 ${id}？该操作不可恢复。`)) return
  try {
    await api.deleteTrip(id)
    toast('已删除')
    await load()
  } catch { /* 拦截器已提示 */ }
}

function fmtTime(s: string) {
  return s ? s.replace('T', ' ').slice(0, 16) : ''
}
</script>

<template>
  <div class="container">
    <section class="section">
      <div class="section-head">
        <div>
          <h1 class="section-title">我的行程</h1>
          <div class="section-sub">已保存的行程会留在这里，可随时打开、打印或继续调整</div>
        </div>
        <router-link to="/plan" class="btn btn-primary btn-sm">＋ 新建行程</router-link>
      </div>

      <div v-if="!currentUser" class="card empty-card">
        <div class="empty-emoji">🔐</div>
        <h3>登录后查看我的行程</h3>
        <p class="muted small">注册一个账号，保存的行程会跟着账号走；也可以先用游客身份体验</p>
        <div class="auth-actions">
          <button class="btn btn-primary" @click="gotoLogin">登录 / 注册 →</button>
          <button class="btn btn-outline" @click="guest">以游客身份体验</button>
        </div>
      </div>

      <div v-else-if="loading" class="empty">加载中…</div>
      <div v-else-if="!trips.length" class="card empty-card">
        <div class="empty-emoji">🧳</div>
        <h3>还没有保存的行程</h3>
        <p class="muted small">选一个旅行模式，填好天数与预算，就能生成专属路线</p>
        <button class="btn btn-primary" @click="router.push('/plan')">去定制行程 →</button>
      </div>

      <div v-else class="grid grid-3">
        <div v-for="t in trips" :key="t.trip_id" class="card card-hover trip-card">
          <div class="trip-top">
            <span class="trip-emoji">{{ MODE_EMOJI[t.mode] || '🧭' }}</span>
            <span class="tag">已保存</span>
          </div>
          <div class="trip-name">{{ t.mode_name }} · {{ t.days }} 天</div>
          <div class="small muted">{{ fmtTime(t.created_at) }}</div>
          <div class="divider"></div>
          <div class="trip-meta">
            <div><span class="muted small">预算</span><b>¥{{ t.budget }}</b></div>
            <div><span class="muted small">预估花费</span><b class="brand-text">¥{{ t.total_cost }}</b></div>
          </div>
          <div class="trip-actions">
            <button class="btn btn-primary btn-sm" @click="router.push(`/trip/${t.trip_id}`)">查看行程</button>
            <button class="btn btn-outline btn-sm" @click="remove(t.trip_id)">删除</button>
          </div>
        </div>
      </div>

      <div class="card tip-card">
        <b>提示</b>
        <span class="small muted">
          <template v-if="currentUser && !currentUser.is_guest">
            当前账号 <b class="brand-text">{{ currentUser.username }}</b>，行程保存在本机 MySQL 的 travel 库中；退出后可用同一账号在小程序端登录查看。
          </template>
          <template v-else-if="currentUser">
            当前为匿名游客身份（服务端签发 JWT），行程不与账号绑定，换设备不会同步。
          </template>
          <template v-else>
            浏览资源与生成行程无需登录；保存行程、查看「我的行程」需要登录或选择游客模式。
          </template>
        </span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.empty-card { text-align: center; padding: 56px 24px; }
.empty-emoji { font-size: 46px; }
.empty-card h3 { margin: 12px 0 4px; }
.empty-card p { margin: 0 0 20px; }
.auth-actions { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.trip-card { display: flex; flex-direction: column; }
.trip-top { display: flex; justify-content: space-between; align-items: center; }
.trip-emoji { font-size: 30px; }
.trip-name { font-size: 18px; font-weight: 700; margin-top: 8px; }
.trip-meta { display: flex; justify-content: space-between; }
.trip-meta div { display: flex; flex-direction: column; gap: 2px; }
.trip-meta b { font-size: 17px; }
.trip-actions { display: flex; gap: 8px; margin-top: 18px; }
.tip-card { margin-top: 28px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
</style>
