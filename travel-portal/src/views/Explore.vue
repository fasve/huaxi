<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, CATEGORY_NAME, toast, type Poi } from '../api'
import { addToBasket } from '../basket'
import TMap from '../components/TMap.vue'
import type { MapPoint } from '../components/amap'

const categories = [
  { code: 'all', name: '全部' },
  { code: 'scenic', name: '景点' },
  { code: 'food', name: '美食' },
  { code: 'hotel', name: '住宿' },
  { code: 'leisure', name: '休闲' },
]

const query = reactive({
  category: 'all',
  keyword: '',
  min_rating: 0,
  price_level: 0,
  tags: '',
  page: 1,
  page_size: 12,
})

const rows = ref<Poi[]>([])
const total = ref(0)
const tags = ref<{ code: string; name: string }[]>([])
const loading = ref(false)
const detail = ref<Poi | null>(null)

/** 当前页资源在高德底图上的分布 */
const mapPoints = computed<MapPoint[]>(() => rows.value.map((p) => ({
  id: p.id,
  name: p.name,
  lng: p.longitude,
  lat: p.latitude,
  category: CATEGORY_NAME[p.category] || p.category,
  address: p.address,
})))

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: query.page, page_size: query.page_size,
    }
    if (query.category !== 'all') params.category = query.category
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.min_rating) params.min_rating = query.min_rating
    if (query.price_level) params.price_level = query.price_level
    if (query.tags) params.tags = query.tags
    const res = await api.listPois(params)
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function reset() {
  query.page = 1
  load()
}

function toggleTag(code: string) {
  query.tags = query.tags === code ? '' : code
  reset()
}

function openDetail(p: Poi) {
  detail.value = p
}

/** 加入「待计划」篮子（跨页 localStorage），到行程页一键排入某天 */
function addBasket(p: Poi) {
  const ok = addToBasket({
    poi_id: p.id, name: p.name, category: p.category,
    image: p.images?.[0] || null, address: p.address,
  })
  toast(ok ? '已加入待计划：去「我的行程」可排入某一天' : '这个点位已经在待计划里了', !ok)
}

watch(() => [query.category, query.min_rating, query.price_level], reset)
onMounted(async () => {
  tags.value = await api.getTags().catch(() => [])
  load()
})
</script>

