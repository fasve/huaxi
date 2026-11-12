<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from './api'
import { currentUser, logout } from './auth'

const route = useRoute()
const router = useRouter()
const current = computed(() => route.path)
// 生产地址由构建时环境变量注入（见 deploy/env/.env.production.example）
const adminUrl = import.meta.env.VITE_ADMIN_URL || 'http://localhost:5173'
const icpNo = import.meta.env.VITE_ICP_NO || ''

async function onLogout() {
  await logout()
  toast('已退出登录')
  if (route.path === '/my' || route.path === '/login') router.push('/')
}

const navs = [
  { path: '/', label: '首页' },
  { path: '/explore', label: '发现花溪' },
  { path: '/chat', label: '问小旅' },
  { path: '/plan', label: '定制行程' },
  { path: '/personalize', label: '个性化' },
  { path: '/study', label: '游学路线' },
  { path: '/compare', label: '模式对比' },
  { path: '/my', label: '我的行程' },
]
</script>

<template>
  <div class="app-shell">
    <header class="site-header no-print">
      <div class="container header-inner">
        <router-link to="/" class="logo">
          <span class="logo-mark">🌿</span>
          <span>花溪旅行</span>
        </router-link>
        <nav class="nav">
          <router-link
            v-for="n in navs" :key="n.path" :to="n.path"
            class="nav-item" :class="{ on: current === n.path || (n.path !== '/' && current.startsWith(n.path)) }"
          >{{ n.label }}</router-link>
        </nav>
        <div class="header-actions">
          <a class="admin-link" :href="adminUrl" target="_blank" rel="noopener">管理后台 ↗</a>
          <template v-if="currentUser">
            <span class="user-chip">
              👋 {{ currentUser.nickname || currentUser.username }}
              <i v-if="currentUser.is_guest" class="guest-dot">游客</i>
            </span>
            <button class="btn btn-outline btn-sm" @click="onLogout">退出</button>
          </template>
          <router-link v-else to="/login" class="btn btn-primary btn-sm">登录 / 注册</router-link>
        </div>
      </div>
    </header>

    <main>
      <router-view />
    </main>

    <footer class="site-footer no-print">
      <div class="container footer-inner">
        <span>花溪区个性化旅游路线规划系统 · 演示数据</span>
        <span class="footer-links">
          <span>四种模式 · 智能行程生成 · PC / 小程序多端</span>
          <a href="/privacy.html" target="_blank" rel="noopener">隐私指引与服务条款</a>
          <span v-if="icpNo">{{ icpNo }}</span>
          <span v-else class="icp-todo">ICP 备案号待填写</span>
        </span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.app-shell { display: flex; flex-direction: column; min-height: 100vh; }
main { flex: 1; }
.site-header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255, 255, 255, .94);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
}
.header-inner {
  display: flex; align-items: center; gap: 28px; height: 64px;
}
.logo {
  display: flex; align-items: center; gap: 8px;
  font-size: 18px; font-weight: 700; color: var(--brand-dark);
  white-space: nowrap;
}
.logo-mark { font-size: 22px; }
.nav { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; }
.nav-item {
  padding: 7px 15px; border-radius: 999px; font-size: 14px;
  color: #5b6b64; transition: all .15s ease;
}
.nav-item:hover { background: var(--brand-light); color: var(--brand); }
.nav-item.on { background: var(--brand); color: #fff; font-weight: 600; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.admin-link {
  font-size: 13px; color: var(--muted); white-space: nowrap;
}
.admin-link:hover { color: var(--brand); }
.user-chip { font-size: 13px; white-space: nowrap; color: var(--ink); }
.guest-dot {
  font-style: normal; font-size: 11px; color: var(--muted);
  background: #f0f2f1; border-radius: 999px; padding: 1px 7px; margin-left: 4px;
}
.site-footer { border-top: 1px solid var(--line); background: #fff; margin-top: 48px; }
.footer-inner {
  display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
  padding-top: 20px; padding-bottom: 20px; color: var(--muted); font-size: 13px;
}
.footer-links { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.footer-links a { color: var(--muted); text-decoration: none; }
.footer-links a:hover { color: var(--brand); }
.icp-todo { opacity: .7; }
@media (max-width: 720px) {
  .header-inner { height: auto; padding-top: 10px; padding-bottom: 10px; gap: 10px; }
  .nav { order: 3; width: 100%; overflow-x: auto; flex-wrap: nowrap; }
  .header-actions { margin-left: auto; }
  .admin-link { display: none; }
}
</style>
