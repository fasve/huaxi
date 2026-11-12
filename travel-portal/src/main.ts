import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Home from './views/Home.vue'
import Explore from './views/Explore.vue'
import Chat from './views/Chat.vue'
import Plan from './views/Plan.vue'
import Personalize from './views/Personalize.vue'
import StudyTours from './views/StudyTours.vue'
import Trip from './views/Trip.vue'
import Compare from './views/Compare.vue'
import My from './views/My.vue'
import Login from './views/Login.vue'
import { restoreSession } from './auth'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', component: Home, meta: { title: '首页' } },
    { path: '/explore', component: Explore, meta: { title: '资源浏览' } },
    { path: '/chat', component: Chat, meta: { title: '问小旅' } },
    { path: '/plan', component: Plan, meta: { title: '定制行程' } },
    { path: '/personalize', component: Personalize, meta: { title: '个性化权重' } },
    { path: '/study', component: StudyTours, meta: { title: '游学路线' } },
    { path: '/compare', component: Compare, meta: { title: '模式对比' } },
    { path: '/trip/:id', component: Trip, meta: { title: '行程详情' } },
    { path: '/my', component: My, meta: { title: '我的行程' } },
    { path: '/login', component: Login, meta: { title: '登录 / 注册' } },
  ],
})

// 先校验本地会话是否有效再挂载，避免头部身份闪一下。
// 未登录 / 后端未启动均可匿名浏览、生成行程；保存与「我的行程」需要登录。
restoreSession().finally(() => {
  createApp(App).use(router).mount('#app')
})
