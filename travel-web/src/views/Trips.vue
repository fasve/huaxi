<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type AdminTrip } from '../api'

const rows = ref<AdminTrip[]>([])
const total = ref(0)
const loading = ref(false)
const query = reactive({
  mode: '', status: '', keyword: '', page: 1, page_size: 10,
})
const detailVisible = ref(false)
const detail = ref<any>(null)

const MODE_OPTIONS = [
  { code: 'leisure', label: '休闲游' },
  { code: 'blitz', label: '特种兵游' },
  { code: 'premium', label: '高端游' },
  { code: 'checkin', label: '打卡游' },
]

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: query.page, page_size: query.page_size }
    if (query.mode) params.mode = query.mode
    if (query.status) params.status = query.status
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    const { data } = await api.listTrips(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function reset() {
  query.page = 1
  load()
}

async function openDetail(row: AdminTrip) {
  const { data } = await api.getTripDetail(row.trip_id)
  detail.value = data
  detailVisible.value = true
}

async function remove(row: AdminTrip) {
  await ElMessageBox.confirm(
    `确定删除行程 ${row.trip_id}（${row.mode_name} ${row.days} 天）？该操作不可恢复。`,
    '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await api.deleteTrip(row.trip_id)
  ElMessage.success('已删除')
  if (rows.value.length === 1 && query.page > 1) query.page--
  load()
}

function fmt(s: string) {
  return s ? s.replace('T', ' ').slice(0, 16) : ''
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h2>行程管理</h2>
        <span class="hint">系统内所有生成的行程记录（含匿名草稿），共 {{ total }} 条</span>
      </div>
      <div class="filters">
        <el-select v-model="query.mode" placeholder="全部模式" clearable style="width: 130px" @change="reset">
          <el-option v-for="m in MODE_OPTIONS" :key="m.code" :label="m.label" :value="m.code" />
        </el-select>
        <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px" @change="reset">
          <el-option label="已保存" value="saved" />
          <el-option label="草稿" value="draft" />
        </el-select>
        <el-input v-model="query.keyword" placeholder="行程编号" clearable
                  style="width: 170px" @keyup.enter="reset" @clear="reset" />
        <el-button type="primary" @click="reset">查询</el-button>
      </div>
    </div>

    <div class="page-card">
      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="trip_id" label="行程编号" width="120" />
        <el-table-column label="模式" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.mode_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="days" label="天数" width="70" align="center" />
        <el-table-column label="预算" width="100" align="right">
          <template #default="{ row }">¥{{ row.budget }}</template>
        </el-table-column>
        <el-table-column label="预估花费" width="110" align="right">
          <template #default="{ row }"><b style="color: #e6803a">¥{{ row.total_cost }}</b></template>
        </el-table-column>
        <el-table-column prop="poi_count" label="行程点" width="80" align="center" />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'saved' ? 'success' : 'info'" size="small">
              {{ row.status === 'saved' ? '已保存' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="生成时间" width="150">
          <template #default="{ row }"><span class="hint">{{ fmt(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page" :page-size="query.page_size" :total="total"
          layout="prev, pager, next" @current-change="load"
        />
      </div>
    </div>

    <!-- 行程详情 -->
    <el-dialog v-model="detailVisible" title="行程详情" width="700px">
      <template v-if="detail">
        <div class="detail-head">
          <span><b>{{ detail.mode_name }}</b> · {{ detail.days }} 天</span>
          <span>预算 ¥{{ detail.budget }} ｜ 花费 <b style="color: #e6803a">¥{{ detail.total_cost }}</b></span>
          <span v-if="detail.hotel">住宿 {{ detail.hotel.name }} × {{ detail.hotel_nights }} 晚</span>
        </div>
        <div v-for="d in detail.days_plan" :key="d.day_index" class="detail-day">
          <div class="day-title">Day {{ d.day_index }} · {{ d.theme }}（¥{{ d.day_cost }}）</div>
          <div v-for="(it, i) in d.items" :key="i" class="detail-item">
            <span class="time">{{ it.start_time }}</span>
            <el-tag size="small" type="info">{{ it.slot_name }}</el-tag>
            <span class="item-name">{{ it.name }}</span>
            <span class="hint">{{ it.duration_min }} 分 · {{ it.cost > 0 ? '¥' + it.cost : '免费' }}</span>
          </div>
        </div>
        <div v-if="detail.relax_log?.length" class="relax">
          <div v-for="(r, i) in detail.relax_log" :key="i" class="hint">· {{ r.label }}</div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.detail-head { display: flex; gap: 20px; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid #ebeef5; font-size: 13px; }
.detail-day { margin-top: 14px; }
.day-title { font-weight: 600; margin-bottom: 6px; }
.detail-item { display: flex; align-items: center; gap: 10px; padding: 5px 0; font-size: 13px; }
.time { width: 48px; color: #909399; }
.item-name { flex: 1; }
.relax { margin-top: 14px; background: #fffaf0; padding: 10px 14px; border-radius: 8px; }
</style>
