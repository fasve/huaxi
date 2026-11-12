<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
        <div>
          <div style="font-size: 16px; font-weight: 600">价格分档规则</div>
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            按票价区间映射 price_level（1~5），套用后写入 POI 主表，规划与筛选立即生效。
          </div>
        </div>
        <div style="display: flex; gap: 8px">
          <el-select v-model="applyCategory" style="width: 130px">
            <el-option label="全部（非住宿/餐饮）" value="" />
            <el-option label="仅景点" value="scenic" />
            <el-option label="仅休闲" value="leisure" />
            <el-option label="仅游学" value="study" />
          </el-select>
          <el-button type="primary" @click="applyBands">套用到 POI</el-button>
          <el-button @click="openBand()">新增分档</el-button>
        </div>
      </div>
      <el-table :data="bands" style="margin-top: 14px" size="small" border>
        <el-table-column prop="name" label="名称" width="140" />
        <el-table-column label="价格区间（元）" width="180">
          <template #default="{ row }">{{ row.min_price }} ~ {{ row.max_price }}</template>
        </el-table-column>
        <el-table-column prop="price_level" label="价格档" width="80" align="center" />
        <el-table-column prop="description" label="说明" min-width="180" />
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBand(row)">编辑</el-button>
            <el-button link type="danger" @click="removeBand(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px">
        <div>
          <div style="font-size: 16px; font-weight: 600">生效时间规则（调价 / 开放时间）</div>
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            按日期区间覆盖票价或开放时间，到点自动生效，无需改代码。
          </div>
        </div>
        <div style="display: flex; gap: 8px">
          <el-input-number v-model="poiId" :min="1" :controls="false" placeholder="POI ID" style="width: 110px" />
          <el-button @click="loadRules">查询</el-button>
          <el-button type="primary" :disabled="!poiId" @click="openRule()">新增规则</el-button>
        </div>
      </div>
      <el-table :data="rules" style="margin-top: 14px" size="small" border empty-text="请输入 POI ID 查询">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="kind" label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'price' ? 'warning' : 'success'">
              {{ row.kind === 'price' ? '价格' : '开放时间' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="生效值" min-width="220">
          <template #default="{ row }">{{ JSON.stringify(row.value) }}</template>
        </el-table-column>
        <el-table-column label="有效期" width="200">
          <template #default="{ row }">
            {{ row.valid_from || '不限' }} ~ {{ row.valid_to || '不限' }}
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140" />
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeRule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 分档编辑 -->
    <el-dialog v-model="bandVisible" :title="bandForm.id ? '编辑分档' : '新增分档'" width="460px">
      <el-form :model="bandForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="bandForm.name" /></el-form-item>
        <el-form-item label="最低价"><el-input-number v-model="bandForm.min_price" :min="0" /></el-form-item>
        <el-form-item label="最高价"><el-input-number v-model="bandForm.max_price" :min="1" /></el-form-item>
        <el-form-item label="价格档">
          <el-input-number v-model="bandForm.price_level" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="bandForm.description" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="bandForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bandVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveBand">保存</el-button>
      </template>
    </el-dialog>

    <!-- 生效规则编辑 -->
    <el-dialog v-model="ruleVisible" title="新增生效规则" width="520px">
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="类型">
          <el-radio-group v-model="ruleForm.kind">
            <el-radio value="price">价格</el-radio>
            <el-radio value="hours">开放时间</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="生效值">
          <el-input
            v-model="ruleValueText"
            type="textarea"
            :rows="4"
            :placeholder="ruleForm.kind === 'price'
              ? '{&quot;price&quot;: 80, &quot;price_level&quot;: 3}'
              : '{&quot;open_time&quot;: [[&quot;08:00&quot;,&quot;18:00&quot;]]}'"
          />
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker v-model="ruleForm.valid_from" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-date-picker v-model="ruleForm.valid_to" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="ruleForm.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type PriceBand, type EffectiveRule } from '../api'

const bands = ref<PriceBand[]>([])
const applyCategory = ref('')
const saving = ref(false)

const bandVisible = ref(false)
const blankBand = (): PriceBand => ({
  id: 0, name: '', min_price: 0, max_price: 100,
  price_level: 1, enabled: true, description: '',
})
const bandForm = ref<PriceBand>(blankBand())

const poiId = ref<number>()
const rules = ref<EffectiveRule[]>([])
const ruleVisible = ref(false)
const ruleValueText = ref('')
const ruleForm = ref<Omit<EffectiveRule, 'id'>>({
  poi_id: 0, kind: 'price', value: {}, valid_from: '', valid_to: '', note: '', enabled: true,
})

async function loadBands() {
  bands.value = (await api.listPriceBands()).data.items
}

function openBand(row?: PriceBand) {
  bandForm.value = row ? { ...row } : blankBand()
  bandVisible.value = true
}

async function saveBand() {
  if (!bandForm.value.name.trim()) return ElMessage.warning('请填写名称')
  if (bandForm.value.min_price >= bandForm.value.max_price) {
    return ElMessage.warning('最低价必须小于最高价')
  }
  saving.value = true
  try {
    const { id, ...payload } = bandForm.value
    if (id) await api.updatePriceBand(id, payload)
    else await api.createPriceBand(payload)
    ElMessage.success('已保存')
    bandVisible.value = false
    await loadBands()
  } finally {
    saving.value = false
  }
}

async function removeBand(row: PriceBand) {
  await ElMessageBox.confirm(`删除分档「${row.name}」？`, '提示', { type: 'warning' })
  await api.deletePriceBand(row.id)
  ElMessage.success('已删除')
  await loadBands()
}

async function applyBands() {
  const { data } = await api.applyPriceBands(applyCategory.value || undefined)
  ElMessage.success(`已套用，更新 ${data.updated} 个 POI`)
}

async function loadRules() {
  if (!poiId.value) return
  rules.value = (await api.listEffectiveRules(poiId.value)).data.items
}

function openRule() {
  if (!poiId.value) return ElMessage.warning('请先填写 POI ID')
  ruleForm.value = {
    poi_id: poiId.value, kind: 'price', value: {}, valid_from: '', valid_to: '', note: '', enabled: true,
  }
  ruleValueText.value = '{"price": 80, "price_level": 3}'
  ruleVisible.value = true
}

async function saveRule() {
  let value: Record<string, any>
  try {
    value = JSON.parse(ruleValueText.value)
  } catch {
    return ElMessage.error('生效值需为合法 JSON')
  }
  saving.value = true
  try {
    await api.createEffectiveRule({ ...ruleForm.value, value })
    ElMessage.success('已创建，将在生效区间自动应用')
    ruleVisible.value = false
    await loadRules()
  } finally {
    saving.value = false
  }
}

async function removeRule(row: EffectiveRule) {
  await ElMessageBox.confirm('删除该生效规则？', '提示', { type: 'warning' })
  await api.deleteEffectiveRule(row.id)
  ElMessage.success('已删除')
  await loadRules()
}

onMounted(loadBands)
</script>
