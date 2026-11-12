<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { api, clearSession, getAdminInfo, type ModeConfig, type ReminderItem, type SystemHealth } from '../api'

const router = useRouter()
const health = ref<SystemHealth | null>(null)
const modes = ref<ModeConfig[]>([])
const selectedMode = ref('leisure')
const loading = ref(false)
const saving = ref(false)
const changing = ref(false)
const admin = computed(() => getAdminInfo())

// 图片源与 API Key 配置
const providers = ref<{
  name: string; display_name: string; license_type: string
  available: boolean; reason: string; requires_key: boolean
}[]>([])
const providerKeys = ref<{
  name: string; env_name: string; configured: boolean; masked: string
}[]>([])
const keyInputs = reactive<Record<string, string>>({})
const savingKey = ref('')

async function loadProviders() {
  try {
    const { data } = await api.listImageProviders()
    providers.value = data.items
    providerKeys.value = data.keys
  } catch {
    // 图片源探测失败不影响设置页其它内容
    providers.value = []
    providerKeys.value = []
  }
}

async function saveKey(name: string) {
  const value = (keyInputs[name] ?? '').trim()
  savingKey.value = name
  try {
    await api.setImageProviderKey(name, value)
    ElMessage.success(value ? '已保存，图片源立即可用' : '已清除该图片源配置')
    keyInputs[name] = ''
    await loadProviders()
  } finally {
    savingKey.value = ''
  }
}

const KEY_LABEL: Record<string, string> = {
  pixabay: 'Pixabay API Key',
  pexels: 'Pexels API Key',
}

// 修改当前管理员密码
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

async function changePassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写原密码与新密码')
    return
  }
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  changing.value = true
  try {
    await api.changePassword(pwdForm.old_password, pwdForm.new_password)
    clearSession()
    ElMessage.success('密码已修改，请重新登录')
    router.push('/login')
  } finally {
    changing.value = false
  }
}

// 可编辑的关键硬约束（其余字段原样保留）
const ruleForm = reactive({
  day_start: '09:00',
  day_end: '21:00',
  daily_poi_min: 2,
  daily_poi_max: 3,
  daily_play_hours_max: 6,
  budget_elasticity_max: 1.1,
  price_level_cap: 4,
  speed_kmh: 22,
})

const currentMode = computed(() => modes.value.find((m) => m.mode === selectedMode.value))

async function load() {
  loading.value = true
  try {
    const [h, m] = await Promise.all([api.getHealth(), api.listModes()])
    health.value = h.data
    modes.value = m.data
    syncForm()
    await loadProviders()
  } finally {
    loading.value = false
  }
}

function syncForm() {
  const r = currentMode.value?.hard_rules
  if (!r) return
  ruleForm.day_start = r.day_start ?? '09:00'
  ruleForm.day_end = r.day_end ?? '21:00'
  ruleForm.daily_poi_min = r.daily_poi_min ?? 2
  ruleForm.daily_poi_max = r.daily_poi_max ?? 3
  ruleForm.daily_play_hours_max = r.daily_play_hours_max ?? 6
  ruleForm.budget_elasticity_max = r.budget_elasticity_max ?? 1.1
  ruleForm.price_level_cap = r.price_level_cap ?? 4
  ruleForm.speed_kmh = r.speed_kmh ?? 22
}

async function saveRules() {
  const r = currentMode.value?.hard_rules
  if (!r) return
  saving.value = true
  try {
    await api.updateMode(selectedMode.value, {
      hard_rules: { ...r, ...ruleForm },
    })
    ElMessage.success('硬约束已保存并生效（配置版本 +1）')
    load()
  } finally {
    saving.value = false
  }
}

async function clearCache() {
  const { data } = await api.clearCache()
  ElMessage.success(`缓存已清空：模式 ${data.cleared_mode} 条、资源 ${data.cleared_poi} 条`)
  load()
}

