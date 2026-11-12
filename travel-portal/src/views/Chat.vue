<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api, qaChatStream, toast,
  type DiagnoseResult, type QaConversation, type QaRef, type QaStatus, type Trip,
} from '../api'
import { currentUser } from '../auth'

interface ChatMsg {
  id?: number
  role: 'user' | 'assistant'
  content: string
  refs: QaRef[]
  aigc: boolean
  degraded: boolean
  streaming?: boolean
  error?: boolean
  /** 降级原因（来自后端 done 事件的 error_code） */
  errorCode?: string
  /** 对话内直接创建的行程卡数据 */
  trip?: Trip | null
  /** 对话内行程判官结果 */
  judge?: DiagnoseResult
}

const route = useRoute()
const router = useRouter()

const status = ref<QaStatus | null>(null)
const suggestions = ref<string[]>([])
const messages = ref<ChatMsg[]>([])
const input = ref('')
const sending = ref(false)
const conversationId = ref('')
const conversations = ref<QaConversation[]>([])
const showHistory = ref(false)
const loadingHistory = ref(false)
const bottomRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
let abortCtrl: AbortController | null = null

const tripId = computed(() => (route.query.trip as string) || '')
const enabled = computed(() => !!status.value?.enabled)
/** 未配置大模型时后端走「知识库直出」，前端如实标注 */
const modelReady = computed(() => !!status.value?.configured)
const canAsk = computed(() => !!input.value.trim() && !sending.value && enabled.value)

// ---------- 会话/行程的本地记忆：匿名刷新后也能恢复最近一次会话 ----------
const LAST_CONV_KEY = 'qa.lastConv'
const LAST_TRIP_KEY = 'qa.lastTrip'
const lastTripId = ref(localStorage.getItem(LAST_TRIP_KEY) || '')

function rememberTrip(t?: Trip | null) {
  if (t?.trip_id) {
    lastTripId.value = t.trip_id
    try { localStorage.setItem(LAST_TRIP_KEY, t.trip_id) } catch { /* ignore */ }
  }
}

watch(conversationId, (v) => {
  try {
    if (v) localStorage.setItem(LAST_CONV_KEY, v)
    else localStorage.removeItem(LAST_CONV_KEY)
  } catch { /* ignore */ }
})

async function restoreLastConversation() {
  if (messages.value.length) return
  let id = ''
  try { id = localStorage.getItem(LAST_CONV_KEY) || '' } catch { id = '' }
  if (!id) return
  try {
    const data = await api.qaConversation(id)
    if (!data.messages?.length) return
    conversationId.value = id
    messages.value = data.messages.map((m: any) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      refs: m.refs || [],
      aigc: !!m.aigc,
      degraded: !!m.degraded,
    }))
    scrollToBottom()
  } catch { /* 匿名会话过期等情况静默 */ }
}

function scrollToBottom() {
  nextTick(() => bottomRef.value?.scrollIntoView({ behavior: 'smooth', block: 'end' }))
}

async function init() {
  try {
    status.value = await api.qaStatus()
  } catch {
    status.value = { enabled: false, configured: false, provider: '', model: '', masked_key: '', aigc_label: '' }
    return
  }
  if (!status.value?.enabled) return
  try {
    const res = await api.qaSuggestions()
    suggestions.value = res.items || []
  } catch { /* 推荐问题失败不阻塞 */ }
  if (currentUser.value) {
    // 登录后：把匿名期间的最近会话认领到账号，再刷新历史会话列表
    let last = ''
    try { last = localStorage.getItem(LAST_CONV_KEY) || '' } catch { last = '' }
    if (last) {
      try { await api.qaConversation(last) } catch { /* 会话不存在/已删除 */ }
    }
    refreshConversations()
  } else {
    await restoreLastConversation()
  }
}

async function refreshConversations() {
  try {
    const data = await api.qaConversations()
    conversations.value = data.items || []
  } catch { /* 未登录或接口异常时静默 */ }
}

function newChat() {
  conversationId.value = ''
  messages.value = []
  input.value = ''
  showHistory.value = false
  nextTick(() => inputRef.value?.focus())
}

