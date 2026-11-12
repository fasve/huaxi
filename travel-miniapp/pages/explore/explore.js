// 发现花溪（T1 资源浏览）：与 PC 端 travel-portal/src/views/Explore.vue 对齐
// 分类 Tab + 关键字搜索 + 评分 / 价格档筛选 + 偏好标签 + 分页加载 + 地图分布 + 详情画廊
const api = require('../../utils/api');

const PAGE_SIZE = 12;

// 评分 / 价格档筛选项（与 PC 端下拉一致）
const RATING_OPTIONS = [
  { value: 0, label: '不限评分' },
  { value: 4, label: '4.0 分以上' },
  { value: 4.5, label: '4.5 分以上' },
];
const PRICE_OPTIONS = [
  { value: 0, label: '不限价格' },
  { value: 1, label: '经济（1 档）' },
  { value: 2, label: '实惠（≤2 档）' },
  { value: 3, label: '中档（≤3 档）' },
];

Page({
  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 });
    }
  },

  data: {
    categories: api.CATEGORY_TABS,
    category: 'all',
    categoryLabel: '全部分类',
    keyword: '',
    minRating: 0,
    priceLevel: 0,
    ratingLabels: RATING_OPTIONS.map((o) => o.label),
    priceLabels: PRICE_OPTIONS.map((o) => o.label),
    ratingIndex: 0,
    priceIndex: 0,
    tags: [],
    tagCode: '',
    tagNameMap: {},
    rows: [],
    total: 0,
    page: 1,
    loading: false,
    finished: false,
    // 地图分布（当前已加载的资源）
    showMap: false,
    markers: [],
    mapLat: 26.3731,
    mapLng: 106.6631,
    // 详情底部弹层
    detail: null,
    detailTags: [],
    detailImages: [],
  },

  onLoad() {
    // 先取标签字典再拉列表，保证卡片上的标签直接显示中文名
    this.loadTags().then(() => this.reload());
  },

  onPullDownRefresh() {
    this.reload().then(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (this.data.finished || this.data.loading) return;
    this.loadPage(this.data.page + 1);
  },

  /** 标签字典：把 POI 返回的 code 翻成中文名（PC 端直接显示 code，这里做了修正） */
  loadTags() {
    return api
      .getTags()
      .then((tags) => {
        const map = {};
        tags.forEach((t) => { map[t.code] = t.name; });
        this.setData({ tags, tagNameMap: map });
      })
      .catch(() => {});
  },

  reload() {
    this.setData({ page: 1, rows: [], finished: false });
    return this.loadPage(1);
  },

  loadPage(page) {
    if (this.data.loading) return Promise.resolve();
    this.setData({ loading: true });
    const params = { page, page_size: PAGE_SIZE };
    if (this.data.category !== 'all') params.category = this.data.category;
    if (this.data.keyword.trim()) params.keyword = this.data.keyword.trim();
    if (this.data.minRating) params.min_rating = this.data.minRating;
    if (this.data.priceLevel) params.price_level = this.data.priceLevel;
    if (this.data.tagCode) params.tags = this.data.tagCode;

    return api
      .listPois(params)
      .then((res) => {
        const items = (res.items || []).map((p) => this.decorate(p));
        const rows = page === 1 ? items : this.data.rows.concat(items);
        this.setData({
          rows,
          total: res.total || 0,
          page,
          loading: false,
          finished: rows.length >= (res.total || 0) || items.length === 0,
        });
        this.buildMarkers(rows);
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 补展示字段：类别名、标签中文名、价格文案、评分文案、开放时间文案 */
  decorate(p) {
    const cat = api.CATEGORY_NAME[p.category] || p.category || '';
    const names = (p.tags || []).map((c) => this.data.tagNameMap[c] || c);
    let openText = '';
    if (p.open_time && p.open_time.length && p.open_time[0] && p.open_time[0].length >= 2) {
      openText = p.open_time[0][0] + ' - ' + p.open_time[0][1];
    }
    return Object.assign({}, p, {
      category_name: cat,
      tag_names: names,
      rating_text: p.rating ? Number(p.rating).toFixed(1) : '—',
      price_text: p.ticket_price > 0 ? '¥' + p.ticket_price : '免费',
      duration_text: p.suggest_duration_min ? '约 ' + p.suggest_duration_min + ' 分钟' : '',
      open_text: openText,
      first_tag: names[0] || '',
      // 无图占位：取名称前两字，配合 .thumb-ph 的淡底大字，比单字色块更像"还没配图"
      initial: (p.name || '').slice(0, 2),
    });
  },

  buildMarkers(rows) {
    const markers = [];
    rows.forEach((p, i) => {
      if (!p.latitude || !p.longitude) return;
      markers.push({
        id: i,
        latitude: Number(p.latitude),
        longitude: Number(p.longitude),
        width: 24,
        height: 24,
        callout: {
          content: p.name,
          display: 'BYCLICK',
          padding: 6,
          borderRadius: 6,
          fontSize: 11,
        },
      });
    });
    const first = rows.find((p) => p.latitude && p.longitude);
    this.setData({
      markers,
      mapLat: first ? Number(first.latitude) : this.data.mapLat,
      mapLng: first ? Number(first.longitude) : this.data.mapLng,
    });
  },

  // ---------------- 筛选交互 ----------------

  pickCategory(e) {
    const category = e.currentTarget.dataset.code;
    if (category === this.data.category) return;
    const tab = api.CATEGORY_TABS.find((t) => t.code === category);
    this.setData({ category, categoryLabel: tab ? tab.name : '全部分类' });
    this.reload();
  },

  onKeyword(e) {
    this.setData({ keyword: e.detail.value });
  },

  search() {
    this.reload();
  },

  onRating(e) {
    const i = Number(e.detail.value);
    this.setData({ ratingIndex: i, minRating: RATING_OPTIONS[i].value });
    this.reload();
  },

  onPrice(e) {
    const i = Number(e.detail.value);
    this.setData({ priceIndex: i, priceLevel: PRICE_OPTIONS[i].value });
    this.reload();
  },

  toggleTag(e) {
    const code = e.currentTarget.dataset.code;
    this.setData({ tagCode: this.data.tagCode === code ? '' : code });
    this.reload();
  },

  resetFilter() {
    this.setData({
      category: 'all', categoryLabel: '全部分类', keyword: '',
      minRating: 0, priceLevel: 0,
      ratingIndex: 0, priceIndex: 0, tagCode: '',
    });
    this.reload();
  },

  // ---------------- 地图 ----------------

  toggleMap() {
    if (!this.data.showMap && !this.data.markers.length) {
      wx.showToast({ title: '当前页资源暂无坐标', icon: 'none' });
      // 仍然打开，让用户看到空态提示
    }
    this.setData({ showMap: !this.data.showMap });
  },

  closeMap() {
    this.setData({ showMap: false });
  },

  onMarkerTap(e) {
    const id = e.detail && e.detail.markerId;
    const row = this.data.rows[id];
    if (row) this.openDetailById(row.id);
  },

  // ---------------- 详情 ----------------

  openDetail(e) {
    this.openDetailById(e.currentTarget.dataset.id);
  },

  openDetailById(id) {
    const p = this.data.rows.find((r) => Number(r.id) === Number(id));
    if (!p) return;
    this.setData({
      detail: p,
      detailTags: p.tag_names || [],
      detailImages: p.images && p.images.length ? p.images : (p.image ? [p.image] : []),
    });
  },

  closeDetail() {
    this.setData({ detail: null, detailTags: [], detailImages: [] });
  },

  stopEvent() {},

  previewImage(e) {
    const src = e.currentTarget.dataset.src;
    if (!src) return;
    wx.previewImage({ current: src, urls: this.data.detailImages });
  },

  navToPoi() {
    const p = this.data.detail;
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
