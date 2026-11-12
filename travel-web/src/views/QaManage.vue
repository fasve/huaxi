<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import {
  api,
  type QaConfigTestResult,
  type QaConversationDetail,
  type QaConversationItem,
  type QaKnowledgeCategory,
  type QaKnowledgeItem,
  type QaModelConfig,
  type QaStats,
} from '../api'

const tab = ref('knowledge')

// ==================== ① 知识库 ====================
const CATEGORY_LABEL: Record<string, string> = { faq: 'FAQ', tip: '运营贴士', policy: '政策口径' }
const CATEGORY_TAG: Record<string, string> = { faq: '', tip: 'success', policy: 'warning' }

const kbLoading = ref(false)
const kbRows = ref<QaKnowledgeItem[]>([])
const kbTotal = ref(0)
const kbQuery = reactive({ keyword: '', category: '', enabled: '', page: 1, page_size: 10 })

async function loadKnowledge() {
  kbLoading.value = true
  try {
    const params: Record<string, unknown> = { page: kbQuery.page, page_size: kbQuery.page_size }
    if (kbQuery.keyword.trim()) params.keyword = kbQuery.keyword.trim()
    if (kbQuery.category) params.category = kbQuery.category
    if (kbQuery.enabled !== '') params.enabled = kbQuery.enabled === 'on'
    const { data } = await api.listQaKnowledge(params)
    kbRows.value = data.items
    kbTotal.value = data.total
  } finally {
    kbLoading.value = false
  }
}

function resetKbQuery() {
  kbQuery.keyword = ''
  kbQuery.category = ''
  kbQuery.enabled = ''
  kbQuery.page = 1
  loadKnowledge()
}

// 编辑弹窗
const kbDialog = ref(false)
const kbSaving = ref(false)
const kbEditingId = ref<number | null>(null)
const kbFormRef = ref<FormInstance>()
const blankKb = (): {
  title: string
  content: string
  category: QaKnowledgeCategory
  tagsText: string
  enabled: boolean
} => ({ title: '', content: '', category: 'faq', tagsText: '', enabled: true })
const kbForm = reactive(blankKb())
const kbRules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }],
}

function openKbCreate() {
  kbEditingId.value = null
  Object.assign(kbForm, blankKb())
  kbDialog.value = true
}

function openKbEdit(row: QaKnowledgeItem) {
  kbEditingId.value = row.id
  Object.assign(kbForm, {
    title: row.title,
    content: row.content,
    category: row.category,
    tagsText: (row.tags || []).join('，'),
    enabled: row.enabled,
  })
  kbDialog.value = true
}

async function submitKb() {
  await kbFormRef.value?.validate()
  kbSaving.value = true
  try {
    const payload = {
      title: kbForm.title.trim(),
      content: kbForm.content.trim(),
      category: kbForm.category,
      tags: kbForm.tagsText.split(/[,，;；\s]+/).map((t) => t.trim()).filter(Boolean),
      enabled: kbForm.enabled,
    }
    if (kbEditingId.value === null) {
      await api.createQaKnowledge(payload)
      ElMessage.success('已新增知识条目，问答即时生效')
    } else {
      await api.updateQaKnowledge(kbEditingId.value, payload)
      ElMessage.success('已保存，问答即时生效')
    }
    kbDialog.value = false
    loadKnowledge()
  } finally {
    kbSaving.value = false
  }
}

