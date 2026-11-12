<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api, MODE_EMOJI, MODE_ORDER, PREFERENCES, PARTY_TYPES,
  type Mode, toast,
} from '../api'
import ModeConfigurator from './ModeConfigurator.vue'
import { defaultParts, estimateCost, type ModeKey } from '../cost'

const route = useRoute()
const router = useRouter()
const modes = ref<Mode[]>([])
const submitting = ref(false)

const form = reactive({
  mode: 'leisure',
  days: 2,
  budget: 1200,
  party_type: 'couple',
  preferences: [] as string[],
})

// 配置器上报的节奏 + 开销偏好（默认取模式默认值）
const modePayload = ref<{ pace: Record<string, unknown>; cost_prefs: Record<string, unknown> }>({
  pace: {}, cost_prefs: {},
})

// 每个模式按当前天数/预算的"整体开销"预估，用于选择卡片上的成本提示
function modeEstimate(mode: string): number {
  return estimateCost(defaultParts(mode as ModeKey), form.days, form.budget).total
}

onMounted(async () => {
  const m = route.query.mode
  if (typeof m === 'string' && MODE_ORDER.includes(m)) form.mode = m
  try {
    modes.value = await api.getModes()
  } catch { /* 拦截器已提示 */ }
})

function togglePref(code: string) {
  const i = form.preferences.indexOf(code)
  if (i >= 0) form.preferences.splice(i, 1)
  else form.preferences.push(code)
}

function payload() {
  return {
    days: form.days,
    budget: form.budget,
    preferences: [...form.preferences],
    party_type: form.party_type,
    seed: Math.floor(Math.random() * 9999),
    ...modePayload.value,
  }
}

