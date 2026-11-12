const api = require('../../utils/api');
const config = require('../../utils/config');

const SLOT_ICON = {
  morning: '🌅',
  lunch: '🍜',
  afternoon: '☀️',
  dinner: '🍲',
  evening: '🌙',
};

const CATEGORY_NAME = {
  scenic: '景点',
  food: '美食',
  hotel: '住宿',
  leisure: '休闲',
};

// 每天一条连线颜色（与 PC 端 AmapMap 的按天着色对齐）
const DAY_COLORS = ['#2f7d5c', '#e6803a', '#4a90d9', '#9b59b6', '#16a085', '#c0392b', '#7f8c8d'];

// ---------- T5 海报：画布尺寸（CSS px）与绘制工具 ----------
const POSTER_W = 375;
const POSTER_H = 640;

/** 微信扫描小程序码进入时，行程 id 在 scene（t=xxx）里而非 query.id */
function resolveTripId(options) {
  options = options || {};
  if (options.id) return decodeURIComponent(options.id);
  if (options.scene) {
    const scene = decodeURIComponent(options.scene);
    const m = /(?:^|&)t=([^&]+)/.exec(scene);
    if (m) return decodeURIComponent(m[1]);
  }
  return '';
}

/** 按最大宽度截断并追加省略号 */
function fitText(ctx, text, maxWidth) {
  const str = String(text || '');
  if (ctx.measureText(str).width <= maxWidth) return str;
  let cut = str;
  while (cut.length && ctx.measureText(cut + '…').width > maxWidth) {
    cut = cut.slice(0, -1);
  }
  return cut + '…';
}

/** 圆角矩形（兼容不支持 roundRect 的基础库） */
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** canvas 2d 加载网络图片（小程序码/二维码） */
function loadCanvasImage(canvas, src) {
  return new Promise((resolve, reject) => {
    const img = canvas.createImage();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('二维码加载失败'));
    img.src = src;
  });
}

