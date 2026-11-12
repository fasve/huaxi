const api = require('../../utils/api');

const MODE_EMOJI = {
  leisure: '🌿',
  blitz: '⚡',
  premium: '✨',
  checkin: '📸',
};

Page({
  data: {
    mode: 'checkin',
    // 行程规模（从定制页带入，生成时生效；PC 端同口径）
    daysOptions: [1, 2, 3, 4, 5, 6, 7],
    daysIndex: 1,
    days: 2,
    budget: 1200,
    modes: [
      { key: 'leisure', label: '休闲游' },
      { key: 'blitz', label: '特种兵游' },
      { key: 'premium', label: '高端游' },
      { key: 'checkin', label: '打卡游' },
    ],
    dimensions: [],
    presets: [],
    eveningPrefs: [],
    sliders: [],
    sliderMap: {},
    percentMap: {},
    sliderTotal: 0,
    pace: { daily_poi_max: 4, play_hours_max: 9, evening: '' },
    preview: [],
    changed: [],
    personalized: false,
    loading: true,
    previewing: false,
    submitting: false,
    targetTripId: '',
  },

  onLoad(options) {
    this.setData({ targetTripId: options.trip || '' });
    if (options.mode) this.setData({ mode: options.mode });
    // 从定制页带入的天数 / 预算（缺省 2 天 / ¥1200）
    if (options.days) {
      const d = Number(options.days);
      const idx = this.data.daysOptions.indexOf(d);
      if (idx >= 0) this.setData({ days: d, daysIndex: idx });
    }
    if (options.budget) {
      const b = Number(options.budget);
      if (b > 0) this.setData({ budget: b });
    }
    wx.setNavigationBarTitle({ title: '个性化 · 按权重调整路线' });
    this.loadMeta();
  },

  onDays(e) {
    const i = Number(e.detail.value);
    this.setData({ daysIndex: i, days: this.data.daysOptions[i] });
  },

  onBudget(e) {
    this.setData({ budget: Number(e.detail.value) || 0 });
  },

  loadMeta() {
    api
      .getWeightMetadata()
      .then((meta) => {
        const mode = this.data.mode;
        const defs = meta.modes[mode] || {};
        const sliderMap = defs.slider_defaults || {};
        const dimensions = (meta.dimensions || []).map((d) => ({
          key: d.key,
          label: d.label,
          icon: d.icon,
          desc: d.desc,
          hint: d.hint,
          value: sliderMap[d.key] || 0,
        }));
        this.setData({
          dimensions,
          sliderMap,
          presets: meta.presets || [],
          eveningPrefs: meta.evening_preferences || [],
          pace: {
            daily_poi_max: defs.daily_poi_max || 3,
            play_hours_max: defs.play_hours_max || 6,
            evening: '',
          },
          loading: false,
        });
        this.recalcPercent();
        this.runPreview();
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 按关注度总和重算各维度占比 */
  recalcPercent() {
    const sliders = this.data.dimensions;
    const total = sliders.reduce((a, b) => a + (b.value || 0), 0);
    const percentMap = {};
    sliders.forEach((d) => {
      percentMap[d.key] = total > 0 ? Math.round(((d.value || 0) / total) * 100) : 0;
    });
    this.setData({ sliderTotal: total, percentMap });
  },

  onSlider(e) {
    const key = e.currentTarget.dataset.key;
    const value = Number(e.detail.value);
    const dimensions = this.data.dimensions.map((d) =>
      d.key === key ? Object.assign({}, d, { value }) : d,
    );
    this.setData({ dimensions });
    this.recalcPercent();
    this.schedulePreview();
  },

  schedulePreview() {
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(() => this.runPreview(), 400);
  },

  runPreview() {
    this.setData({ previewing: true });
    api
      .previewWeights({
        mode: this.data.mode,
        weights: this.buildWeights(),
        pace: this.data.pace,
        top_k: 10,
      })
      .then((res) => {
        this.setData({
          preview: res.items || [],
          changed: res.changed || [],
          personalized: res.is_personalized,
          previewing: false,
        });
      })
      .catch(() => this.setData({ previewing: false }));
  },

  buildWeights() {
    const out = {};
    this.data.dimensions.forEach((d) => {
      out[d.key] = d.value || 0;
    });
    return out;
  },

  /** 切换模式：滑块重置为该模式默认权重 */
  switchMode(e) {
    const mode = e.currentTarget.dataset.mode;
    api.getWeightMetadata().then((m) => {
      const defs = (m.modes[mode] || {}).slider_defaults || {};
      const dimensions = this.data.dimensions.map((d) =>
        Object.assign({}, d, { value: defs[d.key] || 0 }),
      );
      const paceDefaults = m.modes[mode] || {};
      this.setData({
        mode,
        dimensions,
        pace: {
          daily_poi_max: paceDefaults.daily_poi_max || 3,
          play_hours_max: paceDefaults.play_hours_max || 6,
          evening: '',
        },
      });
      this.recalcPercent();
      this.runPreview();
    });
  },

  /** 套用预设模板 */
  applyPreset(e) {
    const key = e.currentTarget.dataset.key;
    const preset = this.data.presets.find((p) => p.key === key);
    if (!preset) return;
    if (preset.key === 'balanced') {
      api.getWeightMetadata().then((m) => {
        const defs = (m.modes[this.data.mode] || {}).slider_defaults || {};
        const dimensions = this.data.dimensions.map((d) =>
          Object.assign({}, d, { value: defs[d.key] || 0 }),
        );
        this.setData({ dimensions });
        this.recalcPercent();
        this.runPreview();
      });
      return;
    }
    const dimensions = this.data.dimensions.map((d) =>
      Object.assign({}, d, { value: preset.weights[d.key] || 0 }),
    );
    this.setData({ dimensions });
    this.recalcPercent();
    this.runPreview();
  },

  onPoiMax(e) {
    this.setData({ 'pace.daily_poi_max': Number(e.detail.value) });
    this.schedulePreview();
  },
  onPlayHours(e) {
    this.setData({ 'pace.play_hours_max': Number(e.detail.value) });
    this.schedulePreview();
  },
  setEvening(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ 'pace.evening': this.data.pace.evening === key ? '' : key });
    this.schedulePreview();
  },

  /** 生成个性化行程（无目标行程时新建） */
  generate() {
    if (this.data.submitting) return;
    if (this.data.budget <= 0) {
      wx.showToast({ title: '请输入有效预算', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    api
      .generateTrip({
        days: this.data.days,
        budget: this.data.budget,
        mode: this.data.mode,
        party_type: 'couple',
        preferences: [],
        seed: Math.floor(Math.random() * 9999),
        weights: this.buildWeights(),
        pace: this.data.pace,
      })
      .then((trip) => {
        this.setData({ submitting: false });
        wx.showToast({ title: '个性化行程已生成', icon: 'success' });
        wx.redirectTo({ url: '/pages/trip/trip?id=' + trip.trip_id });
      })
      .catch((e) => {
        this.setData({ submitting: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 按新权重重排既有行程 */
  reweight() {
    if (this.data.submitting || !this.data.targetTripId) return;
    this.setData({ submitting: true });
    api
      .reweightTrip(this.data.targetTripId, {
        weights: this.buildWeights(),
        pace: this.data.pace,
      })
      .then(() => {
        this.setData({ submitting: false });
        wx.showToast({ title: '已按新权重重排路线', icon: 'success' });
        wx.redirectTo({ url: '/pages/trip/trip?id=' + this.data.targetTripId });
      })
      .catch((e) => {
        this.setData({ submitting: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },
});
