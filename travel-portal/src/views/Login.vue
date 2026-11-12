<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from '../api'
import { currentUser, login, loginAsGuest, register } from '../auth'

const route = useRoute()
const router = useRouter()
const tab = ref<'login' | 'register'>('login')
const busy = ref(false)
const error = ref('')

const account = ref('')
const password = ref('')
const regUsername = ref('')
const regNickname = ref('')
const regPhone = ref('')
const regPassword = ref('')
const regConfirm = ref('')

const redirect = () => (typeof route.query.redirect === 'string' ? route.query.redirect : '/')

onMounted(() => {
  if (currentUser.value) router.replace(redirect())
})

function switchTab(next: 'login' | 'register') {
  tab.value = next
  error.value = ''
}

async function submit() {
  error.value = ''
  if (tab.value === 'login') {
    if (!account.value.trim() || !password.value) {
      error.value = '请填写账号和密码'
      return
    }
  } else {
    if (!/^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$/.test(regUsername.value.trim())) {
      error.value = '用户名需为 2~32 位中英文、数字或下划线'
      return
    }
    if (regPassword.value.length < 6) {
      error.value = '密码至少 6 位'
      return
    }
    if (regPassword.value !== regConfirm.value) {
      error.value = '两次输入的密码不一致'
      return
    }
    if (regPhone.value.trim() && !/^1\d{10}$/.test(regPhone.value.trim())) {
      error.value = '手机号格式不正确（11 位数字）'
      return
    }
  }

  busy.value = true
  try {
    if (tab.value === 'login') {
      await login(account.value.trim(), password.value)
      toast('登录成功')
    } else {
      await register({
        username: regUsername.value.trim(),
        password: regPassword.value,
        nickname: regNickname.value.trim() || undefined,
        phone: regPhone.value.trim() || undefined,
      })
      toast('注册成功，已自动登录')
    }
    router.replace(redirect())
  } catch {
    // 后端错误由请求拦截器统一提示
  } finally {
    busy.value = false
  }
}

