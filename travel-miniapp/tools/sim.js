#!/usr/bin/env node
/**
 * 小程序页面逻辑模拟器（无微信开发者工具时验证真实行为）
 *
 * 做法：用内存 storage + 真实 HTTP 请求伪造 wx.* 运行时，然后直接执行页面 js，
 * 调用 onLoad / onShow / 事件处理函数，断言 data 是否符合预期。
 * 这样能覆盖：接口参数、数据加工、状态流转、跳转目标，而不只是语法。
 *
 * 前提：后端已在 http://127.0.0.1:8000 运行。
 * 用法：node tools/sim.js
 */
const fs = require('fs');
const path = require('path');
const http = require('http');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const API_BASE = 'http://127.0.0.1:8000/api/v1';
const STATIC_BASE = 'http://127.0.0.1:8000';

const failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}
function eq(actual, expect, msg) {
  if (actual !== expect) failures.push(`${msg}（期望 ${JSON.stringify(expect)}，实际 ${JSON.stringify(actual)}）`);
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(ms = 1600) { await wait(ms); }

// ---------------- wx 运行时桩 ----------------
const storage = new Map();
const navLog = [];
let toastLog = [];

function httpRequest(opts) {
  return new Promise((resolve, reject) => {
    const url = new URL(opts.url);
    const body = opts.data === undefined ? null
      : (typeof opts.data === 'string' ? opts.data : JSON.stringify(opts.data));
    const req = http.request({
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname + url.search,
      method: opts.method || 'GET',
      headers: Object.assign({}, opts.header, body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let data = text;
        try { data = JSON.parse(text); } catch (e) { /* 保留原始文本 */ }
        resolve({ statusCode: res.statusCode, data });
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

global.wx = {
  getStorageSync: (k) => (storage.has(k) ? storage.get(k) : ''),
  setStorageSync: (k, v) => storage.set(k, v),
  removeStorageSync: (k) => storage.delete(k),
  clearStorageSync: () => storage.clear(),
  request(opts) {
    // GET 的 data 由 wx 自动拼到 query 上
    let url = opts.url;
    if ((opts.method || 'GET') === 'GET' && opts.data && Object.keys(opts.data).length) {
      const qs = Object.keys(opts.data)
        .filter((k) => opts.data[k] !== undefined && opts.data[k] !== null && opts.data[k] !== '')
        .map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(opts.data[k]))
        .join('&');
      if (qs) url += (url.includes('?') ? '&' : '?') + qs;
    }
    httpRequest({ url, method: opts.method || 'GET', data: (opts.method || 'GET') === 'GET' ? null : opts.data, header: opts.header })
      .then((res) => opts.success && opts.success(res))
      .catch((err) => opts.fail && opts.fail(err))
      .then(() => opts.complete && opts.complete());
  },
  showToast: (o) => { toastLog.push((o && o.title) || ''); },
  hideToast: () => {},
  showLoading: () => {},
  hideLoading: () => {},
  showModal: () => {},
  navigateTo: (o) => navLog.push({ type: 'navigateTo', url: o.url }),
  redirectTo: (o) => navLog.push({ type: 'redirectTo', url: o.url }),
  switchTab: (o) => navLog.push({ type: 'switchTab', url: o.url }),
  reLaunch: (o) => navLog.push({ type: 'reLaunch', url: o.url }),
  navigateBack: () => navLog.push({ type: 'navigateBack' }),
  setNavigationBarTitle: () => {},
  stopPullDownRefresh: () => {},
  openLocation: (o) => navLog.push({ type: 'openLocation', name: o.name }),
  pageScrollTo: (o) => navLog.push({ type: 'pageScrollTo', selector: o.selector }),
  previewImage: () => {},
  setClipboardData: (o) => navLog.push({ type: 'clipboard', data: o.data }),
  getAccountInfoSync: () => ({ miniProgram: { envVersion: 'develop' } }),
  getWindowInfo: () => ({ pixelRatio: 2 }),
  // platform 决定 config.js 用 localhost 还是局域网 IP，这里模拟开发者工具
  getSystemInfoSync: () => ({ pixelRatio: 2, platform: 'devtools' }),
  getPrivacySetting: () => {},
  showShareMenu: () => {},
  login: (o) => o.fail && o.fail({ errMsg: 'sim: no wx.login' }),
};

const appStub = {
  globalData: {
    userInfo: null, savedTripId: '', lastTripId: '', pendingMode: '', pendingPlan: null,
  },
};
global.getApp = () => appStub;
global.getCurrentPages = () => [{}, {}];

// ---------------- Page 装载 ----------------
/** 把 setData 的路径（含 a.b / a[0].b[1].c 两种写法）解析成段 */
function parsePath(key) {
  const segs = [];
  key.replace(/([^.[\]]+)|\[(\d+)\]/g, (m, name, idx) => {
    segs.push(idx !== undefined ? Number(idx) : name);
    return m;
  });
  return segs;
}

function applyPatch(target, patch) {
  Object.keys(patch).forEach((key) => {
    const segs = parsePath(key);
    let cur = target;
    for (let i = 0; i < segs.length - 1; i += 1) {
      const seg = segs[i];
      if (cur[seg] === undefined || cur[seg] === null || typeof cur[seg] !== 'object') {
        cur[seg] = typeof segs[i + 1] === 'number' ? [] : {};
      }
      cur = cur[seg];
    }
    cur[segs[segs.length - 1]] = patch[key];
  });
}

function loadPage(relPath) {
  const file = path.join(ROOT, relPath);
  let def = null;
  global.Page = (d) => { def = d; };
  delete require.cache[require.resolve(file)];
  require(file);
  if (!def) throw new Error(`${relPath} 未调用 Page()`);
  const page = Object.create(null);
  Object.keys(def).forEach((k) => {
    if (k !== 'data') page[k] = def[k];
  });
  page.data = JSON.parse(JSON.stringify(def.data || {}));
  page.setData = function setData(patch, cb) {
    applyPatch(this.data, patch || {});
    if (typeof cb === 'function') cb();
  };
  return page;
}

// ---------------- 场景 ----------------
async function main() {
  // 0) 后端存活
  const ping = await httpRequest({ url: API_BASE + '/health', method: 'GET' }).catch(() => null);
  check(ping && ping.statusCode === 200, '后端未就绪：请先启动 travel-api（http://127.0.0.1:8000）');
  if (!ping || ping.statusCode !== 200) return finish();

  // 1) 首页
  {
    const page = loadPage('pages/home/home.js');
    page.onLoad();
    await settle(2600);
    eq(page.data.modes.length, 4, '首页模式数');
    check(page.data.hotPois.length > 0, '首页精选资源为空');
    check(page.data.totalPois > 0, '首页资源总数未取到');
    {
      // 首页统计必须是「全库口径」，不能被精选那条请求的评分筛选带着走
      const all = await httpRequest({ url: API_BASE + '/pois?page_size=1', method: 'GET' });
      eq(page.data.totalPois, all.data.total, '首页资源总数口径（应为全库）');
    }
    check(page.data.casts.length === 15, '首页 15 天预报条数');
    check(!!page.data.weather, '首页天气实况未取到');
    check(page.data.hotPois.every((p) => p.category_name && p.rating_text), '首页资源缺展示字段');
    check(page.data.hotPois.every((p) => !p.tag_names || p.tag_names.every((t) => !/^[a-z_]+$/.test(t))),
      '首页标签仍是原始 code（未翻译成中文）');
    // 点模式卡 → 走 globalData + switchTab
    page.pickMode({ currentTarget: { dataset: { mode: 'premium' } } });
    eq(appStub.globalData.pendingMode, 'premium', '首页 pickMode 传参');
    const last = navLog[navLog.length - 1];
    check(last && last.type === 'switchTab' && last.url.includes('pages/request/request'), '首页 pickMode 跳转定制页');
  }

  // 2) 发现页
  {
    const page = loadPage('pages/explore/explore.js');
    page.onLoad();
    await settle(2200);
    check(page.data.rows.length > 0, '发现页首屏列表为空');
    check(page.data.total > 0, '发现页总数未取到');
    check(page.data.tags.length >= 10, '发现页标签字典未取到');
    check(page.data.markers.length > 0, '发现页地图 marker 未生成');
    const firstTotal = page.data.total;

    // 分类切换
    page.pickCategory({ currentTarget: { dataset: { code: 'food' } } });
    await settle(1200);
    check(page.data.rows.length > 0 && page.data.rows.every((r) => r.category === 'food'), '发现页分类筛选（美食）失效');
    check(page.data.total < firstTotal, '发现页分类筛选后总数未变化');

    // 关键字 + 标签
    page.pickCategory({ currentTarget: { dataset: { code: 'all' } } });
    await settle(900);
    page.setData({ keyword: '青岩' });
    page.search();
    await settle(1200);
    check(page.data.rows.length > 0 && page.data.rows.every((r) => /青岩/.test(r.name + (r.address || '') + (r.sub_type || ''))), '发现页关键字搜索失效');

    page.setData({ keyword: '' });
    page.toggleTag({ currentTarget: { dataset: { code: 'night_view' } } });
    await settle(1200);
    check(page.data.rows.length > 0 && page.data.rows.every((r) => (r.tags || []).includes('night_view')),
      '发现页标签筛选失效');
    page.toggleTag({ currentTarget: { dataset: { code: 'night_view' } } });
    await settle(1200);

    // 详情弹层
    const target = page.data.rows[0];
    page.openDetailById(target.id);
    eq(page.data.detail && page.data.detail.name, target.name, '发现页详情弹层');
    check(Array.isArray(page.data.detailImages), '发现页详情图集字段缺失');
    page.closeDetail();
    eq(page.data.detail, null, '发现页详情关闭');

    // 分页：加载第 2 页后行数应增加
    const before = page.data.rows.length;
    page.setData({ page: 1, finished: false });
    page.loadPage(2);
    await settle(1200);
    check(page.data.rows.length > before, '发现页上拉分页未追加数据');
  }

  // 3) 对比页（含从定制页带参进入）
  {
    const page = loadPage('pages/compare/compare.js');
    page.onLoad({ days: '3', budget: '2000', party: 'family', prefs: 'nature' });
    await settle(3200);
    eq(page.data.days, 3, '对比页天数参数');
    eq(page.data.budget, 2000, '对比页预算参数');
    eq(page.data.partyType, 'family', '对比页人群参数');
    eq(page.data.results.length, 4, '对比页四模式结果数');
    eq(page.data.insights.length, 4, '对比页差异总结条数');
    const r = page.data.results[0];
    check(typeof r.total_cost === 'number' && r.usage_percent >= 0, '对比页指标未加工');
    check(r.days.length >= 1 && typeof r.days[0].poi_text === 'string', '对比页每日路线未加工');
    check(page.data.results.every((x) => x.emoji), '对比页模式 emoji 缺失');

    // 默认选中第一个模式，切换小卡只换详情、不重新请求
    check(page.data.active && page.data.active.mode === r.mode, '对比页默认未选中第一个模式');
    page.pickMode({ currentTarget: { dataset: { idx: 2 } } });
    eq(page.data.activeIndex, 2, '对比页切换小卡索引');
    eq(page.data.active.mode, page.data.results[2].mode, '对比页切换后详情未更新');
    check(page.data.results[2].total_cost === page.data.active.total_cost, '对比页详情与结果不一致');

    // 采用某模式 → 回定制页
    page.useMode({ currentTarget: { dataset: { mode: 'checkin' } } });
    eq(appStub.globalData.pendingMode, 'checkin', '对比页采用模式传参');
    eq(appStub.globalData.pendingPlan.days, 3, '对比页回传天数');
    eq(appStub.globalData.pendingPlan.budget, 2000, '对比页回传预算');
    check(appStub.globalData.pendingPlan.prefs.includes('nature'), '对比页回传偏好');
  }

  // 4) 定制页（含 tab 传参、开销预估、生成）
  {
    const page = loadPage('pages/request/request.js');
    appStub.globalData.pendingMode = 'blitz';
    appStub.globalData.pendingPlan = { days: 3, budget: 2000, partyType: 'family', prefs: ['nature'] };
    page.onLoad();
    await settle(1800);
    page.onShow(); // 消费 globalData 传参
    await settle(600);
    eq(page.data.mode, 'blitz', '定制页未采用对比页传参的模式');
    eq(page.data.days, 3, '定制页未采用传参天数');
    eq(page.data.budget, 2000, '定制页未采用传参预算');
    check(page.data.selectedPrefs.includes('nature'), '定制页未回填偏好');
    eq(appStub.globalData.pendingMode, '', '定制页未清空 pendingMode');
    eq(page.data.modes.length, 4, '定制页模式列表');
    check(page.data.tags.length >= 10, '定制页标签字典未取到');
    check(page.data.estimate && page.data.estimate.total > 0, '定制页整体开销未计算');
    check(page.data.estimateRows.length === 5, '定制页开销明细行数');
    check(page.data.groups.length === 4 && page.data.groups.every((g) => g.options.some((o) => o.on)),
      '定制页小部件选中态未生成');

    // 小部件：换住宿档位应改变预估
    const before = page.data.estimate.total;
    page.pickPart({ currentTarget: { dataset: { group: 'hotel', key: 'luxury' } } });
    check(page.data.estimate.total > before, '定制页换住宿档位后开销未变化');
    check(page.data.groups.find((g) => g.key === 'hotel').options.some((o) => o.key === 'luxury' && o.on),
      '定制页小部件选中态未刷新');

    // 预算贴合度：把预算调到很低应为 over
    page.setData({ budget: 300 });
    page.recalc();
    eq(page.data.estimate.fit, 'over', '定制页低预算未判为超支');
    page.setData({ budget: 3000 });
    page.recalc();
    eq(page.data.estimate.fit, 'within', '定制页充足预算未判为预算内');

    // 生成载荷：必须带 pace 与 cost_prefs（否则 PC 端的小部件在手机上不生效）
    const payload = page.payload();
    check(payload.pace && payload.pace.daily_poi_max >= 2 && payload.pace.play_hours_max >= 3,
      '定制页载荷缺少 pace');
    check(payload.cost_prefs && typeof payload.cost_prefs.hotel_tier === 'number'
      && payload.cost_prefs.transport, '定制页载荷缺少 cost_prefs');
    check(typeof payload.seed === 'number', '定制页载荷缺少随机 seed');

    // 生成行程（真实接口）
    page.setData({ selectedPrefs: [] });
    page.submit();
    await settle(3000);
    const nav = navLog.filter((n) => n.type === 'navigateTo' && n.url.includes('/pages/trip/trip?id=')).pop();
    check(!!nav, '定制页生成后未跳转行程页');
    if (nav) {
      const tripId = nav.url.split('id=')[1];
      // 5) 行程页
      const tripPage = loadPage('pages/trip/trip.js');
      tripPage.onLoad({ id: tripId });
      await settle(2600);
      check(!!tripPage.data.trip, '行程页未加载到行程');
      eq(tripPage.data.trip.days, 3, '行程页天数');
      check(tripPage.data.trip.days_plan.length === 3, '行程页每日条目数');
      check(tripPage.data.trip.budget_usage_percent >= 0, '行程页预算使用率未计算');
      check(tripPage.data.trip.days_plan.every((d) => d.items.every((it) => it.icon && it.category_name)),
        '行程页槽位展示字段缺失');
      // 图片只允许管理员上传：没有上传过图时 shareImage 为空是正常状态，
      // 只有行程里确实带了图才要求封面被取到
      const hasImage = tripPage.data.trip.days_plan.some((d) => d.items.some((it) => it.image));
      if (hasImage) check(!!tripPage.data.shareImage, '行程页分享封面未取到');
      else eq(typeof tripPage.data.shareImage, 'string', '无图时分享封面应为空字符串');
      // 权重画像（定制页带了 pace，应回传）
      check(Array.isArray(tripPage.data.trip.weight_profile), '行程页权重画像字段');
    }
  }

  // 6) 个性化页（tab 无关，确认元数据与预览链路）
  {
    const page = loadPage('pages/personalize/personalize.js');
    page.onLoad({ mode: 'checkin', days: '4', budget: '2500' });
    await settle(2600);
    check(page.data.dimensions.length >= 8, '个性化页权重维度不足');
    check(page.data.preview.length > 0, '个性化页预览无结果');
    eq(page.data.sliderTotal > 0, true, '个性化页滑块总和为 0');
    eq(page.data.days, 4, '个性化页未接住传入天数');
    eq(page.data.budget, 2500, '个性化页未接住传入预算');

    // 生成载荷：天数 / 预算 / 权重 / 节奏都要带上（PC 端同口径）
    const apiMod = require(path.join(ROOT, 'utils/api.js'));
    const origGenerate = apiMod.generateTrip;
    let captured = null;
    apiMod.generateTrip = (p) => { captured = p; return Promise.resolve({ trip_id: 't_sim' }); };
    page.generate();
    await wait(120);
    apiMod.generateTrip = origGenerate;
    check(!!captured, '个性化页未调用生成接口');
    if (captured) {
      eq(captured.days, 4, '个性化页生成天数');
      eq(captured.budget, 2500, '个性化页生成预算');
      check(captured.weights && Object.keys(captured.weights).length >= 8, '个性化页未带权重');
      check(captured.pace && captured.pace.daily_poi_max, '个性化页未带节奏');
    }
  }

  // 7) 游学线成程 → 行程页（逐站讲解 / 锁定站 / 地图连线 / 行程单复制）
  {
    const body = JSON.stringify({
      days: 1, budget: 800, mode: 'leisure', preferences: [], party_type: 'couple',
      seed: 11, preset_route_code: 'gzu_campus_study_tour', visit_date: '2026-11-11',
    });
    const res = await httpRequest({
      url: API_BASE + '/trips/generate', method: 'POST', data: body,
      header: { 'Content-Type': 'application/json' },
    });
    check(res.statusCode === 200 && res.data.trip_id, '游学线成程接口失败');
    if (res.statusCode === 200 && res.data.trip_id) {
      const page = loadPage('pages/trip/trip.js');
      page.onLoad({ id: res.data.trip_id });
      await settle(2400);

      check(!!page.data.trip.preset_route, '行程页未识别游学线路');
      check(page.data.trip.preset_route.title, '游学横幅标题为空');
      check(page.data.trip.preset_notes.length >= 0, '游学 gate 提示字段缺失');

      const items = page.data.trip.days_plan[0].items;
      const narr = items.filter((it) => it.has_narration);
      check(narr.length > 0, '行程页未识别逐站讲解');
      check(narr.every((it) => it.locked), '游学保底站未标记为锁定');
      check(narr.every((it) => it.narration_text && it.task_card && it.task_card.title),
        '逐站讲解 / 任务卡内容缺失');
      check(narr.some((it) => it.gate_notes.length > 0), '预约或降级提示缺失');

      // 展开讲解：setData 路径写入
      page.toggleNarration({ currentTarget: { dataset: { di: 0, ii: items.indexOf(narr[0]) } } });
      eq(narr[0].narr_open, true, '逐站讲解展开状态未写入');
      page.toggleNarration({ currentTarget: { dataset: { di: 0, ii: items.indexOf(narr[0]) } } });
      eq(narr[0].narr_open, false, '逐站讲解收起状态未写入');

      // 地图：至少 1 个 marker 与一条按天连线
      check(page.data.mapMarkers.length > 0, '行程页地图 marker 未生成');
      check(page.data.mapPolyline.length === 1 && page.data.mapPolyline[0].points.length > 1,
        '行程页地图连线未生成');
      page.pickMapDay({ currentTarget: { dataset: { day: 1 } } });

      // 日期锚点：点 Day 胶囊应触发滚动定位
      page.goDay({ currentTarget: { dataset: { day: 1 } } });
      eq(page.data.dayTabActive, 1, '行程页 Day 胶囊选中态');
      const scroll = navLog.filter((n) => n.type === 'pageScrollTo').pop();
      check(!!scroll && scroll.selector === '#day-1', '行程页 Day 胶囊未触发滚动定位');

      // 每日预算字段（页面头部要显示"当日 ¥x / 预算 ¥y"）
      check(page.data.trip.days_plan.every((d) => typeof d.day_budget === 'number'),
        '行程页缺少每日预算字段');

      // 行程单复制
      check(page.data.tripText.indexOf('花溪旅行') === 0, '行程单文本为空或格式错误');
      check(page.data.tripText.indexOf('Day 1') > 0, '行程单文本未包含每日安排');
      check(page.data.tripText.indexOf('讲解：') > 0, '行程单文本未包含游学讲解');
      page.copyTripText();
      const clip = navLog.filter((n) => n.type === 'clipboard').pop();
      check(!!clip && clip.data.indexOf('花溪旅行') === 0, '行程单复制未调用剪贴板');

      // 锁定站不可替换
      const lockedSlot = narr[0].slot;
      page.pickSlot({ currentTarget: { dataset: { day: 1, slot: lockedSlot } } });
      eq(page.data.showCandidates, false, '锁定站仍弹出了替换候选');
    }
  }

  // 7) 问小旅（问答页）
  {
    const page = loadPage('pages/chat/chat.js');
    page.onLoad();
    await settle(2600);
    check(!!page.data.modeText, '问答页未取到服务状态');
    check((page.data.suggestions || []).length > 0, '问答推荐问题为空');
    page.setData({ input: '青岩古镇门票多少，需要预约吗？', canSend: true });
    page.send();
    await settle(4200);
    const msgs = page.data.messages || [];
    eq(msgs.length, 2, '问答消息条数（用户 + 助手）');
    check(!!msgs[1] && (msgs[1].text || '').length > 10, '助手回答为空');
    eq(!!msgs[1].degraded, true, '未配置 Key 时应标记降级（知识库摘录）');
    check(((msgs[1] && msgs[1].refs) || []).length > 0, '回答引用卡片为空');
    check(!!page.data.convId, '未拿到会话 id');
  }

  finish();
}

function finish() {
  const toasts = [...new Set(toastLog)].filter(Boolean);
  if (toasts.length) console.log('页面 toast：' + toasts.join(' | '));
  if (failures.length) {
    console.log(`\n失败 ${failures.length} 项：`);
    failures.forEach((f) => console.log('  ✗ ' + f));
    process.exit(1);
  }
  console.log('\n全部场景通过：首页 / 发现 / 对比 / 定制 / 行程 / 个性化 / 问小旅');
}

main().catch((e) => {
  console.log('模拟器异常：' + (e && e.stack || e));
  process.exit(1);
});
