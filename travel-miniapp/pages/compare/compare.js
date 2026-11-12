// 四模式对比（与 PC 端 travel-portal/src/views/Compare.vue 对齐）
// 同一组需求一次算出四种模式：并排指标 + 一眼看懂差异 + 一键采用某模式去定制
const api = require('../../utils/api');

const DAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7];

Page({
  data: {
    daysOptions: DAY_OPTIONS,
    daysIndex: 1,          // 默认 2 天
    days: 2,
    budget: 1200,
    partyTypes: api.PARTY_TYPES,
    partyIndex: 0,
    partyType: api.PARTY_TYPES[0].code,
    tags: [],
    selectedPrefs: [],
    results: [],
    insights: [],
    note: '',
    loading: false,
    compared: false,
    // 顶部四个模式小卡里当前选中的那一个
    activeIndex: 0,
    active: null,
  },

  onLoad(options) {
    this.loadTags().then(() => {
      // 从定制页带条件跳进来时，直接出结果
      const q = options || {};
      if (!q.days && !q.budget) return;
      const patch = {};
      if (q.days) {
        const d = Number(q.days);
        const idx = DAY_OPTIONS.indexOf(d);
        if (idx >= 0) {
          patch.days = d;
          patch.daysIndex = idx;
        }
      }
      if (q.budget) patch.budget = Number(q.budget) || 1200;
      if (q.party) {
        const pi = api.PARTY_TYPES.findIndex((p) => p.code === q.party);
        if (pi >= 0) {
          patch.partyIndex = pi;
          patch.partyType = q.party;
        }
      }
      if (q.prefs) {
        const prefs = decodeURIComponent(q.prefs).split(',').filter(Boolean);
        if (prefs.length) patch.selectedPrefs = prefs;
      }
      this.setData(patch);
      this.run();
    });
  },

  /** 偏好标签直接用后端字典，避免 code 与 poi_tag 对不上导致筛不动候选 */
  loadTags() {
    return api
      .getTags()
      .then((tags) => this.setData({ tags }))
      .catch(() => {});
  },

  onDays(e) {
    const i = Number(e.detail.value);
    this.setData({ daysIndex: i, days: DAY_OPTIONS[i] });
  },

  onBudget(e) {
    this.setData({ budget: Number(e.detail.value) || 0 });
  },

  onParty(e) {
    const i = Number(e.detail.value);
    this.setData({ partyIndex: i, partyType: api.PARTY_TYPES[i].code });
  },

  togglePref(e) {
    const code = e.currentTarget.dataset.code;
    const sel = this.data.selectedPrefs.slice();
    const i = sel.indexOf(code);
    if (i >= 0) sel.splice(i, 1);
    else sel.push(code);
    this.setData({ selectedPrefs: sel });
  },

  run() {
    if (this.data.budget <= 0) {
      wx.showToast({ title: '请输入有效预算', icon: 'none' });
      return;
    }
    if (this.data.loading) return;
    this.setData({ loading: true });
    wx.showLoading({ title: '四种模式计算中…', mask: true });
    api
      .compare({
        days: this.data.days,
        budget: this.data.budget,
        preferences: this.data.selectedPrefs,
        party_type: this.data.partyType,
        seed: 42,
      })
      .then((res) => {
        wx.hideLoading();
        const results = (res.results || []).map((r) => this.decorate(r));
        this.setData({
          results,
          note: res.note || '',
          insights: this.buildInsights(results),
          compared: true,
          loading: false,
          activeIndex: 0,
          active: results[0] || null,
        });
      })
      .catch((e) => {
        wx.hideLoading();
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 补展示字段（WXML 里不能调用 Math.*，全部预先算好） */
  decorate(r) {
    const days = (r.days_plan || []).map((d) => ({
      day_index: d.day_index,
      theme: d.theme,
      poi_text: (d.poi_names || []).join(' → '),
    }));
    return Object.assign({}, r, {
      emoji: api.MODE_EMOJI[r.mode] || '🧭',
      usage_percent: Math.round((r.budget_usage || 0) * 100),
      free_percent: Math.round((r.free_poi_ratio || 0) * 100),
      total_cost: Math.round(r.total_cost || 0),
      poi_per_day: r.poi_per_day || 0,
      hotel_text: r.hotel || '不安排',
      days,
    });
  },

  /** 一眼看懂差异：最省钱 / 节奏最满 / 免费点最多 / 预算用得最足 */
  buildInsights(results) {
    if (results.length < 2) return [];
    let minCost = results[0];
    let maxPoi = results[0];
    let mostFree = results[0];
    let maxUsage = results[0];
    results.forEach((r) => {
      if (r.total_cost <= minCost.total_cost) minCost = r;
      if (r.poi_per_day >= maxPoi.poi_per_day) maxPoi = r;
      if ((r.free_poi_ratio || 0) >= (mostFree.free_poi_ratio || 0)) mostFree = r;
      if ((r.budget_usage || 0) >= (maxUsage.budget_usage || 0)) maxUsage = r;
    });
    return [
      '最省钱：' + minCost.mode_name + '（¥' + minCost.total_cost + '）',
      '节奏最满：' + maxPoi.mode_name + '（日均 ' + maxPoi.poi_per_day + ' 个点）',
      '免费点最多：' + mostFree.mode_name + '（占比 ' + Math.round((mostFree.free_poi_ratio || 0) * 100) + '%）',
      '预算用得最足：' + maxUsage.mode_name + '（' + Math.round((maxUsage.budget_usage || 0) * 100) + '%）',
    ];
  },

  /** 顶部小卡切换：只换下方详情，不重新请求 */
  pickMode(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const item = this.data.results[idx];
    if (!item || idx === this.data.activeIndex) return;
    this.setData({ activeIndex: idx, active: item });
  },

  /** 采用该模式去定制（需求页是 tabBar 页，参数走 globalData） */
  useMode(e) {
    const mode = e.currentTarget.dataset.mode;
    const app = getApp();
    app.globalData.pendingMode = mode;
    app.globalData.pendingPlan = {
      days: this.data.days,
      budget: this.data.budget,
      partyType: this.data.partyType,
      prefs: this.data.selectedPrefs.slice(),
    };
    wx.switchTab({ url: '/pages/request/request' });
  },
});
