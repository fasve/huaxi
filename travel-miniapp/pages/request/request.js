// 定制行程（T2 需求录入）+ 模式小部件与整体开销预估
// 与 PC 端 travel-portal/src/views/Plan.vue + ModeConfigurator.vue + cost.ts 对齐：
//   选模式 → 微调住宿/餐饮/交通/晚间/节奏 → 实时看到「整体开销」与预算贴合度 → 生成
const api = require('../../utils/api');
const cost = require('../../utils/cost');

const DAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7];
const QUICK_BUDGETS = [300, 800, 1500, 3000];

// 小部件分组（selectedKey 直接对应 parts 字段）
const GROUPS = [
  { key: 'hotel', label: '🏨 住宿档位', options: cost.HOTEL_TIERS },
  { key: 'dining', label: '🍽 餐饮标准', options: cost.DINING_STANDARDS },
  { key: 'transport', label: '🚌 出行交通', options: cost.TRANSPORT_MODES },
  { key: 'evening', label: '🌙 晚间安排', options: cost.EVENING_OPTIONS },
];

const ESTIMATE_ROWS = [
  { key: 'hotel', label: '🏨 住宿', note: 'n 晚' },
  { key: 'dining', label: '🍽 餐饮', note: '' },
  { key: 'tickets', label: '🎫 门票', note: '' },
  { key: 'transport', label: '🚌 交通', note: '' },
  { key: 'evening', label: '🌙 晚间', note: '' },
];