async function removeKb(row: QaKnowledgeItem) {
  await ElMessageBox.confirm(`确定删除「${row.title}」？删除后游客端问答不再引用该条资料。`, '删除知识条目', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
  await api.deleteQaKnowledge(row.id)
  ElMessage.success('已删除')
  loadKnowledge()
}

async function toggleKbEnabled(row: QaKnowledgeItem, value: boolean) {
  try {
    await api.updateQaKnowledge(row.id, { enabled: value })
    ElMessage.success(value ? '已启用' : '已停用')
  } finally {
    loadKnowledge()
  }
}

// ==================== ② 对话审计 ====================
const stats = ref<QaStats | null>(null)
const auditLoading = ref(false)
const auditRows = ref<QaConversationItem[]>([])
const auditTotal = ref(0)
const auditQuery = reactive({ keyword: '', only_degraded: false, page: 1, page_size: 10 })

async function loadStats() {
  const { data } = await api.getQaStats()
  stats.value = data
}

async function loadAudit() {
  auditLoading.value = true
  try {
    const params: Record<string, unknown> = { page: auditQuery.page, page_size: auditQuery.page_size }
    if (auditQuery.keyword.trim()) params.keyword = auditQuery.keyword.trim()
    if (auditQuery.only_degraded) params.only_degraded = true
    const { data } = await api.listQaConversations(params)
    auditRows.value = data.items
    auditTotal.value = data.total
  } finally {
    auditLoading.value = false
  }
}

function resetAuditQuery() {
  auditQuery.keyword = ''
  auditQuery.only_degraded = false
  auditQuery.page = 1
  loadAudit()
}

const auditDrawer = ref(false)
const auditDetail = ref<QaConversationDetail | null>(null)
const auditDetailLoading = ref(false)

async function openAudit(row: QaConversationItem) {
  auditDrawer.value = true
  auditDetailLoading.value = true
  auditDetail.value = null
  try {
    const { data } = await api.getQaConversation(row.id)
    auditDetail.value = data
  } finally {
    auditDetailLoading.value = false
  }
}

async function removeAudit(row: QaConversationItem) {
  await ElMessageBox.confirm(`确定删除会话「${row.title}」及其全部消息？`, '删除会话', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  })
  await api.deleteQaConversation(row.id)
  ElMessage.success('已删除')
  auditDrawer.value = false
  loadAudit()
  loadStats()
}

// ==================== ③ 模型配置 ====================
const cfgLoading = ref(false)
const cfgSaving = ref(false)
const cfgTesting = ref(false)
const cfgMeta = ref<QaModelConfig | null>(null)
const cfgTest = ref<QaConfigTestResult | null>(null)
const cfgForm = reactive({
  enabled: true,
  base_url: '',
  model: '',
  thinking: 'auto',
  api_key: '',
  timeout: 45,
  max_tokens: 800,
  temperature: 0.3,
  daily_limit: 300,
  anon_daily_limit: 50,
})

async function loadConfig() {
  cfgLoading.value = true
  try {
    const { data } = await api.getQaConfig()
    cfgMeta.value = data
    Object.assign(cfgForm, {
      enabled: data.enabled,
      base_url: data.base_url,
      model: data.model,
      thinking: data.thinking || 'auto',
      api_key: '',
      timeout: data.timeout,
      max_tokens: data.max_tokens,
      temperature: data.temperature,
      daily_limit: data.daily_limit,
      anon_daily_limit: data.anon_daily_limit,
    })
  } finally {
    cfgLoading.value = false
  }
}

async function saveConfig() {
  if (!cfgForm.base_url.trim() || !cfgForm.model.trim()) {
    ElMessage.warning('Base URL 与模型名不能为空')
    return
  }
  cfgSaving.value = true
  try {
    const { data } = await api.updateQaConfig({
      enabled: cfgForm.enabled,
      base_url: cfgForm.base_url.trim(),
      model: cfgForm.model.trim(),
      thinking: cfgForm.thinking,
      api_key: cfgForm.api_key.trim(),   // 留空 = 保持原 Key
      timeout: cfgForm.timeout,
      max_tokens: cfgForm.max_tokens,
      temperature: cfgForm.temperature,
      daily_limit: cfgForm.daily_limit,
      anon_daily_limit: cfgForm.anon_daily_limit,
    })
    cfgMeta.value = data
    cfgForm.api_key = ''
    ElMessage.success('已保存并热生效（无需重启后端）')
  } finally {
    cfgSaving.value = false
  }
}

async function testConfig() {
  cfgTesting.value = true
  cfgTest.value = null
  try {
    const { data } = await api.testQaConfig()
    cfgTest.value = data
    if (data.ok) ElMessage.success(`连接正常（${data.latency_ms} ms）`)
    else ElMessage.error(`连接失败：${data.message}`)
  } finally {
    cfgTesting.value = false
  }
}

onMounted(() => {
  loadKnowledge()
  loadStats()
  loadAudit()
  loadConfig()
})
</script>