async function openConversation(conv: QaConversation) {
  if (sending.value) return
  loadingHistory.value = true
  try {
    const data = await api.qaConversation(conv.id)
    conversationId.value = conv.id
    messages.value = (data.messages || []).map((m) => ({
      id: m.id, role: (m.role === 'user' ? 'user' : 'assistant') as ChatMsg['role'],
      content: m.content, refs: m.refs || [],
      aigc: !!m.aigc, degraded: !!m.degraded,
    }))
    showHistory.value = false
    scrollToBottom()
  } catch (err: any) {
    toast(err?.message || '加载会话失败', true)
  } finally {
    loadingHistory.value = false
  }
}

async function removeConversation(conv: QaConversation, e: Event) {
  e.stopPropagation()
  if (!window.confirm(`删除会话「${conv.title}」？`)) return
  try {
    await api.qaDeleteConversation(conv.id)
    if (conversationId.value === conv.id) newChat()
    refreshConversations()
    toast('会话已删除')
  } catch (err: any) {
    toast(err?.message || '删除失败', true)
  }
}

async function ask(text?: string) {
  const question = (text ?? input.value).trim()
  if (!question || sending.value || !enabled.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: question, refs: [], aigc: false, degraded: false })
  const assistant: ChatMsg = {
    role: 'assistant', content: '', refs: [], aigc: true, degraded: false, streaming: true,
  }
  messages.value.push(assistant)
  sending.value = true
  scrollToBottom()

  // 行程上下文：自然语言编辑行程（改交通方式/出发时间/增删点位/移动点位）
  if (tripId.value && TRIP_EDIT_RE.test(question)) {
    try {
      const res = await api.chatEditTrip(tripId.value, question)
      const changeText = (res.changes || []).map((c) => '· ' + c).join('\n')
      assistant.content = changeText ? `${res.reply}\n\n${changeText}` : res.reply
      assistant.trip = res.trip
      assistant.aigc = false
      assistant.degraded = false
      assistant.streaming = false
      scrollToBottom()
      sending.value = false
      return
    } catch (e: any) {
      toast(e?.message || '行程编辑失败，已转为普通问答', true)
    }
  }

  abortCtrl = new AbortController()
  try {
    await qaChatStream(
      {
        message: question,
        conversation_id: conversationId.value || undefined,
        trip_id: tripId.value || undefined,
      },
      {
        onMeta(meta) {
          conversationId.value = meta.conversation_id
          assistant.refs = meta.refs || []
          if (meta.trip) {
            assistant.trip = meta.trip
            rememberTrip(meta.trip)
          }
        },
        onDelta(text) {
          assistant.content += text
          scrollToBottom()
        },
        onDone(done) {
          assistant.streaming = false
          assistant.aigc = done.aigc
          assistant.degraded = done.degraded
          assistant.errorCode = done.error_code || undefined
          if (done.trip) {
            assistant.trip = done.trip
            rememberTrip(done.trip)
          }
        },
      },
      abortCtrl.signal,
    )
    assistant.streaming = false
    scrollToBottom()
  } catch (err: any) {
    assistant.streaming = false
    if (err?.name === 'AbortError') {
      assistant.content += '\n（已停止生成）'
      assistant.aigc = false
    } else {
      // 流式不可用（旧浏览器/代理缓冲）→ 自动回退到非流式接口
      try {
        const out = await api.qaChatSync({
          message: question,
          conversation_id: conversationId.value || undefined,
          trip_id: tripId.value || undefined,
        })
        conversationId.value = out.conversation_id
        assistant.content = out.answer
        assistant.refs = out.refs || []
        assistant.aigc = out.aigc
        assistant.degraded = out.degraded
        assistant.errorCode = out.error_code || undefined
        if (out.trip) {
          assistant.trip = out.trip
          rememberTrip(out.trip)
        }
      } catch (e2: any) {
        assistant.content = e2?.message || err?.message || '抱歉，问答服务暂时不可用，请稍后再试'
        assistant.error = true
        assistant.aigc = false
      }
    }
    scrollToBottom()
  } finally {
    sending.value = false
    abortCtrl = null
    if (currentUser.value) refreshConversations()
  }
}

function stop() {
  abortCtrl?.abort()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    if (canAsk.value) ask()
  }
}

