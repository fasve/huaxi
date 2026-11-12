// 统一请求封装 + 登录态（设计方案 7.5：wx.login → code2session → 标准 JWT Bearer）
//
// 与旧版差别：不再传固定假 code，而是 wx.login 取一次性 code 交给服务端；
// token 为标准 JWT（7 天），本地记录过期时间并支持滑动续期；
// 401 时自动重走静默登录并重放原请求（账号登录用户不会被静默身份覆盖）。
// 域名按环境（develop / trial / release）自动切换，集中维护在 utils/config.js；
// trial / release 必须替换为已备案 + HTTPS + 已在微信后台登记的合法域名。
const config = require('./config');
// 动态取地址：运行时改了后端地址立即生效（不用重启小程序）
function base() { return config.getApiBase ? config.getApiBase() : config.API_BASE; }
function staticBase() { return config.getStaticBase ? config.getStaticBase() : config.STATIC_BASE; }
const TOKEN_KEY = 'travel_token';
const USER_KEY = 'travel_user';
const EXP_KEY = 'travel_token_exp';
const KIND_KEY = 'travel_login_kind';  // wechat | account
const DEVICE_KEY = 'travel_device_id'; // dev mock 分支的稳定设备标识（生产忽略）
const REFRESH_AHEAD_MS = 24 * 60 * 60 * 1000; // 剩余不足 24h 时自动续期

/** 把后端返回的相对图片路径补成绝对地址（小程序 <image> 需要完整 URL） */
function absImage(url) {
  if (!url) return '';
  const s = String(url);
  if (/^(https?:|cloud:|data:|wxfile:)/.test(s)) return s;
  const path = s.charAt(0) === '/' ? s.slice(1) : s;
  const b = staticBase();
  if (b) return b + '/' + path;
  // 没有 http 基址（体验版/正式版）→ 走云存储 fileID，<image> 原生支持 cloud://
  if (config.CLOUD_FILE_PREFIX) return 'cloud://' + config.CLOUD_FILE_PREFIX + '/' + path;
  return '';
}

/** 给 POI 列表/详情补上封面图字段 image */
function withImages(poi) {
  if (!poi) return poi;
  const imgs = poi.images && poi.images.length ? poi.images.map(absImage) : [];
  return Object.assign({}, poi, { images: imgs, image: imgs[0] || '' });
}

/** 稳定设备标识：退出登录也不清除，保证 dev mock 下游客行程不漂移 */
function getDeviceId() {
  let id = wx.getStorageSync(DEVICE_KEY);
  if (!id) {
    id = 'wx_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 12);
    wx.setStorageSync(DEVICE_KEY, id);
  }
  return id;
}

function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || '';
}
function setToken(token) {
  wx.setStorageSync(TOKEN_KEY, token);
}
function getUser() {
  return wx.getStorageSync(USER_KEY) || null;
}
function setUser(user) {
  if (user) wx.setStorageSync(USER_KEY, user);
}
function getExpireAt() {
  return Number(wx.getStorageSync(EXP_KEY) || 0);
}
function getLoginKind() {
  return wx.getStorageSync(KIND_KEY) || '';
}
/** 保存 JWT 与有效期（不再保存服务端会话标识） */
function saveSession(res, kind) {
  setToken(res.token);
  wx.setStorageSync(EXP_KEY, Date.now() + (res.expires_in || 604800) * 1000);
  wx.setStorageSync(KIND_KEY, kind || 'wechat');
}
function clearToken() {
  [TOKEN_KEY, USER_KEY, EXP_KEY, KIND_KEY].forEach((k) => {
    try { wx.removeStorageSync(k); } catch (e) { /* ignore */ }
  });
}

/** 底层请求：只负责发一次，不参与 401 重登，避免递归 */
// ---------- 微信云托管通道（callContainer）----------
// 免服务器域名、免 downloadFile 域名，且默认域名不会过期；小程序端首选。
let cloudInited = false;
function cloudRunReady() {
  if (!config.CLOUD_ENV || !wx.cloud || typeof wx.cloud.callContainer !== 'function') return false;
  if (config.isDevtools && config.isDevtools()) return false; // 模拟器继续用本机后端
  if (!cloudInited) {
    try {
      wx.cloud.init({ env: config.CLOUD_ENV, traceUser: false });
      cloudInited = true;
    } catch (e) {
      return false;
    }
  }
  return true;
}

