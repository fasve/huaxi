<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, getToken, type Poi } from '../api'

// ---------- 列表状态 ----------
const loading = ref(false)
const rows = ref<Poi[]>([])
const total = ref(0)
const query = reactive({
  category: 'all',
  keyword: '',
  visitable: 'all',
  page: 1,
  page_size: 10,
})

const CATEGORY_LABEL: Record<string, string> = {
  scenic: '景点',
  food: '美食',
  hotel: '住宿',
  leisure: '休闲',
}
const TAG_TYPE: Record<string, string> = {
  scenic: 'success',
  food: 'warning',
  hotel: 'primary',
  leisure: '',
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: query.page, page_size: query.page_size }
    if (query.category !== 'all') params.category = query.category
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.visitable !== 'all') params.visitable = query.visitable === 'on'
    const { data } = await api.listPois(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  query.page = 1
  load()
}

// ---------- 编辑弹窗 ----------
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref()

const blankForm = () => ({
  name: '',
  category: 'scenic',
  sub_type: '',
  address: '',
  longitude: 106.66,
  latitude: 26.4,
  suggest_duration_min: 60,
  ticket_price: 0,
  price_level: 1,
  rating: 4.5,
  visitable: true,
  indoor: false,
  images: [] as string[],
  image_meta: [] as {
    source: string; source_name: string; author: string; license: string; license_url: string
  }[],
})

