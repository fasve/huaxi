<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const routes = ref<any[]>([])
const loading = ref(false)
const drawer = ref(false)
const detail = ref<any>(null)
const detailLoading = ref(false)
const visitDate = ref(today())
const saving = ref(false)

const GATE_NAMES: Record<string, string> = {
  weekday_only: '仅工作日', season_window: '季节窗口',
  reservation_required: '需预约', open_hours: '开放时段',
  reminder: '需预约', degraded: '已降级', replaced: '已替换', open: '正常',
}

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  try {
    const res = await api.listPresetRoutes()
    routes.value = res.items || []
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

onMounted(load)

async function loadDetail(code: string) {
  detailLoading.value = true
  try {
    const d = await api.getPresetRoute(code, visitDate.value)
    d.stops = (d.stops || []).map((s: any) => ({
      ...s,
      gateTypes: (s.date_gate || []).map((g: any) => GATE_NAMES[g.type] || g.type).join(' / ') || '—',
      gateLabel: GATE_NAMES[s.gate?.status] || s.gate?.status || '正常',
      stayText: `${s.effective_stay_min || s.stay_min} 分`,
    }))
    detail.value = d
  } catch { /* 拦截器已提示 */ } finally {
    detailLoading.value = false
  }
}

async function openDetail(row: any) {
  drawer.value = true
  await loadDetail(row.code)
}

async function onDateChange() {
  if (detail.value) await loadDetail(detail.value.code)
}

async function toggle(row: any) {
  saving.value = true
  try {
    await api.patchPresetRoute(row.code, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '线路已启用（游客端可见）' : '线路已停用（游客端不可见）')
  } catch {
    row.enabled = !row.enabled
  } finally {
    saving.value = false
  }
}

async function markChecked(row: any) {
  try {
    await api.patchPresetRoute(row.code, { policy_checked_at: today() })
    ElMessage.success('已登记本周政策校验日期')
    await load()
  } catch { /* 拦截器已提示 */ }
}
</script>

<template>
  <div>
    <el-alert
      type="info" :closable="false" show-icon style="margin-bottom: 14px"
      title="A7 · 预设路线管理"
      description="查看官方编排的站点序列、逐站讲解与研学任务卡；按季节启停线路（如花期结束），每周核验入校预约与场馆开放政策。日期闸门会根据出行日自动降级或替换站点，无需人工改行程。"
    />

    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-weight: 600">主题线路（{{ routes.length }}）</span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="routes" border stripe size="small">
        <el-table-column prop="code" label="线路 code" min-width="200" />
        <el-table-column prop="title" label="线路名称" min-width="200" />
        <el-table-column prop="theme" label="主题" width="110" />
        <el-table-column prop="target_group" label="适用人群" min-width="160" />
        <el-table-column prop="stop_count" label="站点数" width="80" align="center" />
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :loading="saving" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="待核来源" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.unverified_count" type="warning" size="small">
              {{ row.unverified_count }} 项
            </el-tag>
            <el-tag v-else type="success" size="small">全部核验</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="policy_checked_at" label="政策校验日" width="120" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">站点编排</el-button>
            <el-button link type="success" size="small" @click="markChecked(row)">标记周更校验</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" size="72%" :title="detail ? detail.title : '线路详情'">
      <template v-if="detail">
        <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 14px">
          <span style="font-size: 13px; color: #606266">日期闸门预览</span>
          <el-date-picker
            v-model="visitDate" type="date" value-format="YYYY-MM-DD"
            size="small" style="width: 170px" @change="onDateChange"
          />
          <el-tag :type="detail.day.tone === 'warn' ? 'warning' : 'success'" size="small">
            {{ detail.day.date }} · 周{{ detail.day.weekday }} · {{ detail.day.day_type }}
          </el-tag>
          <span style="font-size: 12px; color: #909399">{{ detail.day.note }}</span>
        </div>

        <el-alert
          v-if="detail.gate_notes.length" type="warning" :closable="false" show-icon
          title="本次日期的自动调整" style="margin-bottom: 14px"
        >
          <template #default>
            <div v-for="(n, i) in detail.gate_notes" :key="i" style="font-size: 12px; line-height: 1.8">· {{ n }}</div>
          </template>
        </el-alert>

        <el-descriptions :column="4" size="small" border style="margin-bottom: 16px">
          <el-descriptions-item label="主题">{{ detail.theme_name }}</el-descriptions-item>
          <el-descriptions-item label="半日时长">{{ detail.duration_hours }} 小时</el-descriptions-item>
          <el-descriptions-item label="站点总数">{{ detail.stops.length }}</el-descriptions-item>
          <el-descriptions-item label="校内步行">{{ detail.total_walk_min }} 分钟</el-descriptions-item>
          <el-descriptions-item label="适用人群">{{ detail.target_group }}</el-descriptions-item>
          <el-descriptions-item label="难度">{{ detail.difficulty }}</el-descriptions-item>
          <el-descriptions-item label="版本">v{{ detail.version }}</el-descriptions-item>
          <el-descriptions-item label="政策校验">{{ detail.policy_checked_at || '未登记' }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 6px 0 10px">站点序列（按 seq 预占槽位）</h4>
        <el-table v-loading="detailLoading" :data="detail.stops" border stripe size="small" max-height="420">
          <el-table-column prop="seq" label="序" width="52" align="center" />
          <el-table-column prop="name" label="站点" min-width="170" />
          <el-table-column prop="narration_title" label="讲解主题" min-width="150" />
          <el-table-column prop="stayText" label="停留" width="76" align="center" />
          <el-table-column prop="walk_in_min" label="步行(分)" width="82" align="center" />
          <el-table-column label="槽位" width="70" align="center">
            <template #default="{ row }">{{ row.slot === 'morning' ? '上午' : '下午' }}</template>
          </el-table-column>
          <el-table-column label="必选" width="66" align="center">
            <template #default="{ row }">
              <el-tag :type="row.must_visit ? 'success' : 'info'" size="small">
                {{ row.must_visit ? '是' : '弹性' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="gateTypes" label="日期闸门" min-width="140" />
          <el-table-column label="今日状态" width="92" align="center">
            <template #default="{ row }">
              <el-tag :type="row.gate.status === 'degraded' || row.gate.status === 'replaced' ? 'warning' : 'success'" size="small">
                {{ row.gateLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加段" width="66" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.is_addon" type="warning" size="small">深度</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
        </el-table>

        <h4 style="margin: 18px 0 10px">研学任务卡与讲解（展开查看）</h4>
        <el-collapse>
          <el-collapse-item
            v-for="s in detail.stops" :key="s.seq"
            :name="s.seq"
            :title="`${s.seq}. ${s.narration_title} · ${s.name}`"
          >
            <p style="font-size: 13px; line-height: 1.8; color: #41534a; margin: 0 0 10px">{{ s.narration_text }}</p>
            <div v-for="(t, i) in s.task_cards" :key="i" style="font-size: 12px; color: #245c42; margin-bottom: 6px">
              📝 {{ t.title }}：{{ t.content }}
            </div>
            <div v-if="s.photo_tip" style="font-size: 12px; color: #55468c">📷 {{ s.photo_tip }}</div>
            <div v-for="(n, i) in s.gate.notes" :key="i" style="font-size: 12px; color: #95591a; margin-top: 6px">
              ↳ {{ n }}
            </div>
          </el-collapse-item>
        </el-collapse>

        <h4 style="margin: 18px 0 10px">信息来源与待核字段</h4>
        <el-table :data="detail.sources" border size="small">
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.verified ? 'success' : 'warning'" size="small">
                {{ row.verified ? '已核验' : '待核准' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="item" label="事项" min-width="260" />
          <el-table-column prop="source" label="来源" min-width="200" />
          <el-table-column prop="note" label="备注" min-width="200" />
        </el-table>

        <el-alert
          type="warning" :closable="false" show-icon style="margin-top: 16px"
          title="上线前必须核准"
          description="校园通行开放时段为单源攻略口径、校园内坐标为演示近似值；入校政策变动时请在「标记周更校验」登记日期，必要时停用线路，避免游客跑到现场无法入校。"
        />
      </template>
    </el-drawer>
  </div>
</template>