function parseBody(data) {
  if (typeof data !== 'string') return data;
  try { return JSON.parse(data); } catch (e) { return data; }
}

function cloudRequest(method, url, data, header) {
  return new Promise((resolve, reject) => {
    wx.cloud.callContainer({
      config: { env: config.CLOUD_ENV },
      path: '/api/v1' + url,
      method,
      data,
      header: Object.assign({ 'X-WX-SERVICE': config.CLOUD_SERVICE }, header),
      timeout: 30000,
      success(res) {
        const body = parseBody(res.data);
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body);
          return;
        }
        const detail =
          (body && typeof body === 'object' && typeof body.detail === 'string')
            ? body.detail
            : '请求失败(' + res.statusCode + ')';
        const err = new Error(detail);
        err.status = res.statusCode;
        reject(err);
      },
      fail(err) {
        const e = new Error('云托管通道异常：' + ((err && err.errMsg) || '未知错误'));
        e.status = 0;
        reject(e);
      },
    });
  });
}

function requestRaw(method, url, data) {
  const header = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) header.Authorization = 'Bearer ' + token;
  if (cloudRunReady()) return cloudRequest(method, url, data, header);
  return new Promise((resolve, reject) => {
    wx.request({
      url: base() + url,
      method,
      data,
      header,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          const detail =
            (res.data && typeof res.data === 'object' && typeof res.data.detail === 'string')
              ? res.data.detail
              : '请求失败(' + res.statusCode + ')';
          const err = new Error(detail);
          err.status = res.statusCode;
          reject(err);
        }
      },
      fail(err) {
        // 把实际请求的地址带出来：真机连不上时，第一眼就能看出是不是还在连 127.0.0.1
        const host = base();
        const where = host.replace(/^https?:\/\//, '').replace(/\/api\/v1$/, '');
        const isPlaceholder = host.indexOf('example.cn') >= 0;
        const e = new Error(isPlaceholder
          ? '当前是体验版/正式版，但后端域名还是占位符（' + where + '）。'
            + '请把真实 HTTPS 域名填进 utils/config.js 的 trial/release，并加入微信「服务器域名」白名单'
          : '网络异常：请求 ' + where + ' 失败。请确认手机与电脑同一网段，'
            + '或在「我的 → 后端地址（调试）」改成电脑当前 IP');
        e.status = 0;
        e.detail = err && err.errMsg;
        reject(e);
      },
    });
  });
}

function isAuthEndpoint(url) {
  return /^\/auth\//.test(url);
}

/** 401 自动重走静默登录并重放原请求（设计方案 7.5） */
function request(method, url, data) {
  return requestRaw(method, url, data).catch((err) => {
    const canRelogin =
      err.status === 401 && !isAuthEndpoint(url) && getLoginKind() === 'wechat';
    if (!canRelogin) throw err;
    return guestLogin().then(() => requestRaw(method, url, data));
  });
}

/** wx.login 取一次性 code（5 分钟有效，仅服务端使用） */
function wxLoginCode() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) resolve(res.code);
        else reject(new Error('wx.login 未返回 code，请检查小程序 AppID 配置'));
      },
      fail() {
        reject(new Error('微信登录失败，请检查网络或小程序 AppID 配置'));
      },
    });
  });
}

/** 微信静默登录：code 交给服务端 code2session，本地只拿 JWT */
function guestLogin() {
  return wxLoginCode()
    .then((code) => requestRaw('POST', '/auth/wechat/login', {
      code,
      device_id: getDeviceId(),
    }))
    .then((res) => {
      saveSession(res, 'wechat');
      return requestRaw('GET', '/auth/me').then((u) => {
        setUser(u);
        return u;
      });
    });
}

/** 滑动续期：旧 token → 新 7 天 JWT */
function refreshSession() {
  return requestRaw('POST', '/auth/refresh', {}).then((res) => {
    saveSession(res, getLoginKind() || 'wechat');
    return res;
  });
}