const form = reactive(blankForm())

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  category: [{ required: true, message: '请选择类别', trigger: 'change' }],
  longitude: [{ required: true, message: '请输入经度', trigger: 'blur' }],
  latitude: [{ required: true, message: '请输入纬度', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  dialogVisible.value = true
}

function openEdit(row: Poi) {
  editingId.value = row.poi_id
  const metas = row.image_meta ?? []
  Object.assign(form, {
    ...blankForm(),
    ...row,
    indoor: (row as any).indoor ?? false,
    images: [...(row.images ?? [])],
    image_meta: (row.images ?? []).map((_, i) => ({ ...blankMeta(), ...(metas[i] ?? {}) })),
  })
  dialogVisible.value = true
}

async function submit() {
  await formRef.value?.validate()
  saving.value = true
  try {
    if (editingId.value === null) {
      await api.createPoi(form)
      ElMessage.success('新增成功')
    } else {
      await api.updatePoi(editingId.value, form)
      ElMessage.success('已保存')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

/** 缩略图角标只显示短名，避免遮挡图片主体 */
const SHORT_SOURCE: Record<string, string> = {
  wikimedia: 'Commons',
  openverse: 'Openverse',
  pixabay: 'Pixabay',
  pexels: 'Pexels',
  web: 'Web 搜索',
  upload: '本地上传',
  manual: '手动添加',
  legacy: '历史抓取',
  placeholder: '占位图',
}

function shortSource(meta?: { source: string; source_name: string }): string {
  if (!meta) return ''
  return SHORT_SOURCE[meta.source] ?? (meta.source_name || '').slice(0, 6)
}

// ---------- 图片资源 ----------
const uploading = ref(false)
const fetching = ref(false)
const imageUrlInput = ref('')
const imagePreview = ref<string[]>([])

/** 图片授权元信息，与 form.images 同序对应 */
const blankMeta = () => ({
  source: '', source_name: '', author: '', license: '', license_url: '',
})

/** 加入一张图片及其授权信息（保持 images 与 image_meta 同序） */
function pushImage(url: string, meta?: Partial<ReturnType<typeof blankMeta>>) {
  if (!url) return
  if (form.images.includes(url)) {
    ElMessage.info('该图片已存在')
    return
  }
  form.images.push(url)
  form.image_meta.push({ ...blankMeta(), ...(meta || {}) })
}

/** 上传本地图片 */
async function onUpload(file: File) {
  uploading.value = true
  try {
    const { data } = await api.uploadImage(file)
    pushImage(data.url, data.meta)
    ElMessage.success('图片已上传')
  } catch {
    ElMessage.error('图片上传失败')
  } finally {
    uploading.value = false
  }
  return false
}

/** 联网一键抓取实景图片 */
async function onFetchImages() {
  if (!form.name.trim()) {
    ElMessage.warning('请先填写资源名称，再抓取图片')
    return
  }
  fetching.value = true
  try {
    const { data } = await api.fetchImages({
      name: form.name.trim(),
      sub_type: form.sub_type,
      category: form.category,
      count: 3,
    })
    if (!data.items?.length) {
      ElMessage.warning('未获取到图片，可手动上传')
      return
    }
    let added = 0
    let srcName = ''
    data.items.forEach((it) => {
      if (!form.images.includes(it.url)) {
        form.images.push(it.url)
        form.image_meta.push({
          source: it.source || '', source_name: it.source_name || '',
          author: it.author || '', license: it.license || '',
          license_url: it.license_url || '',
        })
        if (!srcName) srcName = it.source_name || it.source
        added += 1
      }
    })
    ElMessage.success(added ? `已抓取 ${added} 张图片（来源：${srcName}）` : '图片均已存在')
  } catch {
    ElMessage.error('联网抓图失败，请稍后重试')
  } finally {
    fetching.value = false
  }
}

/** 通过 URL 添加图片（后端会本地化，避免外链失效） */
async function onAddByUrl() {
  const url = imageUrlInput.value.trim()
  if (!url) {
    ElMessage.warning('请输入图片地址')
    return
  }
  fetching.value = true
  try {
    const { data } = await api.localizeImage(url)
    pushImage(data.url, data.meta)
    imageUrlInput.value = ''
    ElMessage.success('图片已本地化保存')
  } catch {
    ElMessage.error('图片地址获取失败')
  } finally {
    fetching.value = false
  }
}

function removeImage(idx: number) {
  form.images.splice(idx, 1)
  if (form.image_meta[idx]) form.image_meta.splice(idx, 1)
}

function moveImage(idx: number, dir: -1 | 1) {
  const target = idx + dir
  if (target < 0 || target >= form.images.length) return
  const arr = form.images
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
  const metas = form.image_meta
  if (metas.length === arr.length) {
    ;[metas[idx], metas[target]] = [metas[target], metas[idx]]
  }
}

function setCover(idx: number) {
  if (idx === 0) return
  const arr = form.images
  const [item] = arr.splice(idx, 1)
  arr.unshift(item)
  const metas = form.image_meta
  if (metas.length === arr.length + 1) {
    const [m] = metas.splice(idx, 1)
    metas.unshift(m)
  }
}

function openPreview(url: string) {
  imagePreview.value = [url]
}

async function remove(row: Poi) {
  await ElMessageBox.confirm(`确定删除「${row.name}」？该操作不可恢复。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await api.deletePoi(row.poi_id)
  ElMessage.success('已删除')
  if (rows.value.length === 1 && query.page > 1) query.page -= 1
  load()
}

async function toggle(row: Poi) {
  const next = !row.visitable
  await api.toggleVisitable(row.poi_id, next)
  row.visitable = next
  ElMessage.success(next ? '已上架' : '已下架')
}

// ---------- 导入导出 ----------
const importing = ref(false)

async function onImport(file: File) {
  importing.value = true
  try {
    const { data } = await api.importFile(file)
    ElMessage.success(
      `导入完成：新增 ${data.created ?? 0}，更新 ${data.updated ?? 0}，失败 ${data.failed ?? 0}`,
    )
    load()
  } finally {
    importing.value = false
  }
  return false
}

function exportCsv() {
  // 携带会话 token 通过 fetch 下载，避免 a 标签无法带请求头
  fetch(api.exportUrl(), { headers: { Authorization: `Bearer ${getToken()}` } })
    .then((r) => {
      if (!r.ok) throw new Error(`导出失败(${r.status})`)
      return r.blob()
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `pois_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    })
    .catch(() => ElMessage.error('导出失败，请确认登录状态'))
}

const pageCount = computed(() => Math.ceil(total.value / query.page_size))
onMounted(load)
</script>

<template>
  <div class="page-card">
    <!-- 工具条 -->
    <div class="toolbar">
      <el-radio-group v-model="query.category" @change="resetAndLoad">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="scenic">景点</el-radio-button>
        <el-radio-button value="food">美食</el-radio-button>
        <el-radio-button value="hotel">住宿</el-radio-button>
        <el-radio-button value="leisure">休闲</el-radio-button>
      </el-radio-group>

      <div class="toolbar-right">
        <el-input
          v-model="query.keyword"
          placeholder="搜索名称/地址"
          clearable
          style="width: 200px"
          @keyup.enter="resetAndLoad"
          @clear="resetAndLoad"
        />
        <el-select v-model="query.visitable" style="width: 110px" @change="resetAndLoad">
          <el-option label="全部状态" value="all" />
          <el-option label="已上架" value="on" />
          <el-option label="已下架" value="off" />
        </el-select>
        <el-button type="primary" :icon="'Plus'" @click="openCreate">新增</el-button>
        <el-upload
          :show-file-list="false"
          :before-upload="(f: File) => onImport(f)"
          accept=".csv,.xlsx"
        >
          <el-button :loading="importing" :icon="'Upload'">导入</el-button>
        </el-upload>
        <el-button :icon="'Download'" @click="exportCsv">导出</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <el-table :data="rows" v-loading="loading" stripe style="width: 100%; margin-top: 12px">
      <el-table-column prop="poi_id" label="ID" width="64" />
      <el-table-column prop="name" label="名称" min-width="180">
        <template #default="{ row }">
          <div class="name-cell">
            <el-image
              v-if="row.images && row.images.length"
              :src="row.images[0]"
              fit="cover"
              class="thumb"
              :preview-src-list="row.images"
              preview-teleported
              hide-on-click-modal
            />
            <div v-else class="thumb thumb-empty">
              <el-icon><PictureFilled /></el-icon>
            </div>
            <div class="name-text">
              <span style="font-weight: 500">{{ row.name }}</span>
              <el-tag v-if="row.visitable === false" type="info" size="small" style="margin-left: 6px">
                已下架
              </el-tag>
              <div v-if="row.images && row.images.length > 1" class="img-count">
                {{ row.images.length }} 张图片
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类别" width="92">
        <template #default="{ row }">
          <el-tag :type="(TAG_TYPE[row.category] as any) || ''" size="small">
            {{ CATEGORY_LABEL[row.category] ?? row.category }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sub_type" label="子类" width="110" show-overflow-tooltip />
      <el-table-column prop="address" label="地址" min-width="160" show-overflow-tooltip />
      <el-table-column label="建议时长" width="92" align="center">
        <template #default="{ row }">{{ row.suggest_duration_min }} 分</template>
      </el-table-column>
      <el-table-column label="门票" width="82" align="right">
        <template #default="{ row }">
          {{ row.ticket_price > 0 ? `¥${row.ticket_price}` : '免费' }}
        </template>
      </el-table-column>
      <el-table-column label="评分" width="76" align="center">
        <template #default="{ row }">{{ row.rating?.toFixed(1) ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="上架" width="72" align="center">
        <template #default="{ row }">
          <el-switch :model-value="row.visitable" @change="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pager">
      <span class="hint">共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="query.page"
        :page-size="query.page_size"
        :total="total"
        layout="prev, pager, next"
        @current-change="load"
      />
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新增资源' : '编辑资源'"
      width="620px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-row :gutter="12">
          <el-col :span="16">
            <el-form-item label="名称" prop="name">
              <el-input v-model="form.name" placeholder="如：青岩古镇" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="类别" prop="category">
              <el-select v-model="form.category" style="width: 100%">
                <el-option label="景点" value="scenic" />
                <el-option label="美食" value="food" />
                <el-option label="住宿" value="hotel" />
                <el-option label="休闲" value="leisure" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="子类">
              <el-input v-model="form.sub_type" placeholder="如：古镇 / 黔菜 / 民宿" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="地址">
              <el-input v-model="form.address" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="经度" prop="longitude">
              <el-input-number v-model="form.longitude" :precision="5" :step="0.001" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="纬度" prop="latitude">
              <el-input-number v-model="form.latitude" :precision="5" :step="0.001" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="建议时长">
              <el-input-number v-model="form.suggest_duration_min" :min="0" :step="15" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="门票(元)">
              <el-input-number v-model="form.ticket_price" :min="0" :step="10" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="价格档">
              <el-input-number v-model="form.price_level" :min="1" :max="5" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="评分">
              <el-input-number v-model="form.rating" :min="0" :max="5" :step="0.1" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="室内">
              <el-switch v-model="form.indoor" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="上架">
          <el-switch v-model="form.visitable" />
          <span style="margin-left: 10px; color: #909399; font-size: 12px">
            坐标或时长缺失的资源不允许上架
          </span>
        </el-form-item>

        <!-- 图片资源 -->
        <el-form-item label="图片">
          <div class="img-panel">
            <div class="img-toolbar">
              <el-upload
                :show-file-list="false"
                :before-upload="(f: File) => onUpload(f)"
                accept="image/*"
              >
                <el-button size="small" :loading="uploading" :icon="'PictureFilled'">
                  上传本地图片
                </el-button>
              </el-upload>
              <span class="img-policy-tip">图片仅支持本地上传（联网抓取已停用）</span>
            </div>

            <div v-if="form.images.length" class="img-grid">
              <div
                v-for="(img, idx) in form.images"
                :key="img + idx"
                class="img-cell"
                :class="{ cover: idx === 0 }"
              >
                <img :src="img" :alt="form.name" @click="openPreview(img)" />
                <div class="img-mask">
                  <el-tooltip content="设为封面" placement="top">
                    <el-button link size="small" @click="setCover(idx)">封面</el-button>
                  </el-tooltip>
                  <el-tooltip content="前移" placement="top">
                    <el-button link size="small" :disabled="idx === 0" @click="moveImage(idx, -1)">
                      前移
                    </el-button>
                  </el-tooltip>
                  <el-tooltip content="后移" placement="top">
                    <el-button
                      link
                      size="small"
                      :disabled="idx === form.images.length - 1"
                      @click="moveImage(idx, 1)"
                    >
                      后移
                    </el-button>
                  </el-tooltip>
                  <el-button link size="small" type="danger" @click="removeImage(idx)">删除</el-button>
                </div>
                <span v-if="idx === 0" class="img-badge">封面</span>
                <el-tooltip
                  v-if="form.image_meta?.[idx]?.source_name"
                  placement="bottom"
                >
                  <template #content>
                    <div style="max-width: 260px; line-height: 1.7">
                      <div>来源：{{ form.image_meta[idx].source_name }}</div>
                      <div v-if="form.image_meta[idx].author">
                        作者：{{ form.image_meta[idx].author }}
                      </div>
                      <div v-if="form.image_meta[idx].license">
                        授权：{{ form.image_meta[idx].license }}
                      </div>
                    </div>
                  </template>
                  <span class="img-src">{{ shortSource(form.image_meta[idx]) }}</span>
                </el-tooltip>
              </div>
            </div>
            <div v-else class="img-empty">
              暂无图片。图片仅支持本地上传（「上传本地图片」）。
            </div>
            <p class="img-hint">
              提示：抓取到的图片会保存到后端 <code>/static/poi/</code>，避免外链失效；首张作为封面。
              每张图的来源与授权会登记在 <code>image_meta</code>，鼠标悬停缩略图可查看。
            </p>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 图片预览 -->
    <el-image-viewer
      v-if="imagePreview.length"
      :url-list="imagePreview"
      teleported
      @close="imagePreview = []"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 14px;
}
.hint {
  color: #909399;
  font-size: 13px;
}

/* ---------- 图片资源 ---------- */
.name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.thumb {
  width: 52px;
  height: 40px;
  border-radius: 6px;
  flex: none;
  background: #f2f4f7;
}
.thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  border: 1px dashed #dcdfe6;
}
.name-text {
  min-width: 0;
}
.img-count {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.img-panel {
  width: 100%;
}
.img-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.img-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  gap: 10px;
}
.img-cell {
  position: relative;
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  overflow: hidden;
  border: 2px solid transparent;
  background: #f2f4f7;
}
.img-cell.cover {
  border-color: #67c23a;
}
.img-cell img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  cursor: zoom-in;
}
.img-mask {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  opacity: 0;
  transition: opacity 0.18s;
}
.img-cell:hover .img-mask {
  opacity: 1;
}
.img-mask :deep(.el-button) {
  color: #fff;
  padding: 0 4px;
}
.img-mask :deep(.el-button--danger) {
  color: #f56c6c;
}
.img-badge {
  position: absolute;
  left: 4px;
  top: 4px;
  background: #67c23a;
  color: #fff;
  font-size: 11px;
  line-height: 1.6;
  padding: 0 6px;
  border-radius: 4px;
}
.img-src {
  position: absolute;
  right: 4px;
  bottom: 4px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  line-height: 1.6;
  padding: 0 6px;
  border-radius: 4px;
  max-width: 82%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.img-empty {
  padding: 18px;
  text-align: center;
  color: #909399;
  font-size: 13px;
  background: #f7f8fa;
  border-radius: 8px;
  border: 1px dashed #dcdfe6;
}
.img-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #a0a3ab;
}
.img-hint code {
  background: #f2f3f5;
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
