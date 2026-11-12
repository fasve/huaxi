<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type UserItem } from '../api'

const rows = ref<UserItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await api.listUsers({ page: page.value, page_size: 10 })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function toggle(row: UserItem) {
  const next = row.status === 1 ? 0 : 1
  await api.toggleUser(row.id, next)
  row.status = next
  ElMessage.success(next ? '已启用' : '已禁用')
}

function fmt(s: string) {
  return s ? s.replace('T', ' ').slice(0, 16) : ''
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h2>用户管理</h2>
        <span class="hint">共 {{ total }} 位游客 · 支持账号注册与微信静默登录</span>
      </div>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </div>

    <div class="page-card">
      <el-alert
        type="info" :closable="false" show-icon style="margin-bottom: 16px"
        title="关于演示用户"
        description="游客可通过用户名/手机号注册账号，也可通过微信 wx.login 静默登录（code2session 换取 openid）；注册账号在「账号」列显示。openid 仅展示前 8 位。服务端凭据与 MOCK_LOGIN 开关可在「系统设置 → 登录鉴权」查看。"
      />
      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="OpenID" width="150">
          <template #default="{ row }"><code class="code">{{ row.openid }}</code></template>
        </el-table-column>
        <el-table-column label="账号" width="140">
          <template #default="{ row }">
            <span v-if="row.account" class="code">{{ row.account }}</span>
            <span v-else class="hint">微信 / 游客</span>
          </template>
        </el-table-column>
        <el-table-column prop="nickname" label="昵称" width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }"><el-tag size="small">{{ row.role === 'admin' ? '管理员' : '普通用户' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="trip_count" label="已存行程" width="100" align="center" />
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'" size="small">
              {{ row.status === 1 ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" width="150">
          <template #default="{ row }"><span class="hint">{{ fmt(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link :type="row.status === 1 ? 'danger' : 'primary'" @click="toggle(row)">
              {{ row.status === 1 ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="page" :page-size="10" :total="total"
                       layout="prev, pager, next" @current-change="load" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; }
.code { background: #f1f4f2; padding: 2px 8px; border-radius: 5px; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