<template>
  <div class="container">
    <section class="section">
      <div class="section-head">
        <div>
          <h1 class="section-title">发现花溪</h1>
          <div class="section-sub">系统的资源底座，也是行程算法的候选池 · 共 {{ total }} 条</div>
        </div>
      </div>

      <!-- 筛选 -->
      <div class="card filter-card no-print">
        <div class="filter-row">
          <div class="cat-tabs">
            <button
              v-for="c in categories" :key="c.code"
              class="chip" :class="{ on: query.category === c.code }"
              @click="query.category = c.code"
            >{{ c.name }}</button>
          </div>
          <div class="filter-inputs">
            <input
              v-model="query.keyword" class="input" placeholder="搜索名称 / 地址"
              @keyup.enter="reset" @clear="reset"
            />
            <select v-model.number="query.min_rating" class="select">
              <option :value="0">不限评分</option>
              <option :value="4">4.0 分以上</option>
              <option :value="4.5">4.5 分以上</option>
            </select>
            <select v-model.number="query.price_level" class="select">
              <option :value="0">不限价格</option>
              <option :value="1">经济（1 档）</option>
              <option :value="2">实惠（≤2 档）</option>
              <option :value="3">中档（≤3 档）</option>
            </select>
            <button class="btn btn-primary btn-sm" @click="reset">搜索</button>
          </div>
        </div>
        <div class="divider"></div>
        <div class="tag-row">
          <span class="small muted" style="margin-right: 8px">偏好标签</span>
          <button
            v-for="t in tags" :key="t.code"
            class="chip" :class="{ on: query.tags === t.code }"
            @click="toggleTag(t.code)"
          >{{ t.name }}</button>
        </div>
      </div>

      <!-- 资源分布地图 -->
      <TMap class="map-block" :points="mapPoints" :height="340" title="资源分布 · 当前页" />

      <!-- 列表 -->
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!rows.length" class="empty">没有符合条件的资源，试试放宽筛选条件</div>
      <div v-else class="grid grid-3 poi-grid">
        <div
          v-for="p in rows" :key="p.id"
          class="card card-hover poi-item" @click="openDetail(p)"
        >
          <div class="poi-cover">
            <img v-if="p.images && p.images.length" :src="p.images[0]" :alt="p.name" loading="lazy" />
            <div v-else class="poi-cover-fallback">{{ p.name.slice(0, 2) }}</div>
            <span class="poi-cover-cat">{{ CATEGORY_NAME[p.category] || p.category }}</span>
          </div>
          <div class="poi-body">
            <div class="poi-top">
              <span class="rating">★ {{ p.rating?.toFixed(1) }}</span>
            </div>
            <div class="poi-title">{{ p.name }}</div>
            <div class="small muted">{{ p.sub_type }} · {{ p.address || '花溪区' }}</div>
            <div class="poi-tags">
              <span v-for="t in (p.tags || []).slice(0, 3)" :key="t" class="tag gray">{{ t }}</span>
            </div>
            <div class="poi-meta">
              <span>约 {{ p.suggest_duration_min }} 分钟</span>
              <b>{{ p.ticket_price > 0 ? '¥' + p.ticket_price : '免费' }}</b>
              <button class="btn btn-soft btn-sm basket-btn" @click.stop="addBasket(p)">
                ＋ 待计划
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="pager no-print" v-if="total > query.page_size">
        <button class="btn btn-outline btn-sm" :disabled="query.page <= 1"
                @click="query.page--; load()">← 上一页</button>
        <span class="small muted">第 {{ query.page }} / {{ Math.ceil(total / query.page_size) }} 页</span>
        <button class="btn btn-outline btn-sm" :disabled="query.page * query.page_size >= total"
                @click="query.page++; load()">下一页 →</button>
      </div>
    </section>

    <!-- 详情弹层 -->
    <div v-if="detail" class="mask no-print" @click.self="detail = null">
      <div class="modal">
        <div class="section-head">
          <h2 class="section-title">{{ detail.name }}</h2>
          <button class="btn btn-sm" @click="detail = null">关闭</button>
        </div>
        <div>
          <span class="tag">{{ CATEGORY_NAME[detail.category] || detail.category }}</span>
          <span class="tag orange">{{ detail.sub_type }}</span>
          <span class="tag gray">★ {{ detail.rating?.toFixed(1) }}</span>
        </div>
        <div class="divider"></div>
        <div v-if="detail.images && detail.images.length" class="detail-gallery">
          <img
            v-for="(img, i) in detail.images" :key="img + i"
            :src="img" :alt="`${detail.name} 图${i + 1}`"
            loading="lazy"
          />
        </div>
        <div class="detail-grid">
          <div><span class="muted small">地址</span><div>{{ detail.address || '花溪区' }}</div></div>
          <div><span class="muted small">建议时长</span><div>{{ detail.suggest_duration_min }} 分钟</div></div>
          <div><span class="muted small">门票 / 人均</span><div>{{ detail.ticket_price > 0 ? '¥' + detail.ticket_price : '免费' }}</div></div>
          <div><span class="muted small">价格档</span><div>{{ detail.price_level }} 档</div></div>
          <div><span class="muted small">坐标</span><div>{{ detail.longitude?.toFixed(4) }}, {{ detail.latitude?.toFixed(4) }}</div></div>
          <div><span class="muted small">评价数</span><div>{{ detail.review_count ?? 0 }}</div></div>
        </div>
        <div class="divider"></div>
        <div class="small muted">关联标签</div>
        <div style="margin-top: 8px">
          <span v-for="t in (detail.tags || [])" :key="t" class="tag">{{ t }}</span>
          <span v-if="!detail.tags?.length" class="small muted">暂无标签</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-card { padding: 18px 22px; }
.filter-row { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.cat-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.filter-inputs { display: flex; gap: 8px; flex-wrap: wrap; }
.filter-inputs .input { width: 190px; }
.filter-inputs .select { width: 140px; }
.tag-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.tag-row .chip { padding: 4px 12px; font-size: 12px; }
.map-block { margin-top: 20px; }
.poi-grid { margin-top: 20px; }
.poi-item { cursor: pointer; display: flex; flex-direction: column; padding: 0; overflow: hidden; }
.poi-cover {
  position: relative; width: 100%; aspect-ratio: 16 / 9;
  background: linear-gradient(135deg, #e8f0f8, #d7e5f2); overflow: hidden;
}
.poi-cover img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .35s ease; }
.poi-item:hover .poi-cover img { transform: scale(1.05); }
.poi-cover-fallback {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  font-size: 30px; font-weight: 700; color: rgba(255, 255, 255, .92);
  background: linear-gradient(135deg, #4a90d9, #2f6fb0);
}
.poi-cover-cat {
  position: absolute; left: 10px; top: 10px;
  background: rgba(255, 255, 255, .92); color: var(--brand);
  font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 20px;
}
.poi-body { padding: 14px 16px 16px; display: flex; flex-direction: column; flex: 1; }
.poi-top { display: flex; justify-content: space-between; }
.rating { color: var(--accent); font-size: 13px; font-weight: 700; }
.poi-title { font-size: 17px; font-weight: 700; margin: 10px 0 4px; }
.poi-tags { margin-top: 10px; min-height: 22px; }
.poi-meta {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: auto; padding-top: 12px; border-top: 1px solid var(--line);
  font-size: 13px; color: var(--muted);
}
.poi-meta b { color: var(--brand); font-size: 15px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 24px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.detail-gallery {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px; margin-bottom: 16px;
}
.detail-gallery img {
  width: 100%; aspect-ratio: 4 / 3; object-fit: cover;
  border-radius: 8px; border: 1px solid var(--line);
}
@media (max-width: 640px) { .detail-grid { grid-template-columns: 1fr; } }
</style>
