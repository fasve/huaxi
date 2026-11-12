<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, normalizeWeights, type ModeConfig, type ModeVersion } from '../api'

const loading = ref(false)
const modes = ref<ModeConfig[]>([])
const editing = ref<ModeConfig | null>(null)
const saving = ref(false)

// el-dialog 的 v-model 需要 boolean：代理 editing 对象的显隐
const editingVisible = computed({
  get: () => editing.value !== null,
  set: (v: boolean) => { if (!v) editing.value = null },
})

const form = reactive({ description: '', weights: {} as Record<string, number> })

const WEIGHT_LABEL: Record<string, string> = {
  interest: '兴趣匹配', rating: '口碑评分', popularity: '热度',
  distance: '距离成本', duration: '时长适配', cost: '费用水平',
  luxury: '高端指数', photospot: '出片度', diversity: '多样性',
  budget_fit: '预算契合',
}

const RULE_LABEL: Record<string, string> = {
  daily_poi_min: '每日最少', daily_poi_max: '每日最多',
  daily_play_hours_max: '游玩时长(时)', day_start: '开始', day_end: '结束',
  budget_elasticity_max: '预算弹性', evening_slot: '晚间槽',
  hotel_price_level_min: '酒店最低档', price_level_cap: '价格档上限',
}

const weightSum = computed(() =>
  Object.entries(form.weights)
    .filter(([k]) => k !== 'budget_fit')
    .reduce((s, [, v]) => s + (Number(v) || 0), 0),
)

