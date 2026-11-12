<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminLogin, setSession } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function login() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  try {
    const data = await adminLogin(username.value.trim(), password.value)
    setSession(data)
    ElMessage.success(`欢迎回来，${data.display_name}`)
    router.push('/dashboard')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    error.value = typeof detail === 'string'
      ? detail
      : e?.response
        ? `登录失败(${e.response.status})`
        : '无法连接后端服务，请先启动 travel-api/run.py'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 class="brand-text" style="margin: 0 0 6px">花溪旅游 · 管理后台</h2>
      <p class="subtitle">请使用管理员账号登录</p>

      <el-form label-position="top" @submit.prevent="login">
        <el-form-item label="账号">
          <el-input
            v-model="username"
            placeholder="请输入管理员账号"
            size="large"
            autocomplete="username"
            :prefix-icon="'User'"
            @input="error = ''"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            placeholder="请输入密码"
            size="large"
            show-password
            autocomplete="current-password"
            :prefix-icon="'Lock'"
            @input="error = ''"
            @keyup.enter="login"
          />
        </el-form-item>
      </el-form>

      <p v-if="error" class="err-text">{{ error }}</p>

      <el-button
        type="primary"
        size="large"
        style="width: 100%; margin-top: 8px"
        :loading="loading"
        @click="login"
      >
        登 录
      </el-button>

      <p class="foot-hint">
        本地演示环境 · 初始账号见 README，登录后请在「系统设置」中修改密码
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #e6f2ec 0%, #f5f7f6 60%);
}
.login-card {
  width: 380px;
  padding: 14px 10px 6px;
  border-radius: 12px;
}
.subtitle { color: #909399; font-size: 13px; margin: 0 0 22px; }
.foot-hint {
  color: #a8abb2; font-size: 11px; line-height: 1.6;
  margin: 16px 0 4px; text-align: center;
}
.err-text { color: #e6533a; font-size: 12px; margin: 2px 0 8px; }
:deep(.el-form-item) { margin-bottom: 16px; }
:deep(.el-form-item__label) { padding-bottom: 4px; font-size: 13px; }
</style>