async function guest() {
  busy.value = true
  try {
    await loginAsGuest()
    toast('已进入游客模式')
    router.replace(redirect())
  } catch {
    // 拦截器已提示
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-wrap">
    <div class="auth-intro">
      <div class="intro-mark">🌿</div>
      <h1>把花溪，走成自己的路线</h1>
      <p class="intro-sub">一个账号，收好每一次出发</p>
      <ul class="intro-list">
        <li><span>🧭</span><div><b>四种旅行模式</b><small>休闲 / 打卡 / 深度 / 特种兵，按偏好智能排线</small></div></li>
        <li><span>💾</span><div><b>行程云端留存</b><small>登录后保存，换设备也能继续查看与调整</small></div></li>
        <li><span>🖨️</span><div><b>随时导出</b><small>打印成 PDF 或导出行程单，离线也能带走</small></div></li>
      </ul>
    </div>

    <div class="card auth-card">
      <div class="tabs">
        <button :class="{ on: tab === 'login' }" @click="switchTab('login')">登录</button>
        <button :class="{ on: tab === 'register' }" @click="switchTab('register')">注册</button>
      </div>

      <h2 class="auth-title">{{ tab === 'login' ? '欢迎回来' : '创建游客账号' }}</h2>
      <p class="muted small auth-sub">
        {{ tab === 'login' ? '使用用户名或手机号登录，继续上次的花溪行程' : '注册后自动登录，行程会保存在你的账号下' }}
      </p>

      <form @submit.prevent="submit">
        <template v-if="tab === 'login'">
          <div class="field">
            <label>用户名 / 手机号</label>
            <input v-model="account" class="input" placeholder="请输入用户名或手机号" autocomplete="username" />
          </div>
          <div class="field">
            <label>密码</label>
            <input v-model="password" class="input" type="password" placeholder="请输入密码" autocomplete="current-password" />
          </div>
        </template>
        <template v-else>
          <div class="field">
            <label>用户名 <em>*</em></label>
            <input v-model="regUsername" class="input" placeholder="2~32 位中英文、数字或下划线" autocomplete="username" />
          </div>
          <div class="field-row">
            <div class="field">
              <label>昵称（选填）</label>
              <input v-model="regNickname" class="input" placeholder="展示用昵称" />
            </div>
            <div class="field">
              <label>手机号（选填）</label>
              <input v-model="regPhone" class="input" placeholder="可用于登录" inputmode="numeric" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>密码 <em>*</em></label>
              <input v-model="regPassword" class="input" type="password" placeholder="至少 6 位" autocomplete="new-password" />
            </div>
            <div class="field">
              <label>确认密码 <em>*</em></label>
              <input v-model="regConfirm" class="input" type="password" placeholder="再输入一次" autocomplete="new-password" />
            </div>
          </div>
        </template>

        <div v-if="error" class="err-msg">{{ error }}</div>
        <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
          {{ busy ? '请稍候…' : (tab === 'login' ? '登录' : '注册并登录') }}
        </button>
      </form>

      <div class="or-line"><span>或</span></div>
      <button class="btn btn-outline btn-block" :disabled="busy" @click="guest">以游客身份先逛逛</button>
      <p class="auth-tip muted small">
        游客模式由服务端签发匿名 JWT（7 天有效），无需注册；行程仅与该设备绑定，换设备不会同步。
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  max-width: 980px; margin: 0 auto; padding: 64px 24px 32px;
  display: grid; grid-template-columns: 1fr 420px; gap: 64px; align-items: center;
  min-height: calc(100vh - 220px);
}
.intro-mark { font-size: 46px; line-height: 1; margin-bottom: 20px; }
.auth-intro h1 { font-size: 34px; margin: 0 0 8px; letter-spacing: 1px; }
.intro-sub { color: var(--brand); font-size: 16px; margin: 0 0 32px; }
.intro-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 20px; }
.intro-list li { display: flex; gap: 14px; align-items: flex-start; }
.intro-list li > span {
  width: 40px; height: 40px; flex: none; border-radius: 12px;
  background: var(--brand-light); display: grid; place-items: center; font-size: 20px;
}
.intro-list b { display: block; font-size: 15px; }
.intro-list small { display: block; color: var(--muted); font-size: 13px; margin-top: 2px; }

.auth-card { padding: 30px; }
.tabs {
  display: flex; gap: 4px; background: #f1f4f2; padding: 4px;
  border-radius: 999px; margin-bottom: 26px;
}
.tabs button {
  flex: 1; border: 0; background: transparent; border-radius: 999px;
  padding: 9px 0; font-size: 14px; font-weight: 600; color: var(--muted); cursor: pointer;
}
.tabs button.on { background: #fff; color: var(--brand); box-shadow: var(--shadow); }
.auth-title { font-size: 22px; margin: 0 0 4px; }
.auth-sub { margin: 0 0 22px; }
form { display: grid; gap: 16px; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field em { color: #c0453b; font-style: normal; }
.err-msg {
  background: #fdf0ee; color: #b74133; border-radius: 8px;
  padding: 8px 12px; font-size: 13px;
}
.btn-block { width: 100%; padding: 11px 20px; }
.or-line {
  display: flex; align-items: center; gap: 12px; color: var(--muted);
  font-size: 12px; margin: 20px 0;
}
.or-line::before, .or-line::after { content: ''; flex: 1; height: 1px; background: var(--line); }
.auth-tip { margin: 14px 0 0; line-height: 1.6; }
@media (max-width: 860px) {
  .auth-wrap { grid-template-columns: 1fr; gap: 28px; padding-top: 36px; }
  .auth-intro { display: none; }
  .auth-card { max-width: 420px; width: 100%; margin: 0 auto; }
}
</style>
