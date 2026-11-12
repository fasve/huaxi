<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, type TagItem, type TagSynonym } from '../api'

const rows = ref<TagItem[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref()

const form = reactive({ code: '', name: '' })
const rules = {
  code: [
    { required: true, message: '请输入标签编码', trigger: 'blur' },
    { pattern: /^[a-z_][a-z0-9_]*$/, message: '只能用小写字母、数字、下划线，且以字母开头', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入标签名称', trigger: 'blur' }],
}

const maxCount = computed(() => Math.max(1, ...rows.value.map((r) => r.poi_count)))

async function load() {
  loading.value = true
  try {
    rows.value = (await api.listTags()).data.items
  } finally {
    loading.value = false
  }
}
onMounted(() => { load(); loadSynonyms() })

// ---------- A2 同义词归并 ----------
const synonyms = ref<TagSynonym[]>([])
const synVisible = ref(false)
const synForm = reactive({ alias: '', canonical_code: '', note: '' })
const mergeVisible = ref(false)
const mergeForm = reactive({ from_code: '', to_code: '' })

async function loadSynonyms() {
  synonyms.value = (await api.listTagSynonyms()).data.items
}

function openSynonym() {
  synForm.alias = ''
  synForm.canonical_code = rows.value[0]?.code || ''
  synForm.note = ''
  synVisible.value = true
}

async function saveSynonym() {
  if (!synForm.alias.trim() || !synForm.canonical_code) {
    return ElMessage.warning('请填写别名并选择标准标签')
  }
  saving.value = true
  try {
    await api.createTagSynonym({ ...synForm })
    ElMessage.success('已归并')
    synVisible.value = false
    await loadSynonyms()
  } finally {
    saving.value = false
  }
}

async function removeSynonym(row: TagSynonym) {
  await ElMessageBox.confirm(`删除别名「${row.alias}」的归并关系？`, '提示', { type: 'warning' })
  await api.deleteTagSynonym(row.id)
  ElMessage.success('已删除')
  await loadSynonyms()
}

function openMerge() {
  mergeForm.from_code = ''
  mergeForm.to_code = ''
  mergeVisible.value = true
}

async function submitMerge() {
  if (!mergeForm.from_code || !mergeForm.to_code || mergeForm.from_code === mergeForm.to_code) {
    return ElMessage.warning('请选择两个不同的标签')
  }
  await ElMessageBox.confirm(
    `将「${mergeForm.from_code}」下的资源点全部改挂到「${mergeForm.to_code}」，并登记同义词。`,
    '合并确认', { type: 'warning' },
  )
  const { data } = await api.mergeTags({ ...mergeForm })
  ElMessage.success(`已合并，迁移 ${data.moved} 条关联`)
  mergeVisible.value = false
  await Promise.all([load(), loadSynonyms()])
}

function openCreate() {
  editingId.value = null
  form.code = ''
  form.name = ''
  dialogVisible.value = true
}

function openEdit(row: TagItem) {
  editingId.value = row.id
  form.code = row.code
  form.name = row.name
  dialogVisible.value = true
}

async function submit() {
  await formRef.value?.validate()
  saving.value = true
  try {
    if (editingId.value === null) {
      await api.createTag({ code: form.code, name: form.name })
      ElMessage.success('已创建')
    } else {
      await api.updateTag(editingId.value, { code: form.code, name: form.name })
      ElMessage.success('已更新')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row: TagItem) {
  await ElMessageBox.confirm(
    `确定删除标签「${row.name}」？将同时解除 ${row.poi_count} 个资源点的关联。`,
    '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  const { data } = await api.deleteTag(row.id)
  ElMessage.success(`已删除，解除 ${data.unlinked_pois} 条关联`)
  load()
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h2>标签字典</h2>
        <span class="hint">共 {{ rows.length }} 个偏好标签 · 游客端筛选与算法偏好命中均以此为准</span>
      </div>
      <el-button type="primary" :icon="'Plus'" @click="openCreate">新增标签</el-button>
    </div>

    <div class="page-card">
      <el-alert
        type="info" :closable="false" show-icon style="margin-bottom: 16px"
        title="标签编码是算法识别的键"
        description="修改 code 会影响游客端偏好筛选与行程生成的偏好命中；仅改名称是安全的。"
      />
      <el-table :data="rows" v-loading="loading" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="编码" width="180">
          <template #default="{ row }"><code class="code">{{ row.code }}</code></template>
        </el-table-column>
        <el-table-column prop="name" label="标签名称" width="160" />
        <el-table-column label="关联资源点" min-width="220">
          <template #default="{ row }">
            <div class="bar-cell">
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: Math.max(2, row.poi_count / maxCount * 100) + '%' }"></div>
              </div>
              <b>{{ row.poi_count }}</b>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- A2 同义词归并 -->
    <div class="page-card" style="margin-top: 16px">
      <div class="page-head" style="margin-bottom: 12px">
        <div>
          <h3 style="margin: 0 0 4px; font-size: 16px">同义词归并</h3>
          <span class="hint">把用户口语 / 导入别名统一映射到标准标签，筛选与个性化偏好才能命中同一批资源。</span>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="openMerge">合并标签</el-button>
          <el-button type="primary" @click="openSynonym">新增同义词</el-button>
        </div>
      </div>
      <el-table :data="synonyms" size="small" stripe border empty-text="暂无同义词">
        <el-table-column prop="alias" label="别名" width="180" />
        <el-table-column label="归并到" min-width="220">
          <template #default="{ row }">
            <code class="code">{{ row.canonical_code }}</code>
            <span style="margin-left: 8px; color: #606266">{{ row.canonical_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180" />
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeSynonym(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增同义词 -->
    <el-dialog v-model="synVisible" title="新增同义词" width="440px">
      <el-form label-width="90px">
        <el-form-item label="别名">
          <el-input v-model="synForm.alias" placeholder="如：出片、拍照圣地" />
        </el-form-item>
        <el-form-item label="归并到">
          <el-select v-model="synForm.canonical_code" filterable style="width: 100%">
            <el-option v-for="t in rows" :key="t.code" :label="`${t.name}（${t.code}）`" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="synForm.note" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="synVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSynonym">保存</el-button>
      </template>
    </el-dialog>

    <!-- 合并标签 -->
    <el-dialog v-model="mergeVisible" title="合并标签" width="460px">
      <el-alert
        type="warning" :closable="false" show-icon style="margin-bottom: 14px"
        title="合并不可撤销"
        description="源标签下的资源点会改挂到目标标签，并自动把源 code 登记为同义词。"
      />
      <el-form label-width="90px">
        <el-form-item label="源标签">
          <el-select v-model="mergeForm.from_code" filterable style="width: 100%">
            <el-option v-for="t in rows" :key="t.code" :label="`${t.name}（${t.code}）`" :value="t.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标标签">
          <el-select v-model="mergeForm.to_code" filterable style="width: 100%">
            <el-option v-for="t in rows" :key="t.code" :label="`${t.name}（${t.code}）`" :value="t.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="danger" @click="submitMerge">确认合并</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新增标签' : '编辑标签'" width="440px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="标签编码" prop="code">
          <el-input v-model="form.code" placeholder="如：night_view" />
        </el-form-item>
        <el-form-item label="标签名称" prop="name">
          <el-input v-model="form.name" placeholder="如：夜景夜游" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 10px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; }
.hint { color: #909399; font-size: 12px; }
.code { background: #f1f4f2; padding: 2px 8px; border-radius: 5px; font-size: 12px; color: #2f7d5c; }
.bar-cell { display: flex; align-items: center; gap: 10px; }
.bar-track { flex: 1; height: 10px; background: #f1f4f2; border-radius: 999px; overflow: hidden; }
.bar-fill { height: 100%; background: #2f7d5c; border-radius: 999px; }
.bar-cell b { width: 30px; text-align: right; font-size: 13px; }
</style>