Page({
  data: {
    tripId: '',
    trip: null,
    loading: true,
    // 分享（T5）
    shareImage: '',
    showPoster: false,
    posterPath: '',
    // 调整面板
    adjustDayIndex: 0,
    candidates: [],
    candidatesForSlot: '',
    showCandidates: false,
    // T7 小贴士
    enrichment: null,
    enrichLoading: false,
    // T8 提醒
    reminderTip: '',
    // T4 天数 / 预算调整
    showAdjust: false,
    adjDays: 0,
    adjBudget: 0,
    adjusting: false,
    // #9 每日通勤概览
    segmentsByDay: {},
    // 路线地图（按天着色连线）
    mapDay: 1,
    mapOpen: false,
    dayTabActive: 1,
    mapMarkers: [],
    mapPolyline: [],
    mapCenter: { latitude: 26.4138, longitude: 106.6619 },
    // 目的地天气条
    travelWeather: null,
    // 复制行程单
    tripText: '',
  },

  onLoad(options) {
    // 支持分享卡片 ?id= 与小程序码 ?scene=t%3Dxxx 两种进入方式
    this.setData({ tripId: resolveTripId(options) });
    if (wx.showShareMenu) {
      wx.showShareMenu({ menus: ['shareAppMessage', 'shareTimeline'] });
    }
    if (!this.data.tripId) {
      this.setData({ loading: false });
      wx.showToast({ title: '行程不存在', icon: 'none' });
      return;
    }
    this.fetchTrip();
  },

  fetchTrip() {
    this.setData({ loading: true });
    api
      .getTrip(this.data.tripId)
      .then((trip) => {
        trip.budget_usage_percent = Math.round((trip.budget_usage || 0) * 100);
        trip.weight_profile = trip.weight_profile || [];
        trip.relax_log = trip.relax_log || [];
        let shareImage = '';
        trip.days_plan.forEach((d, di) => {
          d.color = DAY_COLORS[di % DAY_COLORS.length];
          d.items.forEach((it) => {
            it.icon = SLOT_ICON[it.slot] || '📍';
            it.category_name = CATEGORY_NAME[it.category] || it.category;
            it.image = api.absImage(it.image);
            if (!shareImage && it.image) shareImage = it.image;
            // 游学保底站：逐站讲解 / 研学任务卡 / 预约与降级提示
            const p = it.preset || null;
            it.has_narration = !!(p && p.narration_title);
            it.narr_open = false;
            it.locked = !!(p && p.is_study_stop);
            it.narration_title = (p && p.narration_title) || '';
            it.narration_text = (p && p.narration_text) || '';
            it.photo_tip = (p && p.photo_tip) || '';
            it.task_card = (p && p.task_card) || null;
            it.gate_notes = (p && p.gate_notes) || [];
            it.gate_label = (p && p.gate_status === 'degraded') ? '已降级'
              : (p && p.gate_status === 'reminder') ? '需预约' : '';
          });
        });
        const preset = trip.preset_route || null;
        if (preset) {
          const notes = preset.gate_notes || [];
          trip.preset_notes = notes.slice(0, 2);
          trip.preset_notes_more = Math.max(0, notes.length - 2);
          trip.preset_degraded = (preset.degraded_count || 0) > 0;
        }
        this.setData({ trip, shareImage, loading: false, mapDay: 1 });
        this.buildMap(1);
        this.setData({ tripText: this.buildTripText(trip) });
        this.loadEnrichment();
        this.loadSegments();
        this.loadWeather();
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  // ---------- 目的地天气（紧凑天气条，与 PC 行程页一致） ----------
  loadWeather() {
    api.getWeather({ days: 3 })
      .then((w) => {
        if (!w || w.available === false || !w.live) {
          this.setData({ travelWeather: null });
          return;
        }
        const days = (w.casts || []).slice(0, 3).map((c) => ({
          week: c.week,
          day: c.dayweather,
          t: c.daytemp + '°/' + c.nighttemp + '°',
        }));
        this.setData({ travelWeather: { live: w.live, days } });
      })
      .catch(() => this.setData({ travelWeather: null }));
  },

  // ---------- 路线地图：按天连线（住宿当天出发点） ----------
  buildMap(dayIndex) {
    const trip = this.data.trip;
    if (!trip) return;
    const day = (trip.days_plan || []).find((d) => d.day_index === dayIndex);
    const points = [];
    const markers = [];

    const hotel = trip.hotel;
    if (hotel && hotel.latitude && hotel.longitude) {
      points.push({ latitude: Number(hotel.latitude), longitude: Number(hotel.longitude) });
    }
    (day ? day.items : []).forEach((it, i) => {
      if (!it.latitude || !it.longitude) return;
      points.push({ latitude: Number(it.latitude), longitude: Number(it.longitude) });
      markers.push({
        id: i,
        latitude: Number(it.latitude),
        longitude: Number(it.longitude),
        width: 24,
        height: 24,
        callout: {
          content: it.start_time + ' ' + it.name,
          display: 'BYCLICK',
          padding: 6,
          borderRadius: 6,
          fontSize: 11,
        },
      });
    });

    const center = points.length ? points[0] : this.data.mapCenter;
    this.setData({
      mapDay: dayIndex,
      mapMarkers: markers,
      mapPolyline: points.length > 1
        ? [{
            points,
            color: (day && day.color) || '#2f7d5c',
            width: 6,
            arrowLine: true,
            borderWidth: 1,
          }]
        : [],
      mapCenter: center,
    });
  },

  pickMapDay(e) {
    const day = Number(e.currentTarget.dataset.day);
    if (day === this.data.mapDay) return;
    this.buildMap(day);
  },

  /** 地图默认收起：点标题行展开，减少首屏被地图挤占 */
  toggleMap() {
    this.setData({ mapOpen: !this.data.mapOpen });
  },

  /** 跳转到某一天（吸顶的 Day 胶囊） */
  goDay(e) {
    const day = Number(e.currentTarget.dataset.day);
    this.setData({ dayTabActive: day });
    wx.pageScrollTo({ selector: '#day-' + day, offsetTop: -56, duration: 260 });
  },

  /** 展开 / 收起某一站的逐站讲解与研学任务卡 */
  toggleNarration(e) {
    const di = Number(e.currentTarget.dataset.di);
    const ii = Number(e.currentTarget.dataset.ii);
    const day = (this.data.trip && this.data.trip.days_plan[di]) || null;
    if (!day || !day.items[ii]) return;
    const patch = {};
    patch['trip.days_plan[' + di + '].items[' + ii + '].narr_open'] = !day.items[ii].narr_open;
    this.setData(patch);
  },

  goPresetRoute() {
    wx.navigateTo({ url: '/pages/study/study' });
  },

  /** 行程单纯文本（PC 端「导出 txt」的小程序等价物：复制到剪贴板） */
  buildTripText(trip) {
    const lines = [];
    lines.push('花溪旅行 · ' + trip.mode_name + ' ' + trip.days + ' 天行程单');
    lines.push('人均预算 ¥' + trip.budget + ' ｜ 预估花费 ¥' + trip.total_cost
      + ' ｜ 预算使用率 ' + Math.round((trip.budget_usage || 0) * 100) + '%');
    if (trip.visit_date) lines.push('出行日期：' + trip.visit_date);
    if (trip.hotel) lines.push('住宿：' + trip.hotel.name + ' × ' + trip.hotel_nights + ' 晚');
    if ((trip.relax_log || []).length) {
      lines.push('提示：' + trip.relax_log.map((r) => r.label).join('；'));
    }
    lines.push('');
    (trip.days_plan || []).forEach((d) => {
      lines.push('── Day ' + d.day_index + ' ' + d.theme + '（¥' + d.day_cost + '）──');
      d.items.forEach((it) => {
        lines.push('  ' + it.start_time + '  ' + it.slot_name + '  ' + it.name
          + '  约' + it.duration_min + '分钟  ' + (it.cost > 0 ? '¥' + it.cost : '免费'));
        if (it.narration_title) lines.push('      讲解：' + it.narration_title);
        if (it.task_card && it.task_card.title) lines.push('      任务：' + it.task_card.title);
      });
      lines.push('');
    });
    lines.push('数据口径：花溪区本地演示种子数据 · 行程仅供参考');
    return lines.join('\n');
  },

  copyTripText() {
    const data = this.data.tripText;
    if (!data) return;
    wx.setClipboardData({
      data,
      success: () => wx.showToast({ title: '行程单已复制', icon: 'success' }),
      fail: () => wx.showToast({ title: '复制失败，请重试', icon: 'none' }),
    });
  },

  // ---- T7 AI 润色与小贴士 ----
  loadEnrichment() {
    if (!this.data.tripId) return;
    this.setData({ enrichLoading: true });
    api
      .getEnrichment(this.data.tripId)
      .then((enrichment) => this.setData({ enrichment, enrichLoading: false }))
      .catch(() => this.setData({ enrichLoading: false }));
  },

  refreshEnrichment() {
    if (this.data.enrichLoading) return;
    this.setData({ enrichLoading: true });
    api
      .refreshEnrichment(this.data.tripId)
      .then((enrichment) => {
        this.setData({ enrichment, enrichLoading: false });
        wx.showToast({ title: '小贴士已更新', icon: 'success' });
      })
      .catch((e) => {
        this.setData({ enrichLoading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  // ---- #9 每日通勤概览 ----
  loadSegments() {
    if (!this.data.tripId) return;
    api
      .routeSegments(this.data.tripId)
      .then((res) => {
        const map = {};
        (res.days || []).forEach((d) => {
          map[d.day_index] = {
            distance_m: d.distance_m,
            duration_min: d.duration_min,
            distance_text: d.distance_m >= 1000
              ? (d.distance_m / 1000).toFixed(1) + ' km'
              : d.distance_m + ' m',
          };
        });
        this.setData({ segmentsByDay: map });
      })
      .catch(() => {});
  },

  // ---- T8 出行前一日订阅提醒 ----
  subscribeReminder() {
    const tpl = config.TRIP_REMINDER_TEMPLATE_ID;
    if (!tpl) {
      wx.showToast({ title: '提醒模板未配置', icon: 'none' });
      return;
    }
    if (!api.getToken()) {
      this.askLogin('需要登录', '登录后才能设置出行提醒，现在去登录吗？');
      return;
    }
    const trip = this.data.trip || {};
    const visitDate = trip.visit_date;
    if (!visitDate) {
      wx.showToast({ title: '请先在个性化页选择出行日期', icon: 'none' });
      return;
    }
    wx.requestSubscribeMessage({
      tmplIds: [tpl],
      success: (res) => {
        if (res[tpl] !== 'accept') {
          wx.showToast({ title: '未授权提醒', icon: 'none' });
          return;
        }
        api
          .subscribeTrip(this.data.tripId, { visit_date: visitDate })
          .then((r) => {
            this.setData({ reminderTip: r.message || '已设置出行提醒' });
            wx.showToast({ title: '已设置提醒', icon: 'success' });
          })
          .catch((e) => wx.showToast({ title: e.message, icon: 'none' }));
      },
      fail: () => wx.showToast({ title: '订阅授权失败', icon: 'none' }),
    });
  },

  // ---- T4 增量调整天数 / 预算 ----
  openAdjust() {
    const trip = this.data.trip || {};
    this.setData({ showAdjust: true, adjDays: trip.days || 1, adjBudget: trip.budget || 0 });
  },

  closeAdjust() {
    this.setData({ showAdjust: false });
  },

  onAdjDays(e) {
    this.setData({ adjDays: Number(e.detail.value) || 0 });
  },

  onAdjBudget(e) {
    this.setData({ adjBudget: Number(e.detail.value) || 0 });
  },

  applyAdjust() {
    const trip = this.data.trip || {};
    const days = Math.max(1, Math.min(10, parseInt(this.data.adjDays, 10) || trip.days || 1));
    const budget = Math.max(1, parseFloat(this.data.adjBudget) || trip.budget || 1);
    if (days === trip.days && Math.abs(budget - trip.budget) < 0.01) {
      this.closeAdjust();
      return;
    }
    this.setData({ adjusting: true });
    wx.showLoading({ title: '增量重算中…' });
    api
      .replanTrip(this.data.tripId, { days, budget })
      .then(() => {
        wx.hideLoading();
        this.setData({ adjusting: false, showAdjust: false });
        wx.showToast({ title: '已按新参数调整', icon: 'success' });
        this.fetchTrip();
      })
      .catch((e) => {
        wx.hideLoading();
        this.setData({ adjusting: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  // ---- 调整：当日重排（换一批） ----
  redropDay(e) {
    const dayIndex = e.currentTarget.dataset.day;
    wx.showLoading({ title: '重新安排中…' });
    api
      .rebalance(this.data.tripId, { day_index: dayIndex, action: 'redrop' })
      .then(() => {
        wx.hideLoading();
        wx.showToast({ title: '已重排', icon: 'success' });
        this.fetchTrip();
      })
      .catch((e) => {
        wx.hideLoading();
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  // ---- 调整：槽位替换（弹出候选） ----
  pickSlot(e) {
    const { day, slot } = e.currentTarget.dataset;
    if (!slot || slot === 'lunch' || slot === 'dinner') {
      // 用餐槽不提供替换
      return;
    }
    const trip = this.data.trip;
    const dayPlan = ((trip && trip.days_plan) || []).find((d) => d.day_index === Number(day));
    const current = dayPlan && dayPlan.items.find((it) => it.slot === slot);
    if (current && current.locked) {
      wx.showToast({ title: '游学保底站不可替换', icon: 'none' });
      return;
    }
    this.setData({ adjustDayIndex: day, candidatesForSlot: slot, showCandidates: true, candidates: [] });
    api
      .slotCandidates(this.data.tripId, day, slot)
      .then((res) => {
        (res.items || []).forEach((it) => {
          it.category_name = CATEGORY_NAME[it.category] || it.category;
        });
        this.setData({ candidates: res.items || [] });
      })
      .catch((e) => wx.showToast({ title: e.message, icon: 'none' }));
  },

  applyCandidate(e) {
    const poiId = e.currentTarget.dataset.id;
    const { tripId, adjustDayIndex: day, candidatesForSlot: slot } = this.data;
    this.setData({ showCandidates: false });
    wx.showLoading({ title: '替换中…' });
    api
      .rebalance(tripId, { day_index: day, action: 'replace', slot, poi_id: poiId })
      .then(() => {
        wx.hideLoading();
        wx.showToast({ title: '已替换', icon: 'success' });
        this.fetchTrip();
      })
      .catch((e) => {
        wx.hideLoading();
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  closeCandidates() {
    this.setData({ showCandidates: false });
  },

  // ---- 保存到我的行程 ----
  saveTrip() {
    if (!api.getToken()) {
      this.askLogin('需要登录', '登录后才能把行程保存到「我的」，现在去登录吗？');
      return;
    }
    api
      .saveTrip(this.data.tripId)
      .then(() => {
        getApp().globalData.savedTripId = this.data.tripId;
        wx.showToast({ title: '已保存到我的行程', icon: 'success' });
      })
      .catch((e) => {
        if (e.status === 401) this.askLogin('登录已失效', '会话已过期，请重新登录后保存行程');
        else wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  askLogin(title, content) {
    wx.showModal({
      title,
      content,
      confirmText: '去登录',
      success: (r) => {
        if (r.confirm) wx.navigateTo({ url: '/pages/login/login' });
      },
    });
  },

  // ---- 换一批（整体重新生成，回需求页） ----
  regenerate() {
    wx.navigateBack();
  },

  // ---- 按权重调整路线（跳转个性化页，重排当前行程） ----
  goPersonalize() {
    wx.navigateTo({
      url: '/pages/personalize/personalize?trip=' + this.data.tripId +
        '&mode=' + (this.data.trip ? this.data.trip.mode : 'leisure'),
    });
  },

  // ==================== T5 分享：微信卡片 ====================

  onShareAppMessage() {
    const trip = this.data.trip;
    if (!trip) {
      return { title: '花溪智游 · 个性化旅游路线', path: '/pages/home/home' };
    }
    return {
      title: '我在花溪排了份' + trip.days + '天' + trip.mode_name + '行程，快来看',
      path: '/pages/trip/trip?id=' + this.data.tripId,
      imageUrl: this.data.shareImage || undefined,
    };
  },

  onShareTimeline() {
    const trip = this.data.trip;
    if (!trip) return { title: '花溪智游 · 个性化旅游路线' };
    return {
      title: '花溪' + trip.days + '天' + trip.mode_name + '行程 · 人均¥' + trip.budget,
      query: 'id=' + this.data.tripId,
      imageUrl: this.data.shareImage || undefined,
    };
  },

  // ==================== T5 分享：canvas 海报 ====================

  openPoster() {
    if (!this.data.trip) return;
    wx.showLoading({ title: '生成海报中…', mask: true });
    api
      .createPoster(this.data.tripId)
      .then((data) => this.drawPoster(data))
      .then((path) => {
        wx.hideLoading();
        this.setData({ posterPath: path, showPoster: true });
      })
      .catch((e) => {
        wx.hideLoading();
        wx.showToast({ title: e.message || '海报生成失败', icon: 'none' });
      });
  },

  /** 取离屏 canvas 节点并按 dpr 初始化，绘制后导出临时图片 */
  drawPoster(data) {
    return new Promise((resolve, reject) => {
      wx.createSelectorQuery()
        .select('#posterCanvas')
        .fields({ node: true, size: true })
        .exec((res) => {
          const canvas = res && res[0] && res[0].node;
          if (!canvas) {
            reject(new Error('画布初始化失败'));
            return;
          }
          const dpr =
            (wx.getWindowInfo ? wx.getWindowInfo().pixelRatio
              : wx.getSystemInfoSync().pixelRatio) || 2;
          canvas.width = POSTER_W * dpr;
          canvas.height = POSTER_H * dpr;
          const ctx = canvas.getContext('2d');
          ctx.scale(dpr, dpr);

          this.paintPoster(ctx, canvas, data)
            .then(() => {
              wx.canvasToTempFilePath(
                {
                  canvas,
                  fileType: 'png',
                  quality: 1,
                  success: (r) => resolve(r.tempFilePath),
                  fail: (err) => reject(new Error(err.errMsg || '导出海报失败')),
                },
                this,
              );
            })
            .catch(reject);
        });
    });
  },

  /** 海报排版：品牌头 → 标题/预算 → 三日概览 → 二维码 */
  async paintPoster(ctx, canvas, data) {
    const W = POSTER_W;
    ctx.clearRect(0, 0, W, POSTER_H);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, POSTER_H);

    // 头部渐变
    const grad = ctx.createLinearGradient(0, 0, W, 92);
    grad.addColorStop(0, '#2f7d5c');
    grad.addColorStop(1, '#3d9470');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, 92);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath();
    ctx.arc(330, 6, 68, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(362, 92, 38, 0, Math.PI * 2);
    ctx.fill();

    ctx.textAlign = 'left';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 20px sans-serif';
    ctx.fillText(data.brand.name, 24, 40);
    ctx.font = '10px sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.82)';
    ctx.fillText(data.brand.slogan, 24, 60);

    ctx.textAlign = 'right';
    ctx.font = '9px sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    ctx.fillText('PERSONALIZED TRIP', W - 24, 40);
    ctx.textAlign = 'left';

    // 标题与预算
    ctx.fillStyle = '#1d3a2c';
    ctx.font = 'bold 21px sans-serif';
    ctx.fillText(fitText(ctx, data.title, W - 48), 24, 132);
    ctx.fillStyle = '#6b7a72';
    ctx.font = '12px sans-serif';
    ctx.fillText(
      '人均预算 ¥' + Math.round(data.budget) +
        ' · 预估花费 ¥' + Math.round(data.total_cost),
      24,
      154,
    );

    // 三列指标
    roundRect(ctx, 24, 172, W - 48, 54, 10);
    ctx.fillStyle = '#f4f9f6';
    ctx.fill();
    const cols = [
      { x: 78, value: data.days + ' 天', label: '行程天数' },
      { x: 187, value: '¥' + Math.round(data.budget), label: '人均预算' },
      { x: 296, value: Math.round((data.budget_usage || 0) * 100) + '%', label: '预算使用率' },
    ];
    ctx.textAlign = 'center';
    cols.forEach((c) => {
      ctx.fillStyle = '#2f7d5c';
      ctx.font = 'bold 17px sans-serif';
      ctx.fillText(c.value, c.x, 198);
      ctx.fillStyle = '#8a978f';
      ctx.font = '9px sans-serif';
      ctx.fillText(c.label, c.x, 214);
    });
    ctx.textAlign = 'left';

    // 住宿（多日行程）
    let y = 252;
    if (data.hotel && data.hotel.name) {
      ctx.fillStyle = '#a6b1ab';
      ctx.font = '10px sans-serif';
      ctx.fillText('住宿', 24, 246);
      ctx.fillStyle = '#3f4d46';
      ctx.font = '11px sans-serif';
      ctx.fillText(
        fitText(ctx, data.hotel.name + ' · ' + data.hotel.nights + ' 晚', 260),
        58,
        246,
      );
      y = 266;
    }

    // 每日摘要：最多 4 天；≤3 天每天取 4 个时段，否则取 2 个
    const daysPlan = data.days_plan || [];
    const shown = daysPlan.slice(0, 4);
    const perDay = daysPlan.length <= 3 ? 4 : 2;
    shown.forEach((d) => {
      ctx.fillStyle = '#2f7d5c';
      ctx.font = 'bold 12px sans-serif';
      ctx.fillText('Day ' + d.day_index, 24, y);
      ctx.fillStyle = '#1d3a2c';
      ctx.fillText(fitText(ctx, d.theme || '', 190), 68, y);
      ctx.textAlign = 'right';
      ctx.fillStyle = '#e6803a';
      ctx.font = 'bold 11px sans-serif';
      ctx.fillText('¥' + Math.round(d.day_cost || 0), W - 24, y);
      ctx.textAlign = 'left';
      y += 18;

      // 同一时段可能排了多个点，摘要只取每个时段第一个
      const seen = {};
      const picked = [];
      (d.items || []).forEach((it) => {
        if (picked.length >= perDay || seen[it.slot]) return;
        seen[it.slot] = true;
        picked.push(it);
      });
      picked.forEach((it) => {
        ctx.fillStyle = '#a6b1ab';
        ctx.font = '10px sans-serif';
        ctx.fillText(it.slot_name || '', 30, y);
        ctx.fillStyle = '#3f4d46';
        ctx.font = '11px sans-serif';
        ctx.fillText(fitText(ctx, it.name, 200), 96, y);
        ctx.textAlign = 'right';
        ctx.fillStyle = '#7d8a84';
        ctx.font = '10px sans-serif';
        ctx.fillText(it.cost > 0 ? '¥' + Math.round(it.cost) : '免费', W - 24, y);
        ctx.textAlign = 'left';
        y += 15;
      });
      y += 6;
    });

    if (daysPlan.length > shown.length) {
      ctx.fillStyle = '#8a978f';
      ctx.font = '10px sans-serif';
      ctx.fillText('共 ' + data.days + ' 天完整行程，扫码查看每日安排', 24, Math.min(y + 2, 512));
    }

    // 底部分隔线 + 二维码
    ctx.strokeStyle = '#eef2ef';
    ctx.beginPath();
    ctx.moveTo(24, 526);
    ctx.lineTo(W - 24, 526);
    ctx.stroke();

    const qrSize = 84;
    const qrX = W - 24 - qrSize;
    const qrY = 534;
    let qrImg = null;
    try {
      if (data.qr && data.qr.url) {
        qrImg = await loadCanvasImage(canvas, data.qr.url);
      }
    } catch (e) {
      qrImg = null;
    }
    if (qrImg) {
      ctx.drawImage(qrImg, qrX, qrY, qrSize, qrSize);
    } else {
      roundRect(ctx, qrX, qrY, qrSize, qrSize, 8);
      ctx.fillStyle = '#f2f5f3';
      ctx.fill();
      ctx.fillStyle = '#8a978f';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('扫码查看', qrX + qrSize / 2, qrY + qrSize / 2 + 3);
      ctx.textAlign = 'left';
    }

    ctx.fillStyle = '#1d3a2c';
    ctx.font = 'bold 13px sans-serif';
    ctx.fillText('扫码查看完整行程', 24, 552);
    ctx.fillStyle = '#6b7a72';
    ctx.font = '10px sans-serif';
    ctx.fillText('微信搜索小程序「花溪智游」', 24, 572);
    ctx.fillStyle = '#a6b1ab';
    ctx.font = '9px sans-serif';
    ctx.fillText('生成于 ' + data.generated_at, 24, 590);

    ctx.fillStyle = '#c2cbc6';
    ctx.font = '9px sans-serif';
    ctx.fillText(data.brand.slogan, 24, 628);
  },

  savePoster() {
    const filePath = this.data.posterPath;
    if (!filePath) return;
    wx.saveImageToPhotosAlbum({
      filePath,
      success: () => wx.showToast({ title: '已保存到相册', icon: 'success' }),
      fail: (err) => {
        const msg = err.errMsg || '';
        if (/auth|deny|denied/.test(msg)) {
          wx.showModal({
            title: '需要相册权限',
            content: '请在设置中允许「保存到相册」，也可以长按海报图片直接保存',
            confirmText: '去设置',
            success: (r) => {
              if (r.confirm) wx.openSetting();
            },
          });
        } else if (!/cancel/.test(msg)) {
          wx.showToast({ title: '保存失败，可长按图片保存', icon: 'none' });
        }
      },
    });
  },

  closePoster() {
    this.setData({ showPoster: false });
  },

  /** 阻止海报面板点击冒泡到遮罩 */
  noop() {},
});