function applySession(res, kind) {
  saveSession(res, kind || 'account');
  setUser(res.user);
  return res.user;
}

/** 启动时校验 JWT；临近过期先续期；失败仅清除本地状态，不弹提示。 */
function restoreUser() {
  if (!getToken()) {
    clearToken();
    return Promise.resolve(null);
  }
  const kind = getLoginKind();
  const nearExpiry = getExpireAt() && getExpireAt() - Date.now() < REFRESH_AHEAD_MS;
  const pre = nearExpiry ? refreshSession().catch(() => null) : Promise.resolve(true);
  return pre.then(() => getMe()).catch((e) => {
    if (e.status && e.status < 500) {
      clearToken();
      // 微信静默身份：token 失效时自动重登一次，用户无感（设计方案 7.5）
      if (kind === 'wechat') return guestLogin().catch(() => null);
    }
    return null;
  });
}

function register(payload) {
  return request('POST', '/auth/register', payload).then((res) => applySession(res, 'account'));
}
function login(payload) {
  return request('POST', '/auth/login', payload).then((res) => applySession(res, 'account'));
}
function getMe() {
  return request('GET', '/auth/me').then((u) => {
    setUser(u);
    return u;
  });
}
function logout() {
  return request('POST', '/auth/logout', {}).then(
    (res) => { clearToken(); return res; },
    (e) => { clearToken(); throw e; },
  );
}

// 与 PC 端 travel-portal/src/api.ts 保持一致的展示口径
const MODE_ORDER = ['leisure', 'blitz', 'premium', 'checkin'];
const MODE_EMOJI = {
  leisure: '🌿', blitz: '⚡', premium: '✨', checkin: '📸',
};
const CATEGORY_NAME = {
  scenic: '景点', food: '美食', hotel: '住宿', leisure: '休闲', study: '游学',
};
const CATEGORY_TABS = [
  { code: 'all', name: '全部' },
  { code: 'scenic', name: '景点' },
  { code: 'food', name: '美食' },
  { code: 'hotel', name: '住宿' },
  { code: 'leisure', name: '休闲' },
];
const PARTY_TYPES = [
  { code: 'couple', label: '情侣 / 朋友' },
  { code: 'family', label: '家庭亲子' },
  { code: 'solo', label: '独自出行' },
  { code: 'group', label: '团队出行' },
];