<template>
  <el-tabs v-model="tab" type="border-card">
    <!-- ==================== 知识库 ==================== -->
    <el-tab-pane label="知识库" name="knowledge">
      <el-alert
        type="info" :closable="false" show-icon
        title="FAQ / 运营贴士 / 政策口径。POI 知识卡由资源库自动生成，这里维护的是「模型不知道、但必须答对」的补充资料。保存后游客端问答立即生效（缓存已自动失效）。"
        style="margin-bottom: 12px"
      />

      <div class="toolbar">
        <el-input
          v-model="kbQuery.keyword" placeholder="搜索标题或内容" clearable
          style="width: 240px" @keyup.enter="kbQuery.page = 1; loadKnowledge()"
        />
        <el-select v-model="kbQuery.category" placeholder="全部分类" clearable style="width: 140px">
          <el-option label="FAQ" value="faq" />
          <el-option label="运营贴士" value="tip" />
          <el-option label="政策口径" value="policy" />
        </el-select>
        <el-select v-model="kbQuery.enabled" placeholder="全部状态" clearable style="width: 130px">
          <el-option label="已启用" value="on" />
          <el-option label="已停用" value="off" />
        </el-select>
        <el-button type="primary" @click="kbQuery.page = 1; loadKnowledge()">查询</el-button>
        <el-button @click="resetKbQuery">重置</el-button>
        <div class="spacer" />
        <el-button type="primary" plain @click="openKbCreate">＋ 新增知识条目</el-button>
      </div>

      <el-table v-loading="kbLoading" :data="kbRows" border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="分类" width="100">
          <template #default="{ row }">
            <el-tag :type="CATEGORY_TAG[row.category] || ''" size="small">
              {{ CATEGORY_LABEL[row.category] || row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" type="info" style="margin-right: 4px">{{ t }}</el-tag>
            <span v-if="!row.tags?.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled" size="small"
              @change="(v: boolean) => toggleKbEnabled(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="150" />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openKbEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeKb(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="kbQuery.page" v-model:page-size="kbQuery.page_size"
        :total="kbTotal" layout="total, prev, pager, next" style="margin-top: 12px"
        @current-change="loadKnowledge"
      />

      <el-dialog v-model="kbDialog" :title="kbEditingId === null ? '新增知识条目' : '编辑知识条目'" width="720px">
        <el-form ref="kbFormRef" :model="kbForm" :rules="kbRules" label-width="80px">
          <el-form-item label="标题" prop="title">
            <el-input v-model="kbForm.title" maxlength="64" show-word-limit placeholder="如：青岩古镇停车提示" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="kbForm.category" style="width: 200px">
              <el-option label="FAQ（常见问题）" value="faq" />
              <el-option label="运营贴士（tip）" value="tip" />
              <el-option label="政策口径（policy）" value="policy" />
            </el-select>
          </el-form-item>
          <el-form-item label="标签">
            <el-input v-model="kbForm.tagsText" placeholder="逗号分隔，如：交通，停车，避坑" />
          </el-form-item>
          <el-form-item label="内容" prop="content">
            <el-input
              v-model="kbForm.content" type="textarea" :rows="7" maxlength="5000" show-word-limit
              placeholder="给模型看的事实性资料。只写确定的信息，避免绝对化承诺。"
            />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="kbForm.enabled" />
            <span class="hint">停用后该条不再参与检索</span>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="kbDialog = false">取消</el-button>
          <el-button type="primary" :loading="kbSaving" @click="submitKb">保存</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <!-- ==================== 对话审计 ==================== -->
    <el-tab-pane label="对话审计" name="audit">
      <el-row :gutter="10" style="margin-bottom: 12px">
        <el-col :span="3" v-for="c in [
          { label: '会话数', value: stats?.conversations ?? 0 },
          { label: '提问数', value: stats?.questions ?? 0 },
          { label: '今日提问', value: stats?.today_questions ?? 0 },
          { label: 'AI 回答', value: stats?.aigc ?? 0 },
          { label: '降级回答', value: stats?.degraded ?? 0 },
          { label: '降级率', value: ((stats?.degraded_rate ?? 0) * 100).toFixed(1) + '%' },
          { label: '平均时延', value: (stats?.avg_latency_ms ?? 0) + ' ms' },
          { label: '知识条目', value: (stats?.knowledge_enabled ?? 0) + '/' + (stats?.knowledge_total ?? 0) },
        ]" :key="c.label">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value">{{ c.value }}</div>
            <div class="stat-label">{{ c.label }}</div>
          </el-card>
        </el-col>
      </el-row>

      <div class="toolbar">
        <el-input
          v-model="auditQuery.keyword" placeholder="搜索会话标题" clearable style="width: 220px"
          @keyup.enter="auditQuery.page = 1; loadAudit()"
        />
        <el-checkbox v-model="auditQuery.only_degraded" @change="auditQuery.page = 1; loadAudit()">
          只看有降级的会话
        </el-checkbox>
        <el-button type="primary" @click="auditQuery.page = 1; loadAudit()">查询</el-button>
        <el-button @click="resetAuditQuery">重置</el-button>
        <div class="spacer" />
        <el-button @click="loadStats(); loadAudit()">刷新</el-button>
      </div>

      <el-table v-loading="auditLoading" :data="auditRows" border size="small">
        <el-table-column prop="id" label="会话 ID" width="150" />
        <el-table-column prop="title" label="标题（首问）" min-width="220" show-overflow-tooltip />
        <el-table-column label="用户" width="110">
          <template #default="{ row }">
            <span v-if="row.is_anonymous" class="muted">匿名</span>
            <span v-else>uid {{ row.user_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="message_count" label="消息数" width="80" />
        <el-table-column label="降级" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.degraded_count > 0" type="warning" size="small">{{ row.degraded_count }}</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="最近更新" width="150" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openAudit(row)">查看</el-button>
            <el-button link type="danger" @click="removeAudit(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="auditQuery.page" v-model:page-size="auditQuery.page_size"
        :total="auditTotal" layout="total, prev, pager, next" style="margin-top: 12px"
        @current-change="loadAudit"
      />

      <el-drawer v-model="auditDrawer" title="会话详情" size="46%">
        <div v-loading="auditDetailLoading">
          <template v-if="auditDetail">
            <el-descriptions :column="2" border size="small" style="margin-bottom: 14px">
              <el-descriptions-item label="会话 ID">{{ auditDetail.id }}</el-descriptions-item>
              <el-descriptions-item label="用户">
                {{ auditDetail.is_anonymous ? '匿名' : 'uid ' + auditDetail.user_id }}
              </el-descriptions-item>
              <el-descriptions-item label="标题">{{ auditDetail.title }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ auditDetail.updated_at }}</el-descriptions-item>
            </el-descriptions>

            <div v-for="m in auditDetail.messages" :key="m.id" class="audit-msg" :class="m.role">
              <div class="audit-msg-head">
                <el-tag size="small" :type="m.role === 'user' ? 'info' : 'success'">
                  {{ m.role === 'user' ? '游客' : 'AI' }}
                </el-tag>
                <span class="muted small">{{ m.created_at }}</span>
                <template v-if="m.role === 'assistant'">
                  <el-tag v-if="m.aigc" size="small" type="success" effect="plain">AIGC</el-tag>
                  <el-tag v-if="m.degraded" size="small" type="warning" effect="plain">降级</el-tag>
                  <span class="muted small">{{ m.latency_ms }} ms</span>
                </template>
              </div>
              <div class="audit-msg-body">{{ m.content }}</div>
              <div v-if="m.refs?.length" class="audit-refs">
                <el-tag v-for="r in m.refs" :key="r.ref_id" size="small" effect="plain" type="info" style="margin-right: 4px">
                  {{ (r.kind || '').toUpperCase() }} · {{ r.name }}
                </el-tag>
              </div>
            </div>
          </template>
        </div>
      </el-drawer>
    </el-tab-pane>

    <!-- ==================== 模型配置 ==================== -->
    <el-tab-pane label="模型配置" name="config">
      <el-alert
        type="success" :closable="false" show-icon
        title="保存后立即生效（无需重启后端），并写回 travel-api/.env 持久化。API Key 只存服务端，页面只显示掩码；留空表示保持原 Key 不变。"
        style="margin-bottom: 14px"
      />

      <el-card shadow="never" style="max-width: 860px">
        <el-form v-loading="cfgLoading" label-width="150px">
          <el-form-item label="启用问答模块">
            <el-switch v-model="cfgForm.enabled" />
            <span class="hint">关闭后 /api/v1/qa/* 返回 503，游客端显示「暂未启用」</span>
          </el-form-item>
          <el-form-item label="Base URL">
            <el-input v-model="cfgForm.base_url" placeholder="https://api.deepseek.com/v1" />
            <div class="hint">
              OpenAI 兼容协议：通义 https://dashscope.aliyuncs.com/compatible-mode/v1 ·
              智谱 https://open.bigmodel.cn/api/paas/v4 · 本机 Ollama http://127.0.0.1:11434/v1
            </div>
          </el-form-item>
          <el-form-item label="模型名">
            <el-input v-model="cfgForm.model" placeholder="deepseek-flash / deepseek-v4-pro / qwen-plus" />
          </el-form-item>
          <el-form-item label="思考模式">
            <el-select v-model="cfgForm.thinking" style="width: 200px">
              <el-option label="自动（auto）" value="auto" />
              <el-option label="关闭（off）" value="off" />
              <el-option label="开启（on）" value="on" />
            </el-select>
            <div class="hint">
              auto：仅当 Base URL 含 deepseek.com 时自动关闭思考，其他 provider 不下发该参数；
              问答/意图解析建议「关闭」，响应更快更省 token；开启后更慢，且思考模式会忽略 temperature。
            </div>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="cfgForm.api_key" type="password" show-password
              :placeholder="cfgMeta?.api_key_configured ? `已配置：${cfgMeta.api_key_masked}（留空不修改）` : '尚未配置，请填写'"
            />
            <div class="hint">只写入服务端 .env，任何接口都不会回传明文</div>
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="cfgForm.timeout" :min="5" :max="300" />
            <span class="hint">云端一般 30~60，本地 Ollama 可设 120</span>
          </el-form-item>
          <el-form-item label="最大输出 tokens">
            <el-input-number v-model="cfgForm.max_tokens" :min="64" :max="8192" :step="64" />
          </el-form-item>
          <el-form-item label="temperature">
            <el-input-number v-model="cfgForm.temperature" :min="0" :max="2" :step="0.1" :precision="2" />
            <span class="hint">问答建议 0.2~0.5，越低越保守、越少编造</span>
          </el-form-item>
          <el-form-item label="登录用户每日上限">
            <el-input-number v-model="cfgForm.daily_limit" :min="0" :max="100000" :step="50" />
          </el-form-item>
          <el-form-item label="匿名每日上限">
            <el-input-number v-model="cfgForm.anon_daily_limit" :min="0" :max="100000" :step="10" />
            <div class="hint">按 IP 计数，进程内计时（次日 0 点重置）</div>
          </el-form-item>

          <el-form-item>
            <el-button type="primary" :loading="cfgSaving" @click="saveConfig">保存配置</el-button>
            <el-button :loading="cfgTesting" @click="testConfig">测试连通性</el-button>
            <el-button @click="loadConfig">重新读取</el-button>
          </el-form-item>
        </el-form>

        <el-descriptions v-if="cfgMeta" :column="2" border size="small" style="margin-top: 8px">
          <el-descriptions-item label="当前生效模型">{{ cfgMeta.effective_model }}</el-descriptions-item>
          <el-descriptions-item label="模块状态">
            <el-tag v-if="cfgMeta.configured" type="success" size="small">可用</el-tag>
            <el-tag v-else type="warning" size="small">未就绪</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Key 状态">
            {{ cfgMeta.api_key_configured ? cfgMeta.api_key_masked : '未配置' }}
          </el-descriptions-item>
          <el-descriptions-item label="问答接口">/api/v1/qa/chat（SSE） · /api/v1/qa/chat/sync</el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="cfgTest" :type="cfgTest.ok ? 'success' : 'error'" :closable="false" show-icon
          style="margin-top: 14px"
          :title="cfgTest.ok
            ? `连接正常：${cfgTest.model} · ${cfgTest.latency_ms} ms · 返回「${cfgTest.answer}」`
            : `连接失败（${cfgTest.error_code}）：${cfgTest.message}`"
        />
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.spacer { flex: 1; }
.muted { color: #909399; }
.small { font-size: 12px; }
.hint { font-size: 12px; color: #909399; margin-left: 8px; line-height: 1.5; }
.stat-card { text-align: center; }
.stat-value { font-size: 20px; font-weight: 700; color: #2f7d5c; }
.stat-label { font-size: 12px; color: #909399; margin-top: 2px; }
.audit-msg { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.audit-msg.user { background: #f6f8f7; }
.audit-msg-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.audit-msg-body { white-space: pre-wrap; word-break: break-word; font-size: 13.5px; line-height: 1.7; }
.audit-refs { margin-top: 8px; }
</style>
