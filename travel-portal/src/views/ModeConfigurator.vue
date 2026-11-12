<script setup lang="ts">
import { reactive, computed, watch } from 'vue'
import {
  HOTEL_TIERS, DINING_STANDARDS, TRANSPORT_MODES, EVENING_OPTIONS,
  defaultParts, estimateCost, partsToPayload, type CostParts, type ModeKey,
} from '../cost'

const props = defineProps<{
  mode: string
  days: number
  budget: number
}>()

const emit = defineEmits<{
  (e: 'change', payload: { pace: Record<string, unknown>; cost_prefs: Record<string, unknown> }): void
}>()

const parts = reactive<CostParts>(defaultParts(props.mode as ModeKey))

// 切换模式时重置为模式默认小部件
watch(() => props.mode, (m) => {
  Object.assign(parts, defaultParts(m as ModeKey))
})

const breakdown = computed(() => estimateCost(parts, props.days, props.budget))

// 任一部件变化 → 翻译为生成载荷并上报
watch([parts, () => props.days, () => props.budget], () => {
  emit('change', partsToPayload(parts))
}, { deep: true, immediate: true })

const rows = computed(() => [
  { icon: '🏨', label: '住宿', value: breakdown.value.hotel, note: `${breakdown.value.nights} 晚` },
  { icon: '🍽', label: '餐饮', value: breakdown.value.dining, note: '' },
  { icon: '🎫', label: '门票', value: breakdown.value.tickets, note: `约 ${parts.daily_poi} 个/天` },
  { icon: '🚌', label: '交通', value: breakdown.value.transport, note: '' },
  { icon: '🌙', label: '晚间', value: breakdown.value.evening, note: '' },
])

function pick(group: 'hotel' | 'dining' | 'transport' | 'evening', key: string) {
  parts[group] = key
}
</script>