module.exports = {
  get BASE() { return base(); },
  get STATIC_BASE() { return staticBase(); },
  absImage, withImages,
  MODE_ORDER, MODE_EMOJI, CATEGORY_NAME, CATEGORY_TABS, PARTY_TYPES,
  getToken, setToken, clearToken, getUser, setUser,
  getDeviceId, getLoginKind, getExpireAt, saveSession,
  request, requestRaw, refreshSession, restoreUser,
  guestLogin, silentLogin: guestLogin, wxLoginCode,
  register, login, getMe, logout,

  // 业务接口
  getModes() {
    return request('GET', '/trip-modes');
  },
  // ---- 预设主题路线（游学线）：列表 / 详情（含 date_gate 结论） ----
  getPresetRoutes(params) {
    return request('GET', '/preset-routes', params);
  },
  getPresetRoute(code, params) {
    return request('GET', '/preset-routes/' + encodeURIComponent(code), params).then((res) => {
      const fix = (s) => Object.assign({}, s, { image: absImage(s.image) });
      res.stops = (res.stops || []).map(fix);
      res.addon_stops = (res.addon_stops || []).map(fix);
      return res;
    });
  },
  // ---- 个性化：权重维度元数据 / 预览 / 重排 ----
  getWeightMetadata() {
    return request('GET', '/weight-metadata');
  },
  previewWeights(payload) {
    return request('POST', '/trips/preview', payload).then((res) => {
      res.items = (res.items || []).map((it) =>
        Object.assign({}, it, { image: absImage(it.image) }),
      );
      res.changed = (res.changed || []).map((c) =>
        Object.assign({}, c, { image: absImage(c.image) }),
      );
      return res;
    });
  },
  reweightTrip(tripId, payload) {
    return request('POST', '/trips/' + tripId + '/reweight', payload);
  },
  listPois(params) {
    return request('GET', '/pois', params).then((res) => {
      res.items = (res.items || []).map(withImages);
      return res;
    });
  },
  /** 标签字典（T1 筛选器 / 需求页偏好）：code 与后端 poi_tag 完全一致 */
  getTags() {
    return request('GET', '/tags').then((rows) => (rows || []).map((t) => ({
      code: t.code, name: t.name,
    })));
  },
  /** 四模式对比（不落库，避免污染统计） */
  compare(payload) {
    return request('POST', '/trips/compare', payload).then((res) => {
      res.results = res.results || [];
      return res;
    });
  },
  /** 天气（Open-Meteo 服务端代理）：实况 + 逐日预报，坐标须为 WGS-84 */
  getWeather(params) {
    return request('GET', '/weather', params);
  },
  getForecast(params) {
    return request('GET', '/weather/forecast', params);
  },
  getPoi(id) {
    return request('GET', '/pois/' + id).then(withImages);
  },
  generateTrip(payload) {
    return request('POST', '/trips/generate', payload);
  },
  rebalance(tripId, payload) {
    return request('POST', '/trips/' + tripId + '/rebalance', payload);
  },
  slotCandidates(tripId, dayIndex, slot) {
    return request(
      'GET',
      '/trips/' + tripId + '/days/' + dayIndex + '/slots/' + slot + '/candidates?page_size=10',
    );
  },
  // ---- T4 增量重算：只改天数 / 预算，保留原日程 ----
  replanTrip(tripId, payload) {
    return request('POST', '/trips/' + tripId + '/replan', payload);
  },
  // ---- T7 AI 润色与小贴士 ----
  getEnrichment(tripId) {
    return request('GET', '/trips/' + tripId + '/enrichment');
  },
  refreshEnrichment(tripId) {
    return request('POST', '/trips/' + tripId + '/enrichment', { force: true });
  },
  // ---- T8 出行前一日订阅提醒 ----
  subscribeTrip(tripId, payload) {
    return request('POST', '/trips/' + tripId + '/subscribe', payload || {});
  },
  // ---- #9 路线分段（距离 / 耗时） ----
  routeSegments(tripId) {
    return request('GET', '/trips/' + tripId + '/route-segments');
  },
  saveTrip(tripId) {
    return request('POST', '/trips/' + tripId + '/save', {});
  },
  // ---- T5 分享海报素材（#7）：排版数据 + 小程序码/二维码（canvas 端绘制） ----
  createPoster(tripId) {
    return request('POST', '/trips/' + tripId + '/poster', {}).then((res) => {
      if (res && res.qr && res.qr.url) res.qr.url = absImage(res.qr.url);
      return res;
    });
  },
  getTrip(tripId) {
    return request('GET', '/trips/' + tripId);
  },
  myTrips() {
    return request('GET', '/trips?page=1&page_size=20');
  },
  deleteTrip(tripId) {
    return request('DELETE', '/trips/' + tripId);
  },

  // ---- 专属问答「问小旅」（后端 /qa/*，未配大模型时自动走知识库直出） ----
  qaStatus() {
    return request('GET', '/qa/status');
  },
  qaSuggestions() {
    return request('GET', '/qa/suggestions');
  },
  qaChat(payload) {
    return request('POST', '/qa/chat/sync', payload).then((res) => {
      res.refs = res.refs || [];
      return res;
    });
  },
  qaConversations() {
    return request('GET', '/qa/conversations?page=1&page_size=20');
  },
  qaConversation(id) {
    return request('GET', '/qa/conversations/' + encodeURIComponent(id)).then((res) => {
      res.messages = (res.messages || []).map((m) =>
        Object.assign({}, m, { refs: m.refs || [] }),
      );
      return res;
    });
  },
  qaJudge(tripId, conversationId) {
    return request('POST', '/qa/judge', {
      trip_id: tripId, conversation_id: conversationId || undefined,
    });
  },
};
