<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, MODE_EMOJI, CATEGORY_NAME, type Mode, type Poi,
         type PresetRouteSummary, toast } from '../api'
import WeatherCard from '../components/WeatherCard.vue'
import { defaultParts, estimateCost, type ModeKey } from '../cost'

const router = useRouter()
const modes = ref<Mode[]>([])
const hotPois = ref<Poi[]>([])
const studyRoutes = ref<PresetRouteSummary[]>([])
const loading = ref(true)

// 首页无天数输入，按默认 2 天估算各模式的"整体开销"，让选择页即体现成本
function modeTotal(mode: string): number {
  return estimateCost(defaultParts(mode as ModeKey), 2, 1).total
}

onMounted(async () => {
  try {
    const [m, p, r] = await Promise.all([
      api.getModes(),
      api.listPois({ page_size: 6, min_rating: 4.5 }),
      api.getPresetRoutes().catch(() => ({ items: [] as PresetRouteSummary[] })),
    ])
    modes.value = m
    hotPois.value = p.items
    studyRoutes.value = r.items
  } catch {
    toast('数据加载失败，请确认后端已启动', true)
  } finally {
    loading.value = false
  }
})

function goPlan(mode: string) {
  router.push({ path: '/plan', query: { mode } })
}
</script>

<template>
  <!-- Hero -->
  <section class="hero">
    <div class="container hero-inner">
      <div class="hero-copy">
        <div class="hero-badge">贵阳 · 花溪区</div>
        <h1>把花溪，玩成<br /><span class="brand-text">你想要的模样</span></h1>
        <p class="hero-desc">
          选一种旅行方式，告诉我们天数与预算，系统会自动排好每日路线、餐食与住宿。
          四种模式、80 个本地资源点，慢逛或暴走，都由你定。
        </p>
        <div class="hero-actions">
          <button class="btn btn-primary" @click="router.push('/plan')">开始定制行程 →</button>
          <button class="btn btn-outline" @click="router.push('/compare')">四种模式对比</button>
        </div>
      </div>
      <div class="hero-panel">
        <div class="panel-title">系统能做什么</div>
        <div class="stat-row">
          <div class="stat"><b>80</b><span>本地资源点</span></div>
          <div class="stat"><b>4</b><span>旅行模式</span></div>
          <div class="stat"><b>9</b><span>维权重打分</span></div>
        </div>
        <div class="divider"></div>
        <div class="flow">
          <div class="flow-step"><i>1</i><span>选模式与偏好</span></div>
          <div class="flow-step"><i>2</i><span>算法排布每日槽位</span></div>
          <div class="flow-step"><i>3</i><span>随时换一批 / 换单点</span></div>
        </div>
        <div class="panel-note">全程预算硬约束校验，不超支；不满足时给出分级松弛提示。</div>
      </div>
    </div>
  </section>

  <div class="container">
    <!-- 天气 -->
    <section class="section weather-section">
      <div class="section-head">
        <div>
          <h2 class="section-title">出行前，先看实时天气</h2>
          <div class="section-sub">按浏览器实时定位查询你所在位置的实况与未来 15 天预报；也可一键切回花溪查看目的地天气</div>
        </div>
      </div>
      <WeatherCard />
    </section>

    <!-- 四模式 -->
    <section class="section">
      <div class="section-head">
        <div>
          <h2 class="section-title">选择你的旅行方式</h2>
          <div class="section-sub">同一组需求，四种模式的路线节奏明显不同</div>
        </div>
        <router-link to="/compare" class="small brand-text">并排对比四种模式 →</router-link>
      </div>
      <div class="grid grid-4">
        <div v-for="m in modes" :key="m.mode" class="card card-hover mode-card" @click="goPlan(m.mode)">
          <div class="mode-emoji">{{ MODE_EMOJI[m.mode] || '🧭' }}</div>
          <div class="mode-name">{{ m.mode_name }}</div>
          <div class="mode-desc">{{ m.description }}</div>
          <div class="mode-foot">
            <span class="small muted">{{ m.budget_hint }}</span>
            <button class="btn btn-soft btn-sm">选它</button>
          </div>
          <div class="mode-cost">整体开销预估 ≈ ¥{{ modeTotal(m.mode) }}（2 天）</div>
        </div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
    </section>

    <!-- 游学路线入口（G7 / T9） -->
    <section v-if="studyRoutes.length" class="section">
      <router-link to="/study" class="study-banner">
        <div class="sb-icon">🎓</div>
        <div class="sb-copy">
          <div class="sb-eyebrow">预设主题路线 · 游学线</div>
          <h3>{{ studyRoutes[0].title }}</h3>
          <p>{{ studyRoutes[0].subtitle }} · 逐站讲解、研学任务卡、入校预约提醒，支持「半天游学 + 半天自由游」一键成程</p>
          <div class="sb-meta">
            <span>约 {{ studyRoutes[0].duration_hours }} 小时</span>
            <span>{{ studyRoutes[0].stop_count }} 站</span>
            <span :class="studyRoutes[0].day.tone">
              {{ studyRoutes[0].day.date }} · {{ studyRoutes[0].day.day_type }}：{{ studyRoutes[0].day.note }}
            </span>
          </div>
        </div>
        <div class="sb-cta">查看路线 →</div>
      </router-link>
    </section>

    <!-- 精选资源 -->
    <section class="section">
      <div class="section-head">
        <div>
          <h2 class="section-title">花溪精选</h2>
          <div class="section-sub">来自资源库的高分地点，也是行程算法的候选池</div>
        </div>
        <router-link to="/explore" class="small brand-text">浏览全部资源 →</router-link>
      </div>
      <div class="grid grid-3">
        <router-link
          v-for="p in hotPois" :key="p.id" to="/explore"
          class="card card-hover poi-card"
        >
          <div class="poi-card-cover">
            <img v-if="p.images && p.images.length" :src="p.images[0]" :alt="p.name" loading="lazy" />
            <div v-else class="poi-card-fallback">{{ p.name.slice(0, 2) }}</div>
          </div>
          <div class="poi-card-body">
            <div class="poi-card-top">
              <span class="tag">{{ CATEGORY_NAME[p.category] || p.category }}</span>
              <span class="rating">★ {{ p.rating?.toFixed(1) }}</span>
            </div>
            <div class="poi-name">{{ p.name }}</div>
            <div class="small muted">{{ p.sub_type }} · {{ p.address || '花溪区' }}</div>
            <div class="poi-foot">
              <span>{{ p.suggest_duration_min }} 分钟</span>
              <span>{{ p.ticket_price > 0 ? '¥' + p.ticket_price : '免费' }}</span>
            </div>
          </div>
        </router-link>
      </div>
    </section>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, #2f7d5c 0%, #3d9470 55%, #65ae8d 100%);
  color: #fff;
  padding: 64px 0 72px;
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: ''; position: absolute; right: -120px; top: -120px;
  width: 420px; height: 420px; border-radius: 50%;
  background: rgba(255, 255, 255, .07);
}
.hero-inner { display: grid; grid-template-columns: 1.15fr .85fr; gap: 48px; align-items: center; }
.hero-badge {
  display: inline-block; padding: 5px 14px; border-radius: 999px;
  background: rgba(255, 255, 255, .18); font-size: 13px; letter-spacing: 2px;
}
.hero h1 { font-size: 46px; line-height: 1.25; margin: 18px 0; font-weight: 800; letter-spacing: 1px; }
.hero h1 .brand-text { color: #e8f8ef; }
.hero-desc { max-width: 520px; font-size: 15px; opacity: .92; line-height: 1.85; }
.hero-actions { display: flex; gap: 12px; margin-top: 28px; flex-wrap: wrap; }
.hero .btn-outline { border-color: #fff; color: #fff; }
.hero .btn-outline:hover { background: rgba(255, 255, 255, .15); }
.hero .btn-primary { background: #fff; color: var(--brand-dark); }
.hero .btn-primary:hover { background: #eef7f2; }
.hero-panel {
  background: rgba(255, 255, 255, .14);
  border: 1px solid rgba(255, 255, 255, .25);
  border-radius: 20px; padding: 26px; backdrop-filter: blur(6px);
}
.panel-title { font-weight: 700; margin-bottom: 16px; }
.stat-row { display: flex; justify-content: space-between; text-align: center; }
.stat { display: flex; flex-direction: column; }
.stat b { font-size: 30px; font-weight: 800; }
.stat span { font-size: 12px; opacity: .85; }
.hero-panel .divider { background: rgba(255, 255, 255, .22); }
.flow { display: flex; flex-direction: column; gap: 10px; }
.flow-step { display: flex; align-items: center; gap: 10px; font-size: 14px; }
.flow-step i {
  width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(255, 255, 255, .25); font-style: normal; font-size: 12px; font-weight: 700;
}
.panel-note { margin-top: 18px; font-size: 12px; opacity: .8; line-height: 1.7; }

.mode-card { cursor: pointer; display: flex; flex-direction: column; min-height: 210px; }
.mode-emoji { font-size: 34px; margin-bottom: 8px; }
.mode-name { font-size: 19px; font-weight: 700; margin-bottom: 6px; }
.mode-desc { font-size: 13px; color: var(--muted); line-height: 1.7; flex: 1; }
.mode-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 14px; }
.mode-cost {
  margin-top: 10px; font-size: 12px; font-weight: 700; color: var(--brand);
  background: var(--brand-light, #e8f3ee); border-radius: 999px; padding: 4px 10px; align-self: flex-start;
}
.study-banner {
  display: flex; align-items: center; gap: 20px; padding: 22px 26px;
  border-radius: 16px; border: 1px solid #dfeae3;
  background: linear-gradient(110deg, #eef7f1 0%, #f8faf6 60%, #fff7e8 100%);
  transition: transform .15s ease, box-shadow .15s ease;
}
.study-banner:hover { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(28, 60, 46, .1); }
.sb-icon { font-size: 40px; flex-shrink: 0; }
.sb-copy { flex: 1; min-width: 0; }
.sb-eyebrow { font-size: 11px; font-weight: 700; color: var(--brand); letter-spacing: .5px; }
.sb-copy h3 { font-size: 19px; color: var(--brand-dark); margin: 5px 0 6px; }
.sb-copy p { font-size: 13px; color: #4c5d54; line-height: 1.7; }
.sb-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.sb-meta span { font-size: 11px; color: #5b6b64; background: rgba(255,255,255,.85); border-radius: 999px; padding: 4px 10px; }
.sb-meta span.warn { color: #95591a; background: #fff1dc; }
.sb-cta { white-space: nowrap; font-size: 14px; font-weight: 700; color: var(--brand); }
@media (max-width: 720px) {
  .study-banner { flex-wrap: wrap; }
  .sb-cta { width: 100%; }
}
.poi-card { display: block; padding: 0; overflow: hidden; }
.poi-card-cover {
  width: 100%; aspect-ratio: 16 / 9; overflow: hidden;
  background: linear-gradient(135deg, #e8f0f8, #d7e5f2);
}
.poi-card-cover img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .35s ease; }
.poi-card:hover .poi-card-cover img { transform: scale(1.05); }
.poi-card-fallback {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 700; color: rgba(255, 255, 255, .92);
  background: linear-gradient(135deg, #3d9470, #2f7d5c);
}
.poi-card-body { padding: 14px 16px 16px; }
.poi-card-top { display: flex; justify-content: space-between; align-items: center; }
.rating { color: var(--accent); font-size: 13px; font-weight: 700; }
.poi-name { font-size: 17px; font-weight: 700; margin: 10px 0 4px; }
.poi-foot {
  display: flex; justify-content: space-between; margin-top: 14px;
  padding-top: 12px; border-top: 1px solid var(--line);
  font-size: 13px; color: var(--brand); font-weight: 600;
}
@media (max-width: 900px) {
  .hero-inner { grid-template-columns: 1fr; gap: 28px; }
  .hero h1 { font-size: 34px; }
}
</style>