async function generate() {
  if (form.budget <= 0) {
    toast('请输入有效预算', true)
    return
  }
  submitting.value = true
  try {
    const trip = await api.generateTrip({ ...payload(), mode: form.mode })
    router.push({ path: `/trip/${trip.trip_id}` })
  } catch {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

function goCompare() {
  const p = payload()
  router.push({
    path: '/compare',
    query: {
      days: String(p.days), budget: String(p.budget),
      prefs: p.preferences.join(','), party: p.party_type, seed: String(p.seed),
    },
  })
}

function goPersonalize() {
  router.push({
    path: '/personalize',
    query: {
      mode: form.mode, days: String(form.days), budget: String(form.budget),
    },
  })
}
</script>

<template>
  <div class="container">
    <section class="section">
      <div class="section-head">
        <div>
          <h1 class="section-title">定制你的花溪行程</h1>
          <div class="section-sub">填写几个简单条件，系统会在 1 秒内排好每日路线、餐食与住宿</div>
        </div>
      </div>

      <div class="plan-layout">
        <!-- 左侧：表单 -->
        <div class="card form-card">
          <div class="form-block">
            <div class="block-title"><i>1</i> 选择旅行模式</div>
            <div class="block-sub muted small">选一种方式，下面的"小部件"都能单独改；选之前先看清整体开销是否贴合你的预算</div>
            <div class="mode-grid">
              <div
                v-for="m in modes" :key="m.mode"
                class="mode-opt" :class="{ on: form.mode === m.mode }"
                @click="form.mode = m.mode"
              >
                <span class="mode-e">{{ MODE_EMOJI[m.mode] || '🧭' }}</span>
                <span class="mode-n">{{ m.mode_name }}</span>
                <span class="mode-cost">预估 ¥{{ modeEstimate(m.mode) }}</span>
              </div>
              <div v-if="!modes.length" class="small muted">模式加载中…</div>
            </div>
            <div class="small muted" style="margin-top: 10px">
              {{ modes.find((m) => m.mode === form.mode)?.description || '' }}
            </div>
            <!-- 模式细节微调 + 整体开销 -->
            <ModeConfigurator
              :mode="form.mode"
              :days="form.days"
              :budget="form.budget"
              @change="modePayload = $event"
            />
          </div>

          <div class="divider"></div>

          <div class="form-block">
            <div class="block-title"><i>2</i> 行程天数与预算</div>
            <div class="form-row">
              <div class="field">
                <label>行程天数：{{ form.days }} 天</label>
                <input v-model.number="form.days" type="range" min="1" max="7" step="1" class="range" />
                <div class="range-ticks"><span>1 天</span><span>7 天</span></div>
              </div>
              <div class="field">
                <label>全程人均预算（元）</label>
                <input v-model.number="form.budget" type="number" min="1" class="input" />
              </div>
            </div>
            <div class="preset-row">
              <span class="small muted">快速选预算</span>
              <button v-for="b in [300, 800, 1500, 3000]" :key="b"
                      class="chip" :class="{ on: form.budget === b }"
                      @click="form.budget = b">¥{{ b }}</button>
            </div>
          </div>

          <div class="divider"></div>

          <div class="form-block">
            <div class="block-title"><i>3</i> 出行人群</div>
            <div class="chips">
              <button v-for="p in PARTY_TYPES" :key="p.code" class="chip"
                      :class="{ on: form.party_type === p.code }"
                      @click="form.party_type = p.code">{{ p.label }}</button>
            </div>
          </div>

          <div class="divider"></div>

          <div class="form-block">
            <div class="block-title"><i>4</i> 旅行偏好 <span class="small muted">（可多选，可跳过）</span></div>
            <div class="chips">
              <button v-for="p in PREFERENCES" :key="p.code" class="chip"
                      :class="{ on: form.preferences.includes(p.code) }"
                      @click="togglePref(p.code)">{{ p.label }}</button>
            </div>
          </div>

          <div class="divider"></div>

          <div class="action-row no-print">
            <button class="btn btn-primary" :disabled="submitting" @click="generate">
              {{ submitting ? '生成中…' : '生成行程 →' }}
            </button>
            <button class="btn btn-outline" @click="goCompare">先对比四种模式</button>
            <button class="btn btn-soft" @click="goPersonalize">按权重个性化</button>
          </div>
        </div>

        <!-- 右侧：说明 -->
        <aside class="side">
          <div class="card side-card">
            <div class="side-title">生成规则说明</div>
            <ul class="rule-list">
              <li><b>预算硬约束</b>：全程花费不超过预算弹性上限，住宿按晚计入</li>
              <li><b>时间窗对齐</b>：午餐 11:30 后、晚餐 18:00 后，超时的点自动留白</li>
              <li><b>不重复</b>：同一行程内每个资源点只出现一次</li>
              <li><b>路线就近</b>：同槽位按最近邻 + 2-opt 排序，少走回头路</li>
              <li><b>分级松弛</b>：候选不足时逐级放宽并给出提示，不会静默降质</li>
            </ul>
          </div>
          <div class="card side-card">
            <div class="side-title">预算小建议</div>
            <div class="small muted" style="line-height: 1.9">
              特种兵游约 ¥100–250/天，休闲游 ¥300–600/天，
              打卡游 ¥300–700/天，高端游 ¥1000–2000/天。
              预算偏低时高端游会自动降级，属正常行为。
            </div>
          </div>
        </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
.plan-layout { display: grid; grid-template-columns: 1fr 320px; gap: 22px; align-items: start; }
.form-card { padding: 28px; }
.block-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; display: flex; align-items: center; gap: 9px; }
.block-title i {
  width: 22px; height: 22px; border-radius: 50%; background: var(--brand);
  color: #fff; font-size: 12px; font-style: normal; display: grid; place-items: center;
}
.mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.block-sub { margin: -6px 0 12px; }
.mode-opt {
  border: 1.5px solid var(--line); border-radius: 12px; padding: 14px 8px;
  text-align: center; cursor: pointer; transition: all .15s ease;
  display: flex; flex-direction: column; gap: 3px; align-items: center;
}
.mode-opt:hover { border-color: var(--brand); }
.mode-opt.on { border-color: var(--brand); background: var(--brand-light); }
.mode-e { display: block; font-size: 26px; }
.mode-n { font-size: 14px; font-weight: 600; }
.mode-cost {
  font-size: 12px; color: var(--brand); font-weight: 700;
  background: var(--brand-light, #e8f3ee); border-radius: 999px; padding: 2px 9px; margin-top: 2px;
}
.mode-opt.on .mode-cost { background: #d8ece1; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.range { width: 100%; accent-color: var(--brand); }
.range-ticks { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
.preset-row { display: flex; align-items: center; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.preset-row .chip { padding: 4px 12px; font-size: 12px; }
.chips { display: flex; gap: 9px; flex-wrap: wrap; }
.action-row { display: flex; gap: 12px; flex-wrap: wrap; }
.side { display: flex; flex-direction: column; gap: 16px; }
.side-card { padding: 20px; }
.side-title { font-weight: 700; margin-bottom: 12px; }
.rule-list { margin: 0; padding-left: 18px; font-size: 13px; color: #5b6b64; line-height: 1.95; }
.rule-list b { color: var(--ink); }
@media (max-width: 900px) {
  .plan-layout { grid-template-columns: 1fr; }
  .mode-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) { .form-row { grid-template-columns: 1fr; } }
</style>
