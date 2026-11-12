import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import Dashboard from './views/Dashboard.vue'
import PoiManage from './views/PoiManage.vue'
import Trips from './views/Trips.vue'
import Tags from './views/Tags.vue'
import ModeConfig from './views/ModeConfig.vue'
import Pricing from './views/Pricing.vue'
import PresetRoutes from './views/PresetRoutes.vue'
import QaManage from './views/QaManage.vue'
import Users from './views/Users.vue'
import Settings from './views/Settings.vue'
import Login from './views/Login.vue'
import './style.css'
import { isLoggedIn } from './api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', component: Login, meta: { title: '登录' } },
    { path: '/dashboard', component: Dashboard, meta: { title: '数据概览' } },
    { path: '/pois', component: PoiManage, meta: { title: '资源管理' } },
    { path: '/trips', component: Trips, meta: { title: '行程管理' } },
    { path: '/tags', component: Tags, meta: { title: '标签字典' } },
    { path: '/modes', component: ModeConfig, meta: { title: '模式配置' } },
    { path: '/pricing', component: Pricing, meta: { title: '价格与生效规则' } },
    { path: '/preset-routes', component: PresetRoutes, meta: { title: '预设路线' } },
    { path: '/qa', component: QaManage, meta: { title: '问答管理' } },
    { path: '/users', component: Users, meta: { title: '用户管理' } },
    { path: '/settings', component: Settings, meta: { title: '系统设置' } },
  ],
})

// 未登录只能访问登录页；已登录不再停留在登录页
router.beforeEach((to) => {
  if (to.path !== '/login' && !isLoggedIn()) return { path: '/login' }
  if (to.path === '/login' && isLoggedIn()) return { path: '/dashboard' }
  return true
})

const app = createApp(App)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
for (const [name, comp] of Object.entries(Icons)) {
  app.component(name, comp as any)
}
app.mount('#app')
