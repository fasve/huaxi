// 游学路线（预设主题路线）：逐站讲解 / 研学任务卡 / date_gate / 一键成程
const api = require('../../utils/api');

const MODE_OPTIONS = [
  { key: 'leisure', label: '🌿 休闲游' },
  { key: 'blitz', label: '⚡ 特种兵游' },
  { key: 'premium', label: '✨ 高端游' },
  { key: 'checkin', label: '📸 打卡游' },
];

const GATE_META = {
  open: { label: '正常开放', cls: 'ok' },
  reminder: { label: '需预约', cls: 'info' },
  degraded: { label: '已降级', cls: 'warn' },
  replaced: { label: '已替换', cls: 'warn' },
};

function today() {
  const d = new Date();
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-');
}

function buildStops(detail, addon) {
  const all = (detail.stops || []).concat(addon ? (detail.addon_stops || []) : []);
  return all
    .sort((a, b) => a.seq - b.seq)
    .map((s) => {
      const g = s.gate || {};
      const meta = GATE_META[g.status] || GATE_META.open;
      return Object.assign({}, s, {
        gateLabel: meta.label,
        gateCls: meta.cls,
        replaced: !!g.replaced,
        stayText: (s.effective_stay_min || s.stay_min) + ' 分钟',
        slotText: s.slot === 'morning' ? '上午' : '下午',
        tasks: s.task_cards || [],
        gateNotes: g.notes || [],
        tagText: s.is_addon ? '深度加段' : (s.must_visit ? '' : '弹性站'),
      });
    });
}

Page({
  data: {
    visitDate: today(),
    routes: [],
    detail: null,
    stops: [],
    gateNotes: [],
    dayLabel: '',
    dayNote: '',
    dayTone: 'ok',
    includeAddon: false,
    modeNames: MODE_OPTIONS.map((m) => m.label),
    modeIndex: 0,
    days: 1,
    budget: 600,
    loading: true,
    submitting: false,
  },

  onLoad() {
    this.loadAll();
  },

  onPullDownRefresh() {
    this.loadAll().then(() => wx.stopPullDownRefresh());
  },

  loadAll() {
    this.setData({ loading: true });
    return api
      .getPresetRoutes({ visit_date: this.data.visitDate })
      .then((res) => {
        const routes = res.items || [];
        this.setData({ routes, loading: false });
        if (!routes.length) {
          this.setData({ detail: null, stops: [] });
          return null;
        }
        return this.loadDetail(routes[0].code);
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message || '线路加载失败', icon: 'none' });
      });
  },

  loadDetail(code) {
    return api
      .getPresetRoute(code, { visit_date: this.data.visitDate })
      .then((detail) => {
        const day = detail.day || {};
        this.setData({
          detail,
          stops: buildStops(detail, this.data.includeAddon),
          gateNotes: detail.gate_notes || [],
          dayLabel: (day.date || '') + ' 周' + (day.weekday || '') + ' · ' + (day.day_type || ''),
          dayNote: day.note || '',
          dayTone: day.tone === 'warn' ? 'warn' : 'ok',
        });
      })
      .catch((e) => {
        wx.showToast({ title: e.message || '站点加载失败', icon: 'none' });
      });
  },

  onDateChange(e) {
    this.setData({ visitDate: e.detail.value }, () => this.loadAll());
  },

  pickRoute(e) {
    const code = e.currentTarget.dataset.code;
    this.loadDetail(code);
  },

  onAddon(e) {
    const includeAddon = e.detail.value;
    this.setData({
      includeAddon,
      stops: this.data.detail ? buildStops(this.data.detail, includeAddon) : [],
    });
  },

  onMode(e) {
    this.setData({ modeIndex: Number(e.detail.value) });
  },

  onDays(e) {
    this.setData({ days: Number(e.detail.value) });
  },

  onBudget(e) {
    this.setData({ budget: Number(e.detail.value) || 0 });
  },

  generate() {
    if (!this.data.detail) return;
    if (this.data.budget <= 0) {
      wx.showToast({ title: '请输入有效预算', icon: 'none' });
      return;
    }
    const mode = MODE_OPTIONS[this.data.modeIndex].key;
    this.setData({ submitting: true });
    api
      .generateTrip({
        days: this.data.days,
        budget: this.data.budget,
        mode,
        preferences: [],
        party_type: mode === 'premium' ? 'couple' : 'family',
        seed: Math.floor(Math.random() * 9999),
        preset_route_code: this.data.detail.code,
        visit_date: this.data.visitDate,
        include_addon: this.data.includeAddon,
      })
      .then((trip) => {
        wx.navigateTo({ url: '/pages/trip/trip?id=' + trip.trip_id });
      })
      .catch((e) => {
        wx.showToast({ title: e.message || '生成失败', icon: 'none' });
      })
      .then(() => this.setData({ submitting: false }));
  },
});
