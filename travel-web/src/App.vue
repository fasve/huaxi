<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isLoggedIn, getAdminInfo, clearSession, api } from './api'

const route = useRoute()
const router = useRouter()

// 生产地址由构建时环境变量注入（见 deploy/env/.env.production.example）
const portalUrl = import.meta.env.VITE_PORTAL_URL || 'http://localhost:5174'
const isLogin = computed(() => route.path === '/login')
const active = computed(() => route.path)
const title = computed(() => (route.meta.title as string) ?? '')
// localStorage 不是响应式源：登录/退出导致路由变化时重新读取
const admin = ref(getAdminInfo())
watch(() => route.path, () => { admin.value = getAdminInfo() })

const menus = [
  { path: '/dashboard', label: '数据概览', icon: 'DataAnalysis' },
  { path: '/pois', label: '资源管理', icon: 'Location' },
  { path: '/trips', label: '行程管理', icon: 'Tickets' },
  { path: '/tags', label: '标签字典', icon: 'CollectionTag' },
  { path: '/modes', label: '模式配置', icon: 'SetUp' },
  { path: '/pricing', label: '价格与生效规则', icon: 'PriceTag' },
  { path: '/preset-routes', label: '预设路线', icon: 'Reading' },
  { path: '/qa', label: '问答管理', icon: 'ChatDotRound' },
  { path: '/users', label: '用户管理', icon: 'User' },
  { path: '/settings', label: '系统设置', icon: 'Setting' },
]

async function logout() {
  // 服务端吊销会话；失败（如已过期）也不影响本地退出
  try { await api.logout() } catch { /* noop */ }
  clearSession()
  router.push('/login')
}
</script>

<template>
  <!-- 登录页：无框架 -->
  <router-view v-if="isLogin" />

  <!-- 主布局 -->
  <el-container v-else-if="isLoggedIn()" style="height: 100vh">
    <el-aside width="200px" style="background: #fff; border-right: 1px solid #ebeef5">
      <div style="padding: 18px 20px; font-size: 16px" class="brand-text">
        花溪旅游管理后台
      </div>
      <el-menu :default-active="active" router>
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header
        style="
          display: flex; align-items: center; justify-content: space-between;
          background: #fff; border-bottom: 1px solid #ebeef5; height: 52px;
        "
      >
        <span style="font-size: 15px; font-weight: 600">{{ title }}</span>
        <div style="display: flex; align-items: center; gap: 16px">
          <a :href="portalUrl" target="_blank" rel="noopener"
             style="font-size: 13px; color: #2f7d5c; text-decoration: none">游客端 ↗</a>
          <span style="font-size: 13px; color: #606266">
            {{ admin.displayName }}<span style="color: #a8abb2">（{{ admin.username }}）</span>
          </span>
          <el-button link type="danger" @click="logout">退出登录</el-button>
        </div>
      </el-header>
      <el-main style="padding: 16px">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <!-- 未登录 -->
  <div v-else style="display: grid; place-items: center; height: 100vh">
    <el-result icon="warning" title="未登录" sub-title="请先登录管理后台">
      <template #extra>
        <el-button type="primary" @click="router.push('/login')">去登录</el-button>
      </template>
    </el-result>
  </div>
</template>