const kindLabel: Record<string, string> = { poi: '资源', faq: '知识库', mode: '模式', weather: '天气' }
const kindIcon: Record<string, string> = { poi: '📍', faq: '📖', mode: '🧭', weather: '🌤' }

/** 降级原因 → 面向用户的简短说明（后端 done/error_code） */
const TRIP_EDIT_RE = /(改成|改为|换成|换为|删掉|删除|去掉|移除|加上|加个|加一个|加入|移动到|挪到|移到|出发|骑行|打车|步行|公交|驾车|当地美食|加餐|调整时间)/

const DEGRADED_REASON: Record<string, string> = {
  timeout: '响应超时',
  rate_limit: '服务繁忙',
  auth: '配置异常',
  unavailable: '网络波动',
  bad_response: '服务异常',
  not_configured: '服务未配置',
}

function degradedLabel(m: ChatMsg): string {
  const reason = m.errorCode ? DEGRADED_REASON[m.errorCode] : ''
  return reason
    ? `AI 服务暂不可用（${reason}）· 以下为知识库摘录`
    : 'AI 服务暂不可用 · 以下为知识库摘录'
}

/** 打开对话内生成的行程详情 */
function openTrip(t: Trip | null | undefined) {
  if (t?.trip_id) router.push(`/trip/${t.trip_id}`)
}

// ---------- 行程判官（问答内直接检查行程） ----------
const judging = ref(false)
const judgeTripId = computed(() => tripId.value || lastTripId.value)

function starText(n: number | undefined | null): string {
  const k = Math.max(0, Math.min(5, Math.round(n || 0)))
  return '★★★★★'.slice(0, k) + '☆☆☆☆☆'.slice(0, 5 - k)
}

async function runJudge() {
  const tid = judgeTripId.value
  if (!tid) {
    toast('先在「创建计划」生成一个行程，或在行程页点「问AI」进入后再使用行程判官')
    return
  }
  if (judging.value) return
  judging.value = true
  messages.value.push({
    role: 'user', content: '帮我检查一下这个行程', refs: [], aigc: false, degraded: false,
  })
  scrollToBottom()
  try {
    const res = await api.qaJudge({
      trip_id: tid,
      conversation_id: conversationId.value || undefined,
    })
    conversationId.value = res.conversation_id || conversationId.value
    messages.value.push({
      role: 'assistant',
      // 气泡只展示前两行摘要，详细内容由下方判官卡承载（完整文本已落库用于历史会话）
      content: (res.answer || '').split('\n').slice(0, 2).join('\n'),
      refs: [], aigc: false, degraded: false, judge: res.diagnose,
    })
    if (currentUser.value) refreshConversations()
  } catch (e: any) {
    messages.value.push({
      role: 'assistant', content: e?.message || '行程判官暂时不可用，请稍后再试',
      refs: [], aigc: false, degraded: false, error: true,
    })
  } finally {
    judging.value = false
    scrollToBottom()
  }
}

// ---------- 智能解析（合规版）：粘贴攻略文本 → 行程 ----------
const parseOpen = ref(false)
const parseText = ref('')
const parsing = ref(false)

function openParse() {
  parseOpen.value = true
}

async function submitParse() {
  const text = parseText.value.trim()
  if (text.length < 10) {
    toast('攻略文本太短，至少粘贴 10 个字')
    return
  }
  parsing.value = true
  try {
    const res = await api.parseGuideTrip({
      text,
      conversation_id: conversationId.value || undefined,
    })
    parseOpen.value = false
    parseText.value = ''
    conversationId.value = res.conversation_id || conversationId.value
    rememberTrip(res.trip)
    messages.value.push({
      role: 'user',
      content: '【智能解析】' + text.slice(0, 60) + (text.length > 60 ? '…' : ''),
      refs: [], aigc: false, degraded: false,
    })
    const matched = res.matched.slice(0, 8).join('、')
    const unmatched = res.unmatched.length ? `\n未匹配：${res.unmatched.join('、')}` : ''
    messages.value.push({
      role: 'assistant',
      content: res.answer || `已从攻略中识别 ${res.matched.length} 个地点，生成 ${res.days} 天行程：${matched}${unmatched}。\n${res.note}`,
      refs: [], aigc: false, degraded: false, trip: res.trip,
    })
    if (currentUser.value) refreshConversations()
    scrollToBottom()
  } catch (e: any) {
    toast(e?.message || '智能解析失败，请换一段攻略试试', true)
  } finally {
    parsing.value = false
  }
}

