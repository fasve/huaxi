// 首页：模式入口 + 实时天气 + 游学线入口 + 花溪精选
// 与 PC 端 travel-portal/src/views/Home.vue 对齐（天气、系统能力、模式开销预估、资源入口）
const api = require('../../utils/api');
const cost = require('../../utils/cost');

// 后端 open_meteo 的 icon 取值 → 展示用图形
const WEATHER_EMOJI = {
  sun: '☀️', partly: '⛅', overcast: '☁️', fog: '🌫️',
  rain: '🌧️', heavyrain: '⛈️', snow: '❄️', thunder: '⚡',
};

Page({
  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 0 });
    }
  },

  data: {
    modes: [],
    hotPois: [],
    totalPois: 0,
    studyTitle: '',
    studySub: '',
    studyDay: '',
    loading: true,
    poiDetail: null,
    // 天气（默认花溪区；一期不采集精确定位）
    weather: null,
    weatherError: '',
    casts: [],
  },

  onLoad() {
    this.fetchAll();
  },

  onPullDownRefresh() {
    this.fetchAll().then(() => wx.stopPullDownRefresh());
  },

  fetchAll() {
    this.setData({ loading: true });
    return Promise.all([
      api.getModes(),
      api.listPois({ page_size: 6, min_rating: 4.5 }),
      api.getPresetRoutes().catch(() => ({ items: [] })),
      api.getTags().catch(() => []),
      // 单独取一次总数（上面那 6 条带了评分筛选，total 不是全库口径）
      api.listPois({ page_size: 1 }).catch(() => ({ total: 0 })),
      this.fetchWeather(),
    ])
      .then(([modes, pois, routes, tags, all]) => {
        const tagMap = {};
        (tags || []).forEach((t) => { tagMap[t.code] = t.name; });
        const r = (routes.items || [])[0];
        this.setData({
          modes: this.decorateModes(modes),
          hotPois: (pois.items || []).map((p) => Object.assign({}, p, {
            category_name: api.CATEGORY_NAME[p.category] || p.category,
            rating_text: p.rating ? Number(p.rating).toFixed(1) : '—',
            price_text: p.ticket_price > 0 ? '¥' + p.ticket_price : '免费',
            duration_text: p.suggest_duration_min ? p.suggest_duration_min + ' 分钟' : '',
            tag_names: (p.tags || []).map((c) => tagMap[c] || c),
            initial: (p.name || '').slice(0, 2),
          })),
          totalPois: all.total || 0,
          studyTitle: r ? r.title : '',
          studySub: r ? r.subtitle : '',
          studyDay: r ? (r.day.date + ' · ' + r.day.day_type + '：' + r.day.note) : '',
          loading: false,
        });
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 模式卡片上直接给出「2 天」的整体开销预估，选模式时就能判断预算够不够 */
  decorateModes(modes) {
    return (modes || []).map((m) => {
      const est = cost.estimateCost(cost.cloneDefaults(m.mode), 2, 1200);
      return Object.assign({}, m, {
        emoji: api.MODE_EMOJI[m.mode] || '🧭',
        estimate2d: est.total,
      });
    });
  },

  // ---------------- 天气（Open-Meteo，服务端代理，免密钥） ----------------

  fetchWeather() {
    return api
      .getWeather({ days: 15 })
      .then((w) => {
        if (!w || w.available === false || !w.live) {
          this.setData({
            weather: null,
            casts: [],
            weatherError: (w && (w.message || w.error)) || '天气服务暂不可用',
          });
          return;
        }
        const casts = (w.casts || []).map((c) => ({
          date: c.date,
          week: c.week,
          day: c.dayweather,
          night: c.nightweather,
          daytemp: c.daytemp,
          nighttemp: c.nighttemp,
          emoji: WEATHER_EMOJI[c.icon] || '⛅',
          precip: c.precip === null || c.precip === undefined ? '' : c.precip + '%',
          short_date: (c.date || '').slice(5),
        }));
        this.setData({ weather: w.live, casts, weatherError: '' });
      })
      .catch((e) => {
        this.setData({ weather: null, casts: [], weatherError: e.message || '天气服务暂不可用' });
      });
  },

  // ---------------- 交互 ----------------

  /** 选模式 → 进定制 tab（tabBar 页不能带参数，走 globalData） */
  pickMode(e) {
    const mode = e.currentTarget.dataset.mode;
    const app = getApp();
    if (app.globalData) app.globalData.pendingMode = mode;
    wx.switchTab({ url: '/pages/request/request' });
  },

  goPlan() {
    wx.switchTab({ url: '/pages/request/request' });
  },

  goExplore() {
    wx.switchTab({ url: '/pages/explore/explore' });
  },

  goCompare() {
    wx.navigateTo({ url: '/pages/compare/compare' });
  },

  goStudy() {
    wx.navigateTo({ url: '/pages/study/study' });
  },

  goChat() {
    wx.navigateTo({
      url: '/pages/chat/chat',
      fail(err) {
        // 常见原因：开发者工具没重新编译（app.json 里还没有这个页面）
        wx.showToast({
          title: '问答页打不开：' + ((err && err.errMsg) || '请先点「编译」'),
          icon: 'none',
          duration: 2500,
        });
      },
    });
  },

  // ---------------- POI 详情 ----------------

  openPoi(e) {
    const id = Number(e.currentTarget.dataset.id);
    const poi = this.data.hotPois.find((p) => Number(p.id) === id);
    if (!poi) return;
    this.setData({ poiDetail: poi });
  },

  closePoi() {
    this.setData({ poiDetail: null });
  },

  stopEvent() {},

  navToPoi() {
    const p = this.data.poiDetail;
    if (!p || !p.latitude || !p.longitude) {
      wx.showToast({ title: '暂无坐标', icon: 'none' });
      return;
    }
    wx.openLocation({
      latitude: Number(p.latitude),
      longitude: Number(p.longitude),
      name: p.name,
      address: p.address || '',
      scale: 16,
    });
  },
});