<template>
  <div class="cfg">
    <div class="cfg-head">
      <div>
        <div class="cfg-title">微调该模式的每个小部件</div>
        <div class="small muted">每项的花费都会计入下方"整体开销"，可单独调整后再决定要不要这个模式</div>
      </div>
    </div>

    <!-- 小部件：住宿 / 餐饮 / 交通 / 晚间 -->
    <div class="cfg-grid">
      <div class="cfg-part">
        <div class="part-label">🏨 住宿档位</div>
        <div class="pills">
          <button v-for="o in HOTEL_TIERS" :key="o.key"
                  class="pill" :class="{ on: parts.hotel === o.key }"
                  @click="pick('hotel', o.key)">
            <b>{{ o.label }}</b><span>{{ o.desc }}</span>
          </button>
        </div>
      </div>

      <div class="cfg-part">
        <div class="part-label">🍽 餐饮标准</div>
        <div class="pills">
          <button v-for="o in DINING_STANDARDS" :key="o.key"
                  class="pill" :class="{ on: parts.dining === o.key }"
                  @click="pick('dining', o.key)">
            <b>{{ o.label }}</b><span>{{ o.desc }}</span>
          </button>
        </div>
      </div>

      <div class="cfg-part">
        <div class="part-label">🚌 出行交通</div>
        <div class="pills">
          <button v-for="o in TRANSPORT_MODES" :key="o.key"
                  class="pill" :class="{ on: parts.transport === o.key }"
                  @click="pick('transport', o.key)">
            <b>{{ o.label }}</b><span>{{ o.desc }}</span>
          </button>
        </div>
      </div>

      <div class="cfg-part">
        <div class="part-label">🌙 晚间安排</div>
        <div class="pills">
          <button v-for="o in EVENING_OPTIONS" :key="o.key"
                  class="pill" :class="{ on: parts.evening === o.key }"
                  @click="pick('evening', o.key)">
            <b>{{ o.label }}</b><span>{{ o.desc }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 小部件：每日景点数 / 游玩节奏（滑块） -->
    <div class="cfg-sliders">
      <div class="slider-row">
        <label>每日景点数：<b>{{ parts.daily_poi }}</b> 个/天</label>
        <input v-model.number="parts.daily_poi" type="range" min="2" max="6" step="1" class="range" />
      </div>
      <div class="slider-row">
        <label>游玩节奏：<b>{{ parts.play_hours }}</b> 小时/天</label>
        <input v-model.number="parts.play_hours" type="range" min="3" max="12" step="1" class="range" />
      </div>
    </div>

    <!-- 整体开销面板 -->
    <div class="cost" :class="breakdown.fit">
      <div class="cost-head">
        <span class="cost-title">整体开销预估</span>
        <span class="cost-total">¥{{ breakdown.total }}</span>
      </div>
      <div class="cost-rows">
        <div v-for="r in rows" :key="r.label" class="cost-row">
          <span class="cr-label">{{ r.icon }} {{ r.label }}</span>
          <span class="cr-val">¥{{ r.value }}<i v-if="r.note" class="cr-note">{{ r.note }}</i></span>
        </div>
      </div>

      <div class="budget-bar">
        <div class="bb-track">
          <div class="bb-fill" :style="{ width: Math.min(100, breakdown.usage * 100) + '%' }"></div>
        </div>
        <div class="bb-legend">
          <span>预算 ¥{{ budget }}</span>
          <span :class="breakdown.fit">{{ Math.round(breakdown.usage * 100) }}%</span>
        </div>
      </div>

      <div class="cost-status">{{ breakdown.statusText }}</div>
      <div class="cost-suggest small muted">{{ breakdown.suggestion }}</div>
    </div>
  </div>
</template>

<style scoped>
.cfg { margin-top: 14px; }
.cfg-head { margin-bottom: 12px; }
.cfg-title { font-weight: 700; font-size: 15px; }
.cfg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.cfg-part { background: var(--bg-soft, #f6f8f7); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.part-label { font-size: 13px; font-weight: 600; margin-bottom: 9px; color: var(--ink); }
.pills { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.pill {
  display: flex; flex-direction: column; gap: 1px; align-items: flex-start;
  border: 1.5px solid var(--line); border-radius: 9px; padding: 7px 9px;
  background: #fff; cursor: pointer; text-align: left; transition: all .14s ease;
}
.pill b { font-size: 13px; }
.pill span { font-size: 11px; color: var(--muted); }
.pill:hover { border-color: var(--brand); }
.pill.on { border-color: var(--brand); background: var(--brand-light, #e8f3ee); }
.cfg-sliders { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 14px; }
.slider-row label { font-size: 13px; color: var(--ink); }
.slider-row label b { color: var(--brand); }
.range { width: 100%; accent-color: var(--brand); margin-top: 6px; }

.cost { margin-top: 16px; border-radius: 14px; padding: 16px 18px; border: 1px solid var(--line); }
.cost.within { background: #f1faf4; border-color: #bfe6cd; }
.cost.slight { background: #fff8ec; border-color: #f3dcae; }
.cost.over { background: #fdf0f0; border-color: #f0c4c4; }
.cost-head { display: flex; justify-content: space-between; align-items: baseline; }
.cost-title { font-weight: 700; font-size: 14px; }
.cost-total { font-size: 26px; font-weight: 800; color: var(--ink); }
.cost-rows { margin: 12px 0; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px 14px; }
.cost-row { display: flex; flex-direction: column; font-size: 12px; }
.cr-label { color: var(--muted); }
.cr-val { font-weight: 700; font-size: 14px; color: var(--ink); }
.cr-note { font-weight: 400; font-size: 10px; color: var(--muted); margin-left: 4px; }
.budget-bar { margin: 8px 0 10px; }
.bb-track { height: 10px; border-radius: 999px; background: #e7ece9; overflow: hidden; }
.bb-fill { height: 100%; border-radius: 999px; transition: width .25s ease; }
.cost.within .bb-fill { background: #2f9e63; }
.cost.slight .bb-fill { background: #e0a23a; }
.cost.over .bb-fill { background: #d9534f; }
.bb-legend { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-top: 5px; }
.bb-legend .within, .bb-legend .slight, .bb-legend .over { font-weight: 700; }
.bb-legend .within { color: #2f9e63; }
.bb-legend .slight { color: #c8861f; }
.bb-legend .over { color: #d9534f; }
.cost-status { font-size: 13px; font-weight: 600; color: var(--ink); }
.cost-suggest { line-height: 1.7; margin-top: 4px; }
@media (max-width: 760px) {
  .cfg-grid, .cfg-sliders { grid-template-columns: 1fr; }
  .cost-rows { grid-template-columns: 1fr 1fr; }
}
</style>