async function load() {
  loading.value = true
  try {
    modes.value = (await api.listModes()).data
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openEdit(m: ModeConfig) {
  editing.value = m
  form.description = m.description
  form.weights = { ...m.weights }
}

function autoNormalize() {
  form.weights = normalizeWeights(form.weights)
  ElMessage.success('权重已归一化到 1.00')
}

async function save() {
  if (!editing.value) return
  saving.value = true
  try {
    // updateMode 内部会自动归一化，避免后端 400「权重和必须为 1.0」
    await api.updateMode(editing.value.mode, {
      description: form.description,
      weights: form.weights,
    })
    ElMessage.success('已保存，缓存已刷新')
    editing.value = null
    load()
  } finally {
    saving.value = false
  }
}

// ---------- A4 版本历史 / 回滚 / 灰度 ----------
const versionVisible = ref(false)
const versionMode = ref<ModeConfig | null>(null)
const versions = ref<ModeVersion[]>([])
const versionLoading = ref(false)
const grayPct = ref(10)

const STATUS_LABEL: Record<string, string> = {
  active: '线上', history: '历史', candidate: '灰度候选',
}
const STATUS_TYPE: Record<string, string> = {
  active: 'success', history: 'info', candidate: 'warning',
}

function openVersions(m: ModeConfig) {
  versionMode.value = m
  grayPct.value = 10
  versionVisible.value = true
  loadVersions()
}

async function loadVersions() {
  if (!versionMode.value) return
  versionLoading.value = true
  try {
    versions.value = (await api.listModeVersions(versionMode.value.mode)).data.items
  } finally {
    versionLoading.value = false
  }
}

async function rollbackTo(row: ModeVersion) {
  if (!versionMode.value) return
  await ElMessageBox.confirm(
    `回滚到 v${row.version}？当前配置会先自动留档，可再次回滚。`,
    '回滚确认', { type: 'warning' },
  )
  const { data } = await api.rollbackMode(versionMode.value.mode, row.version)
  ElMessage.success(`已回滚并生效，新版本 v${data.version}`)
  await Promise.all([loadVersions(), load()])
}

async function createGray() {
  if (!versionMode.value) return
  const { data } = await api.createGray(versionMode.value.mode, {
    weights: versionMode.value.weights,
    description: versionMode.value.description,
    traffic_pct: grayPct.value,
    note: `管理端灰度 ${grayPct.value}%`,
  })
  ElMessage.success(`已创建灰度 v${data.version}（${data.traffic_pct}% 流量）`)
  await loadVersions()
}

async function promote(row: ModeVersion) {
  if (!versionMode.value) return
  await ElMessageBox.confirm(`将灰度 v${row.version} 全量发布？`, '发布确认', { type: 'warning' })
  await api.promoteGray(versionMode.value.mode, row.version)
  ElMessage.success('已全量发布')
  await Promise.all([loadVersions(), load()])
}

async function removeGray(row: ModeVersion) {
  if (!versionMode.value) return
  await ElMessageBox.confirm(`删除灰度候选 v${row.version}？`, '提示', { type: 'warning' })
  await api.deleteGray(versionMode.value.mode, row.version)
  ElMessage.success('已删除')
  await loadVersions()
}
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>模式配置</h2>
        <span class="hint">四种模式的 9 维权重与硬约束 · 「权重即配置」，改完立即生效</span>
      </div>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </div>

    <div class="mode-grid">
      <div v-for="m in modes" :key="m.mode" class="page-card mode-card">
        <div class="head">
          <div>
            <div class="title">{{ m.mode_name }}</div>
            <div class="desc">{{ m.description }}</div>
          </div>
          <div style="display: flex; gap: 10px; flex-shrink: 0">
            <el-button link @click="openVersions(m)">版本与灰度</el-button>
            <el-button link type="primary" @click="openEdit(m)">调整权重</el-button>
          </div>
        </div>

        <div class="chips">
          <div v-for="(w, k) in m.weights" :key="k" class="chip">
            <span class="chip-k">{{ WEIGHT_LABEL[k] ?? k }}</span>
            <span class="chip-v">{{ Number(w).toFixed(2) }}</span>
          </div>
        </div>

        <div class="rules">
          <template v-for="key in Object.keys(RULE_LABEL)" :key="key">
            <span v-if="m.hard_rules && m.hard_rules[key] !== undefined">
              {{ RULE_LABEL[key] }}：<b>{{ m.hard_rules[key] }}</b>
            </span>
          </template>
          <span class="hint">v{{ m.version }}</span>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="editingVisible" :title="`调整权重 · ${editing?.mode_name ?? ''}`" width="580px"
    >
      <el-alert
        type="info" :closable="false" show-icon style="margin-bottom: 16px"
        title="保存时自动归一化"
        :description="`当前静态权重和 ${weightSum.toFixed(3)}；后端要求 9 维权重和为 1.00，保存时会自动按比例调整，无需手动凑数。`"
      />
      <el-form label-width="92px">
        <el-form-item label="模式说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item v-for="(val, k) in form.weights" :key="k" :label="WEIGHT_LABEL[k] ?? k">
          <el-slider v-model="form.weights[k]" :min="0" :max="0.6" :step="0.01" show-input />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="autoNormalize">归一化到 1.00</el-button>
        <el-button @click="editingVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- A4 版本历史 / 回滚 / 灰度 -->
    <el-dialog
      v-model="versionVisible" :title="`版本与灰度 · ${versionMode?.mode_name ?? ''}`" width="760px"
    >
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px">
        <span class="hint">用当前线上权重创建灰度候选，按请求 seed 稳定分桶命中：</span>
        <el-input-number v-model="grayPct" :min="1" :max="100" />
        <span class="hint">% 流量</span>
        <el-button type="primary" size="small" @click="createGray">创建灰度</el-button>
      </div>
      <el-table :data="versions" v-loading="versionLoading" size="small" border>
        <el-table-column prop="version" label="版本" width="80" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TYPE[row.status] || 'info'">
              {{ STATUS_LABEL[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="流量" width="80" align="center">
          <template #default="{ row }">
            {{ row.status === 'candidate' ? row.traffic_pct + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="note" label="说明" min-width="150" />
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button v-if="row.status === 'candidate'" link type="success" @click="promote(row)">
              全量发布
            </el-button>
            <el-button v-if="row.status === 'candidate'" link type="danger" @click="removeGray(row)">
              删除
            </el-button>
            <el-button
              v-if="row.status !== 'candidate'"
              link type="primary" @click="rollbackTo(row)"
            >回滚到此版本</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="versionVisible = false">关闭</el-button>
        <el-button @click="loadVersions">刷新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; font-weight: 400; }
.mode-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.mode-card { padding: 18px 20px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.title { font-size: 15px; font-weight: 600; }
.desc { color: #909399; font-size: 12px; margin-top: 4px; line-height: 1.5; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 10px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: #f2f6f4; border-radius: 6px; padding: 3px 8px; font-size: 12px; }
.chip-k { color: #606266; }
.chip-v { color: #2f7d5c; font-weight: 600; }
.rules { display: flex; flex-wrap: wrap; gap: 4px 14px; color: #909399; font-size: 12px; border-top: 1px dashed #ebeef5; padding-top: 10px; }
.rules b { color: #303133; font-weight: 500; }
@media (max-width: 1100px) { .mode-grid { grid-template-columns: 1fr; } }
</style>