Page({
  data: {
    modes: [],
    mode: 'leisure',
    modeName: '休闲游',
    modeDesc: '',
    daysOptions: DAY_OPTIONS,
    daysIndex: 1,
    days: 2,
    budget: 1200,
    quickBudgets: QUICK_BUDGETS,
    partyTypes: api.PARTY_TYPES,
    partyIndex: 0,
    partyType: api.PARTY_TYPES[0].code,
    tags: [],
    selectedPrefs: [],
    // 小部件与预估
    showConfig: false,
    groups: [],
    parts: null,
    estimate: null,
    estimateFitText: '',
    estimateRows: [],
    submitting: false,
  },

  onLoad(options) {
    if (options && options.mode) {
      this.setData({ mode: options.mode });
    }
    this.setData({ parts: cost.cloneDefaults(this.data.mode) });
    this.loadModes();
    this.loadTags();
    this.refreshModeInfo();
    this.refreshGroups();
    this.recalc();
  },

  /** 从「四模式对比」「首页模式卡」跳到本 tab 时，用 globalData 传参（switchTab 不能带 query） */
  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 });
    }
    const app = getApp();
    if (!app.globalData) return;
    const mode = app.globalData.pendingMode;
    const plan = app.globalData.pendingPlan;
    if (!mode && !plan) return;

    const patch = {};
    if (mode) {
      patch.mode = mode;
      patch.parts = cost.cloneDefaults(mode);
    }
    if (plan) {
      if (plan.days) {
        const idx = DAY_OPTIONS.indexOf(Number(plan.days));
        patch.days = Number(plan.days);
        patch.daysIndex = idx >= 0 ? idx : 1;
      }
      if (plan.budget) patch.budget = Number(plan.budget);
      if (plan.partyType) {
        const pi = api.PARTY_TYPES.findIndex((p) => p.code === plan.partyType);
        patch.partyType = plan.partyType;
        patch.partyIndex = pi >= 0 ? pi : 0;
      }
      if (plan.prefs && plan.prefs.length) patch.selectedPrefs = plan.prefs.slice();
    }
    app.globalData.pendingMode = '';
    app.globalData.pendingPlan = null;
    this.setData(patch);
    this.refreshModeInfo();
    this.refreshGroups();
    this.recalc();
  },

  // ---------------- 数据加载 ----------------

  loadModes() {
    api
      .getModes()
      .then((modes) => {
        this.setData({ modes: this.decorateModes(modes) });
        this.refreshModeInfo();
      })
      .catch((e) => wx.showToast({ title: e.message, icon: 'none' }));
  },

  /** 偏好标签取后端字典（code 必须与 poi_tag 一致，否则筛选会把候选池筛空） */
  loadTags() {
    api
      .getTags()
      .then((tags) => this.setData({ tags }))
      .catch(() => {});
  },

  decorateModes(modes) {
    const { days, budget } = this.data;
    return (modes || []).map((m) => {
      const est = cost.estimateCost(cost.cloneDefaults(m.mode), days, budget);
      return Object.assign({}, m, {
        emoji: api.MODE_EMOJI[m.mode] || '🧭',
        estimate: est.total,
        over: est.total > budget,
      });
    });
  },

  refreshModeInfo() {
    const m = (this.data.modes || []).find((x) => x.mode === this.data.mode);
    if (m) {
      this.setData({ modeName: m.mode_name, modeDesc: m.description });
    }
  },

  /** 生成小部件分组（每个选项带 on 标记，避免 WXML 里做动态取值） */
  refreshGroups() {
    const parts = this.data.parts || {};
    const groups = GROUPS.map((g) => ({
      key: g.key,
      label: g.label,
      options: g.options.map((o) => ({
        key: o.key,
        label: o.label,
        desc: o.desc,
        on: parts[g.key] === o.key,
      })),
    }));
    this.setData({ groups });
  },

  /** 重算整体开销 + 各模式卡片上的预估 */
  recalc() {
    const { parts, days, budget, modes } = this.data;
    if (!parts) return;
    const est = cost.estimateCost(parts, days, budget);
    const fitText = est.fit === 'over' ? '超出预算'
      : est.fit === 'slight' ? '略超预算' : '预算内';
    const rows = ESTIMATE_ROWS.map((r) => ({
      label: r.label,
      value: est[r.key],
      note: r.note === 'n 晚' ? est.nights + ' 晚' : '',
    }));
    const nextModes = (modes || []).map((m) => {
      const e = cost.estimateCost(cost.cloneDefaults(m.mode), days, budget);
      return Object.assign({}, m, { estimate: e.total, over: e.total > budget });
    });
    this.setData({
      estimate: est, estimateFitText: fitText, estimateRows: rows, modes: nextModes,
    });
  },

  // ---------------- 基础条件 ----------------

  pickMode(e) {
    const mode = e.currentTarget.dataset.mode;
    if (mode === this.data.mode) return;
    this.setData({ mode, parts: cost.cloneDefaults(mode) });
    this.refreshModeInfo();
    this.refreshGroups();
    this.recalc();
  },

  onDays(e) {
    const i = Number(e.detail.value);
    this.setData({ daysIndex: i, days: DAY_OPTIONS[i] });
    this.recalc();
  },

  /** 天数用胶囊直选（比滑杆少一次拖拽） */
  pickDays(e) {
    const d = Number(e.currentTarget.dataset.day);
    const i = DAY_OPTIONS.indexOf(d);
    if (i < 0) return;
    this.setData({ days: d, daysIndex: i });
    this.recalc();
  },

  onBudget(e) {
    this.setData({ budget: Number(e.detail.value) || 0 });
    this.recalc();
  },

  pickBudget(e) {
    this.setData({ budget: Number(e.currentTarget.dataset.value) });
    this.recalc();
  },

  pickParty(e) {
    const code = e.currentTarget.dataset.code;
    const i = api.PARTY_TYPES.findIndex((p) => p.code === code);
    this.setData({ partyType: code, partyIndex: i >= 0 ? i : 0 });
  },

  togglePref(e) {
    const code = e.currentTarget.dataset.code;
    const sel = this.data.selectedPrefs.slice();
    const i = sel.indexOf(code);
    if (i >= 0) sel.splice(i, 1);
    else sel.push(code);
    this.setData({ selectedPrefs: sel });
  },

  // ---------------- 小部件 ----------------

  toggleConfig() {
    this.setData({ showConfig: !this.data.showConfig });
  },

  pickPart(e) {
    const group = e.currentTarget.dataset.group;
    const key = e.currentTarget.dataset.key;
    const parts = Object.assign({}, this.data.parts, { [group]: key });
    this.setData({ parts });
    this.refreshGroups();
    this.recalc();
  },

  onDailyPoi(e) {
    const parts = Object.assign({}, this.data.parts, { daily_poi: Number(e.detail.value) });
    this.setData({ parts });
    this.recalc();
  },

  onPlayHours(e) {
    const parts = Object.assign({}, this.data.parts, { play_hours: Number(e.detail.value) });
    this.setData({ parts });
    this.recalc();
  },

  // ---------------- 提交 ----------------

  payload() {
    const { days, budget, mode, partyType, selectedPrefs, parts } = this.data;
    const extra = cost.partsToPayload(parts);
    return {
      days,
      budget,
      mode,
      party_type: partyType,
      preferences: selectedPrefs.slice(),
      seed: Math.floor(Math.random() * 9999),
      pace: extra.pace,
      cost_prefs: extra.cost_prefs,
    };
  },

  submit() {
    const { days, budget } = this.data;
    if (days < 1 || days > 7) {
      wx.showToast({ title: '天数需在 1-7 天', icon: 'none' });
      return;
    }
    if (budget <= 0) {
      wx.showToast({ title: '请输入人均预算', icon: 'none' });
      return;
    }
    if (this.data.submitting) return;
    this.setData({ submitting: true });
    wx.showLoading({ title: '正在排行程…', mask: true });
    api
      .generateTrip(this.payload())
      .then((trip) => {
        wx.hideLoading();
        this.setData({ submitting: false });
        const app = getApp();
        if (app.globalData) app.globalData.lastTripId = trip.trip_id;
        wx.navigateTo({ url: '/pages/trip/trip?id=' + trip.trip_id });
      })
      .catch((e) => {
        wx.hideLoading();
        this.setData({ submitting: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  goCompare() {
    // 带上当前条件，对比页可直接出结果
    const prefs = this.data.selectedPrefs.join(',');
    wx.navigateTo({
      url: '/pages/compare/compare?days=' + this.data.days
        + '&budget=' + this.data.budget
        + '&party=' + this.data.partyType
        + '&prefs=' + encodeURIComponent(prefs),
    });
  },

  goPersonalize() {
    wx.navigateTo({
      url: '/pages/personalize/personalize?mode=' + this.data.mode
        + '&days=' + this.data.days + '&budget=' + this.data.budget,
    });
  },
});