// T8 出行提醒运维
const reminders = ref<ReminderItem[]>([])
const reminderCounts = ref<Record<string, number>>({})
const reminderLoading = ref(false)

const REMINDER_STATUS: Record<string, string> = {
  pending: '待发送', sent: '已发送', skipped: '已跳过', failed: '失败',
}
const REMINDER_TYPE: Record<string, string> = {
  pending: 'warning', sent: 'success', skipped: 'info', failed: 'danger',
}

async function loadReminders() {
  reminderLoading.value = true
  try {
    const { data } = await api.listReminders()
    reminders.value = data.items
    reminderCounts.value = data.counts
  } finally {
    reminderLoading.value = false
  }
}

async function runReminders() {
  reminderLoading.value = true
  try {
    const { data } = await api.runReminders()
    ElMessage.success(`${data.message}：发送 ${data.sent}，失败 ${data.failed}，跳过 ${data.skipped}`)
    await loadReminders()
  } finally {
    reminderLoading.value = false
  }
}

onMounted(() => { load(); loadReminders() })
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>系统设置</h2>
        <span class="hint">运行状态、缓存与算法硬约束 · dev 环境口径</span>
      </div>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </div>

    <!-- 账号安全 -->
    <div class="page-card">
      <h3>账号安全 <span class="hint">（当前登录：{{ admin.displayName }} / {{ admin.username }}）</span></h3>
      <el-form label-width="120px" style="max-width: 480px">
        <el-form-item label="原密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入当前密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="再输入一次新密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="changing" @click="changePassword">修改密码</el-button>
          <span class="hint" style="margin-left: 12px">修改后全部会话失效，需重新登录</span>
        </el-form-item>
      </el-form>
    </div>

    <!-- 健康检查 -->
    <div class="page-card" style="margin-top: 14px">
      <h3>运行状态</h3>
      <template v-if="health">
        <div class="health-grid">
          <div class="health-item">
            <span class="hint">服务状态</span>
            <b :class="health.status === 'ok' ? 'ok' : 'bad'">
              {{ health.status === 'ok' ? '● 正常' : '● 异常' }}
            </b>
          </div>
          <div class="health-item"><span class="hint">数据库</span><b>{{ health.database.name }} @ {{ health.database.host }}:{{ health.database.port }}</b></div>
          <div class="health-item"><span class="hint">数据表</span><b>{{ health.database.tables }} 张</b></div>
          <div class="health-item"><span class="hint">资源 / 行程</span><b>{{ health.database.poi_count }} / {{ health.database.trip_count }}</b></div>
          <div class="health-item"><span class="hint">缓存条目</span><b>模式 {{ health.cache.mode_entries }} · 资源 {{ health.cache.poi_entries }}</b></div>
          <div class="health-item">
            <span class="hint">增强开关</span>
            <b>AI 润色 {{ health.features.ai_polish ? '开' : '关' }} · 路径 API {{ health.features.route_api ? '开' : '关' }}</b>
          </div>
          <div class="health-item">
            <span class="hint">登录鉴权</span>
            <b>
              {{ health.features.auth_mode === 'real_code2session' ? '真实 code2session' : '开发 mock（禁止生产）' }}
              · JWT {{ health.features.jwt_alg || 'HS256' }} {{ health.features.jwt_expire_hours || 168 }}h
              · 密钥 {{ health.features.jwt_secret ? '已配置' : '未配置' }}
              · 微信凭据 {{ health.features.wechat_credentials ? '已配置' : '未配置' }}
            </b>
          </div>
          <div class="health-item">
            <span class="hint">天气数据源</span>
            <b>Open-Meteo（免密钥） · 15 天预报 {{ health.features.forecast_15d ? '开' : '关' }}</b>
          </div>
          <div class="health-item">
            <span class="hint">高德地名解析</span>
            <b>{{ health.features.amap_geocode ? '已配置' : '未配置（仅影响地名显示）' }}</b>
          </div>
          <div class="health-item">
            <span class="hint">图片资源</span>
            <b>
              已配图 {{ health.images?.with_images ?? 0 }} / {{ health.images?.total_pois ?? 0 }} 个资源 ·
              本地文件 {{ health.images?.files ?? 0 }} 张 ·
              授权已登记 {{ health.images?.with_meta ?? 0 }} 个
            </b>
          </div>
        </div>
        <div style="margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap">
          <el-button @click="clearCache">清空进程内缓存</el-button>
          <el-link href="http://127.0.0.1:8000/docs" target="_blank" type="primary">打开 API 文档 ↗</el-link>
          <el-link href="http://localhost:5174" target="_blank" type="primary">打开游客 PC 端 ↗</el-link>
        </div>
      </template>
    </div>

    <!-- 图片来源与授权 -->
    <div class="page-card" style="margin-top: 14px">
      <h3>图片来源与授权 <span class="hint">（联网抓取时按合规优先级自动降级）</span></h3>
      <el-table :data="providers" size="small" style="width: 100%">
        <el-table-column prop="display_name" label="图片源" min-width="180" />
        <el-table-column prop="license_type" label="授权类型" min-width="150" />
        <el-table-column label="状态" min-width="70" width="80">
          <template #default="{ row }">
            <el-tag :type="row.available ? 'success' : 'info'" size="small">
              {{ row.available ? '可用' : '不可用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="240" />
      </el-table>

      <div class="key-block">
        <h4>API Key 配置</h4>
        <p class="hint">
          Key 仅保存在服务端 <code>travel-api/.env</code>，不会下发浏览器。
          Pixabay / Pexels 的免费 key 可在各自官网注册后获取；
          维基共享资源与 Openverse 无需 key（部分网络环境下可能不可达）。
        </p>
        <div v-for="k in providerKeys" :key="k.name" class="key-row">
          <span class="key-label">{{ KEY_LABEL[k.name] || k.env_name }}</span>
          <el-input
            v-model="keyInputs[k.name]"
            :placeholder="k.configured ? `已配置（${k.masked}）` : '粘贴 API Key'"
            style="width: 320px"
          />
          <el-button
            type="primary" :loading="savingKey === k.name"
            @click="saveKey(k.name)"
          >
            {{ k.configured ? '更新' : '保存' }}
          </el-button>
          <el-button
            v-if="k.configured" :loading="savingKey === k.name"
            @click="keyInputs[k.name] = ''; saveKey(k.name)"
          >
            清除
          </el-button>
        </div>
      </div>

      <el-alert
        type="info" :closable="false" show-icon style="margin-top: 14px"
        title="合规说明"
        description="抓图会遵循目标站 robots.txt 并使用诚实 UA（不伪装浏览器）；每张图的来源与授权会登记在 poi.image_meta。Web 搜索兜底源因目标站 robots.txt 禁止抓取搜索结果页，默认关闭。"
      />
    </div>

    <!-- 硬约束 -->
    <div class="page-card" style="margin-top: 14px">
      <h3>算法硬约束 <span class="hint">（改完立即生效，无需重启服务）</span></h3>
      <div class="mode-select">
        <span class="hint">选择模式</span>
        <el-select v-model="selectedMode" style="width: 180px" @change="syncForm">
          <el-option v-for="m in modes" :key="m.mode" :label="m.mode_name" :value="m.mode" />
        </el-select>
        <el-tag v-if="currentMode" size="small">配置版本 v{{ currentMode.version }}</el-tag>
      </div>

      <el-form label-width="150px" style="max-width: 620px; margin-top: 18px">
        <el-form-item label="每日开始时间">
          <el-input v-model="ruleForm.day_start" placeholder="09:00" style="width: 140px" />
        </el-form-item>
        <el-form-item label="每日结束时间">
          <el-input v-model="ruleForm.day_end" placeholder="21:00" style="width: 140px" />
        </el-form-item>
        <el-form-item label="每日 POI 数量下限">
          <el-input-number v-model="ruleForm.daily_poi_min" :min="1" :max="10" />
          <span class="hint" style="margin-left: 12px">不足时触发分级松弛</span>
        </el-form-item>
        <el-form-item label="每日 POI 数量上限">
          <el-input-number v-model="ruleForm.daily_poi_max" :min="1" :max="12" />
        </el-form-item>
        <el-form-item label="每日游玩时长上限">
          <el-input-number v-model="ruleForm.daily_play_hours_max" :min="1" :max="14" />
          <span class="hint" style="margin-left: 12px">小时</span>
        </el-form-item>
        <el-form-item label="预算弹性上限">
          <el-input-number v-model="ruleForm.budget_elasticity_max" :min="1" :max="2" :step="0.05" :precision="2" />
          <span class="hint" style="margin-left: 12px">1.10 = 最多允许超预算 10%</span>
        </el-form-item>
        <el-form-item label="候选价格档上限">
          <el-input-number v-model="ruleForm.price_level_cap" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="交通速度">
          <el-input-number v-model="ruleForm.speed_kmh" :min="5" :max="80" />
          <span class="hint" style="margin-left: 12px">km/h，用于估算景点间耗时</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveRules">保存硬约束</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        type="warning" :closable="false" show-icon
        title="谨慎调整"
        description="硬约束直接影响行程生成结果。若把每日 POI 上限调得过低或时间窗调得过窄，可能导致大量「未达推荐下限」的松弛提示；建议配合模式配置页的权重一起调。"
      />
    </div>

    <!-- T8 出行前一日订阅提醒 -->
    <div class="page-card" style="margin-top: 14px">
      <div class="page-head" style="margin-bottom: 12px">
        <div>
          <h3 style="margin: 0 0 4px">出行提醒队列</h3>
          <span class="hint">
            开关 FEATURE_SUBSCRIBE_MSG={{ health?.features.subscribe_msg ? '开' : '关' }}，
            微信模板{{ health?.features.subscribe_configured ? '已配置' : '未配置' }}；
            未配置时提醒保持待发送，不会丢失。
          </span>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <el-tag type="warning" size="small">待发送 {{ reminderCounts.pending || 0 }}</el-tag>
          <el-tag type="success" size="small">已发送 {{ reminderCounts.sent || 0 }}</el-tag>
          <el-tag type="danger" size="small">失败 {{ reminderCounts.failed || 0 }}</el-tag>
          <el-button size="small" :loading="reminderLoading" @click="loadReminders">刷新</el-button>
          <el-button size="small" type="primary" :loading="reminderLoading" @click="runReminders">
            立即扫描
          </el-button>
        </div>
      </div>
      <el-table :data="reminders" v-loading="reminderLoading" size="small" border>
        <el-table-column prop="trip_id" label="行程" width="110" />
        <el-table-column prop="visit_date" label="出行日" width="120" />
        <el-table-column prop="remind_at" label="提醒时间（CST）" width="170" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="REMINDER_TYPE[row.status] || 'info'">
              {{ REMINDER_STATUS[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="openid" label="openid" width="130" />
        <el-table-column prop="last_error" label="最近错误" min-width="200" />
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; font-weight: 400; }
h3 { margin: 0 0 16px; font-size: 15px; }
.health-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.health-item { display: flex; flex-direction: column; gap: 3px; background: #f7f9f8; border-radius: 8px; padding: 12px 14px; }
.health-item b { font-size: 13px; }
.ok { color: #2f7d5c; }
.bad { color: #e6533a; }
.mode-select { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.key-block { margin-top: 18px; }
.key-block h4 { margin: 0 0 8px; font-size: 14px; font-weight: 500; }
.key-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.key-label { width: 150px; font-size: 13px; }
code { background: #f0f2f5; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
@media (max-width: 1000px) { .health-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