function openRef(ref: QaRef) {
  if (ref.poi_id || ref.kind === 'poi') {
    router.push({ path: '/explore', query: { keyword: ref.name } })
  }
}

onMounted(init)
</script>

<template>
  <section class="section">
    <div class="container chat-page">
      <header class="chat-head">
        <div>
          <h1 class="section-title">问小旅 <span class="tag">AI</span></h1>
          <p class="section-sub">
            花溪专属问答助手 · 回答基于本站资源库与实时天气
            <template v-if="status?.model"> · {{ status.model }}</template>
          </p>
        </div>
        <div class="head-actions">
          <button class="btn btn-outline btn-sm" @click="showHistory = !showHistory">
            {{ showHistory ? '收起历史' : '历史会话' }}
          </button>
          <button class="btn btn-primary btn-sm" @click="newChat">＋ 新对话</button>
        </div>
      </header>

      <div v-if="status && !enabled" class="card disabled-card">
        <h3>问答功能暂未启用</h3>
        <p class="muted small">
          后端未开启 <code>FEATURE_QA_CHAT</code> 或未配置大模型 Key。请在
          <code>travel-api/.env</code> 中配置 <code>LLM_BASE_URL / LLM_API_KEY / LLM_MODEL</code> 后重启服务。
        </p>
      </div>

      <div v-else class="chat-layout" :class="{ 'with-history': showHistory }">
        <aside v-if="showHistory" class="card history-panel">
          <h3 class="panel-title">历史会话</h3>
          <p v-if="!currentUser" class="muted small">
            登录后可保存并查看全部历史会话；未登录时本机会自动保留最近一次会话（刷新后仍可恢复）。
          </p>
          <p v-else-if="!conversations.length" class="muted small">还没有历史会话</p>
          <ul v-else class="conv-list">
            <li
              v-for="c in conversations" :key="c.id"
              class="conv-item" :class="{ on: c.id === conversationId }"
              @click="openConversation(c)"
            >
              <div class="conv-title">{{ c.title }}</div>
              <div class="conv-meta">
                <span>{{ c.updated_at || c.created_at }}</span>
                <button class="conv-del" title="删除" @click="removeConversation(c, $event)">×</button>
              </div>
            </li>
          </ul>
          <p v-if="loadingHistory" class="muted small">加载中…</p>
        </aside>

        <div class="card chat-panel">
          <div class="messages" aria-live="polite">
            <div v-if="!messages.length" class="welcome">
              <div class="welcome-avatar">🌿</div>
              <h2>你好，我是小旅</h2>
              <p class="muted">
                我可以回答花溪的景点、美食、住宿、交通、行程模式等问题，
                也会结合你正在看的行程给出建议。试试下面的问题：
              </p>
              <p v-if="tripId" class="trip-edit-hint">
                当前关联行程 <b>{{ tripId }}</b>：直接说「最后一段改成骑行」「8点出发」
                「加个当地美食」「删掉某某」就可以改行程。
              </p>
              <div class="sug-list">
                <button
                  v-for="s in suggestions" :key="s" class="chip sug-chip"
                  @click="ask(s)"
                >{{ s }}</button>
              </div>
            </div>

            <div
              v-for="(m, i) in messages" :key="i"
              class="msg" :class="m.role"
            >
              <div v-if="m.role === 'assistant'" class="avatar">🌿</div>
              <div class="bubble-wrap">
                <div class="bubble" :class="{ error: m.error }">
                  <span class="bubble-text">{{ m.content }}</span>
                  <span v-if="m.streaming" class="cursor">▍</span>
                </div>
                <div v-if="m.refs?.length" class="refs">
                  <button
                    v-for="r in m.refs" :key="r.ref_id" class="ref-chip"
                    :class="{ clickable: r.kind === 'poi' }"
                    :title="r.summary || r.name"
                    @click="openRef(r)"
                  >
                    <span class="ref-icon">{{ kindIcon[r.kind] || '📎' }}</span>
                    <span class="ref-name">{{ r.name }}</span>
                    <span class="ref-kind">{{ kindLabel[r.kind] || r.kind }}</span>
                  </button>
                </div>
                <div v-if="m.trip" class="trip-card">
                  <div class="tc-head">
                    <span class="tc-title">🧭 {{ m.trip.mode_name }} · {{ m.trip.days }} 天行程</span>
                    <span v-if="m.trip.start_date" class="tc-date">{{ m.trip.start_date }}</span>
                  </div>
                  <div class="tc-meta">
                    预算 ¥{{ m.trip.budget }} · 预计花费 ¥{{ m.trip.total_cost }} ·
                    {{ m.trip.days_plan?.length || 0 }} 天
                  </div>
                  <div class="tc-days">
                    <div v-for="d in m.trip.days_plan" :key="d.day_index" class="tc-day">
                      <b>Day{{ d.day_index }}</b>
                      <span v-if="d.date" class="tc-week">{{ d.date }} {{ d.week }}</span>
                      <span class="tc-theme">{{ d.theme }}</span>
                      <span class="tc-n">{{ d.items?.length || 0 }} 点</span>
                    </div>
                  </div>
                  <button class="btn btn-primary btn-sm tc-go" @click="openTrip(m.trip)">
                    查看计划 →
                  </button>
                </div>
                <div v-if="m.judge" class="judge-chat-card">
                  <div class="jc-head">
                    <span class="jc-stars">{{ starText(m.judge.overall?.stars) }}</span>
                    <b>{{ m.judge.overall?.level }}</b>
                    <span class="jc-trip">{{ m.judge.trip_id }}</span>
                  </div>
                  <div class="jc-overall">{{ m.judge.overall?.summary }}</div>
                  <div class="jc-days">
                    <div v-for="ds in (m.judge.day_summaries || [])" :key="ds.day_index" class="jc-day">
                      <b>Day{{ ds.day_index }}</b>
                      <span class="jc-theme">{{ ds.theme }}</span>
                      <span class="jc-meta">{{ ds.play_count }} 点 · 通勤 {{ ds.commute_km }}km/{{ ds.commute_min }}分</span>
                    </div>
                  </div>
                  <div v-if="(m.judge.suggestions || []).length" class="jc-sug">
                    💡 {{ (m.judge.suggestions || [])[0]?.title }}
                  </div>
                  <div v-if="(m.judge.issues || []).length" class="jc-issues small muted">
                    需留意 {{ (m.judge.issues || []).length }} 条：{{ (m.judge.issues || [])[0]?.title }}{{ (m.judge.issues || []).length > 1 ? ' 等' : '' }}
                  </div>
                  <button class="btn btn-primary btn-sm tc-go" @click="router.push('/trip/' + m.judge.trip_id)">
                    查看并优化行程 →
                  </button>
                </div>
                <div v-if="m.role === 'assistant' && !m.streaming" class="msg-meta">
                  <span v-if="m.degraded" class="degraded">{{ degradedLabel(m) }}</span>
                  <span v-else-if="m.aigc" class="aigc">内容由 AI 生成，仅供参考</span>
                </div>
              </div>
            </div>
            <div ref="bottomRef" />
          </div>

          <div class="composer">
            <div class="chat-actions">
              <button class="chip" @click="router.push('/plan')">＋ 创建计划</button>
              <button class="chip" @click="openParse">✨ 智能解析</button>
              <button class="chip" :disabled="judging" @click="runJudge">
                {{ judging ? '判官检查中…' : '🧭 行程判官' }}
              </button>
            </div>
            <textarea
              ref="inputRef"
              v-model="input"
              class="composer-input"
              rows="2"
              maxlength="300"
              placeholder="问点花溪的事，比如「青岩古镇门票多少？」（Enter 发送，Shift+Enter 换行）"
              :disabled="!enabled || sending"
              @keydown="onKeydown"
            />
            <div class="composer-bar">
              <span class="counter">{{ input.length }}/300</span>
              <button v-if="sending" class="btn btn-outline btn-sm" @click="stop">停止</button>
              <button v-else class="btn btn-primary btn-sm" :disabled="!canAsk" @click="ask()">发送</button>
            </div>
          </div>
          <p class="composer-hint">
            回答由 AI 基于本站资料生成，可能存在误差；门票、开放时间等以景区官方公告为准。
          </p>

          <!-- 智能解析弹层 -->
          <div v-if="parseOpen" class="parse-mask no-print" @click.self="parseOpen = false">
            <div class="parse-modal">
              <div class="parse-head">
                <h3>✨ 智能解析攻略</h3>
                <button class="btn btn-sm" @click="parseOpen = false">关闭</button>
              </div>
              <p class="muted small">
                把你看过的攻略文字粘贴进来（这里只解析你粘贴的文本，不抓任何链接），
                系统会识别地点并排成行程；本站没有的地点会列出来，不会编造。
              </p>
              <textarea
                v-model="parseText"
                class="parse-textarea"
                rows="8"
                maxlength="6000"
                placeholder="例如：上午先去花溪公园散步，中午到花溪王记牛肉粉店吃碗牛肉粉，下午去十里河滩湿地公园骑行，傍晚去青岩古镇逛老街吃状元蹄…"
              />
              <div class="parse-foot">
                <span class="small muted">{{ parseText.length }}/6000</span>
                <button class="btn btn-outline btn-sm" @click="parseOpen = false">取消</button>
                <button class="btn btn-primary btn-sm" :disabled="parsing" @click="submitParse">
                  {{ parsing ? '解析中…' : '解析并生成行程' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-page { max-width: 1180px; }
.chat-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
.head-actions { display: flex; gap: 10px; }
.disabled-card { text-align: center; padding: 48px 24px; }
.disabled-card code { background: var(--brand-light); color: var(--brand); padding: 1px 6px; border-radius: 5px; }

.chat-layout { display: grid; grid-template-columns: 1fr; gap: 16px; align-items: start; }
.chat-layout.with-history { grid-template-columns: 260px 1fr; }

.history-panel { padding: 16px; position: sticky; top: 84px; max-height: calc(100vh - 120px); overflow: auto; }
.panel-title { font-size: 15px; margin: 0 0 12px; }
.conv-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.conv-item { padding: 10px 12px; border-radius: 10px; cursor: pointer; border: 1px solid transparent; }
.conv-item:hover { background: var(--brand-light); }
.conv-item.on { background: var(--brand-light); border-color: var(--brand); }
.conv-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { display: flex; align-items: center; justify-content: space-between; margin-top: 4px; font-size: 11px; color: var(--muted); }
.conv-del { border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 15px; line-height: 1; padding: 2px 4px; border-radius: 4px; }
.conv-del:hover { color: #c0392b; background: #fdecea; }

.chat-panel { display: flex; flex-direction: column; padding: 0; overflow: hidden; min-height: 620px; }
.messages { flex: 1; overflow-y: auto; padding: 22px 22px 8px; max-height: calc(100vh - 320px); min-height: 380px; }

.welcome { text-align: center; padding: 18px 8px 8px; }
.welcome-avatar { font-size: 34px; }
.welcome h2 { margin: 8px 0 6px; font-size: 20px; }
.welcome p { max-width: 560px; margin: 0 auto 16px; font-size: 14px; }
.sug-list { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.sug-chip { background: #fff; border: 1px solid var(--line); }

.msg { display: flex; gap: 10px; margin-bottom: 16px; }
.msg.user { justify-content: flex-end; }
.avatar {
  width: 34px; height: 34px; border-radius: 50%; flex: 0 0 34px;
  display: flex; align-items: center; justify-content: center;
  background: var(--brand-light); font-size: 17px;
}
.bubble-wrap { max-width: 78%; }
.msg.user .bubble-wrap { max-width: 72%; }
.bubble {
  padding: 11px 14px; border-radius: 14px; font-size: 14.5px; line-height: 1.75;
  white-space: pre-wrap; word-break: break-word;
}
.msg.assistant .bubble { background: #f3f6f4; border-top-left-radius: 4px; }
.msg.user .bubble { background: var(--brand); color: #fff; border-top-right-radius: 4px; }
.bubble.error { background: #fdecea; color: #a93226; }
.cursor { display: inline-block; animation: blink 1s steps(2, start) infinite; color: var(--brand); }
@keyframes blink { to { visibility: hidden; } }

.refs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.ref-chip {
  display: inline-flex; align-items: center; gap: 5px;
  background: #fff; border: 1px solid var(--line); border-radius: 999px;
  padding: 4px 10px; font-size: 12px; color: var(--ink); cursor: default;
}
.ref-chip.clickable { cursor: pointer; }
.ref-chip.clickable:hover { border-color: var(--brand); color: var(--brand); }
.ref-icon { font-size: 12px; }
.ref-name { font-weight: 600; }
.ref-kind { color: var(--muted); font-size: 11px; }
.msg-meta { margin-top: 6px; font-size: 11.5px; }
.aigc { color: var(--muted); }
.degraded { color: var(--accent); }

/* 对话内行程卡 */
.trip-card {
  margin-top: 10px; background: #fff; border: 1px solid var(--line);
  border-radius: 14px; padding: 12px 14px; max-width: 360px;
}
.tc-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.tc-title { font-weight: 700; font-size: 14px; }
.tc-date { font-size: 11.5px; color: var(--muted); }
.tc-meta { margin-top: 4px; font-size: 12px; color: var(--muted); }
.tc-days { margin: 8px 0 10px; display: flex; flex-direction: column; gap: 4px; }
.tc-day { font-size: 12.5px; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.tc-week { color: var(--accent); font-size: 11.5px; }
.tc-theme { color: var(--ink); }
.tc-n { color: var(--muted); font-size: 11px; margin-left: auto; }
.tc-go { width: 100%; }

/* 对话内行程判官卡 */
.judge-chat-card {
  margin-top: 10px; background: #fff; border: 1px solid #f0d3a8;
  border-radius: 14px; padding: 12px 14px; max-width: 420px;
}
.jc-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.jc-stars { color: #e6a23c; letter-spacing: 1px; font-size: 14px; }
.jc-trip { margin-left: auto; font-size: 11px; color: var(--muted); }
.jc-overall { margin-top: 5px; font-size: 12.5px; color: var(--ink); }
.jc-days { margin: 8px 0; display: flex; flex-direction: column; gap: 4px; }
.jc-day { font-size: 12.5px; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.jc-theme { color: var(--ink); }
.jc-meta { color: var(--muted); font-size: 11.5px; margin-left: auto; }
.jc-sug {
  margin: 6px 0; padding: 7px 10px; border-radius: 9px;
  background: #fffaf1; border: 1px solid #f0d3a8; font-size: 12.5px;
}
.jc-issues { margin-bottom: 8px; }

/* 底部动作入口 */
.chat-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.chat-actions .chip { font-size: 12.5px; padding: 5px 11px; }
.trip-edit-hint {
  margin-top: 10px; padding: 8px 12px; border-radius: 10px;
  background: var(--brand-light); color: var(--brand); font-size: 12.5px;
}

/* 智能解析弹层 */
.parse-mask {
  position: fixed; inset: 0; background: rgba(20, 30, 26, .45); z-index: 60;
  display: flex; align-items: center; justify-content: center;
}
.parse-modal {
  width: 640px; max-width: 92vw; max-height: 86vh; overflow: auto;
  background: #fff; border-radius: 16px; padding: 18px 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, .25);
}
.parse-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.parse-head h3 { margin: 0; font-size: 17px; }
.parse-textarea {
  width: 100%; margin-top: 10px; resize: vertical; min-height: 160px;
  border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  font-size: 13.5px; line-height: 1.7; outline: none; color: var(--ink);
  font-family: inherit;
}
.parse-textarea:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-light); }
.parse-foot { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 10px; }
.parse-foot .muted { margin-right: auto; }

.composer { border-top: 1px solid var(--line); padding: 12px 16px 6px; background: #fff; }
.composer-input {
  width: 100%; resize: none; border: 1px solid var(--line); border-radius: 12px;
  padding: 10px 12px; font-size: 14px; outline: none; color: var(--ink);
}
.composer-input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-light); }
.composer-input:disabled { background: #f7f8f7; }
.composer-bar { display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 8px; }
.counter { margin-right: auto; font-size: 12px; color: var(--muted); }
.composer-hint { margin: 6px 16px 12px; font-size: 11.5px; color: var(--muted); text-align: center; }

@media (max-width: 860px) {
  .chat-layout.with-history { grid-template-columns: 1fr; }
  .history-panel { position: static; max-height: 240px; }
  .bubble-wrap, .msg.user .bubble-wrap { max-width: 88%; }
}
</style>
