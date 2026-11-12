// 小程序三环境域名与合规常量（设计方案 7.4 / 7.10）
//
// 上线前必做：把 trial / release 的占位域名换成真实域名，且三处完全一致：
//   1) 已 ICP 备案（服务器在中国内地）
//   2) 已部署 HTTPS 证书（TLS 1.2+，证书域名匹配）
//   3) 已在微信公众平台「开发管理 → 开发设置 → 服务器域名」登记
// request 合法域名填 api 域；downloadFile 合法域名填 static/CDN 域。
//
// 手机（预览 / 真机调试）访问不到 127.0.0.1——那是手机自己。
// 必须填**开发机的局域网 IP**，且手机与电脑在同一个 Wi-Fi / 路由器下。
// 换网络 / 换机器时：① 改下面这行 LAN_HOST；或
// ② 在「我的 → 后端地址（调试）」里改（存本地，重启小程序生效，不用动代码）。
const LAN_HOST = '10.22.59.107';

// ===== 正式上线只改这一处 =====
// 备案域名（不带 https://、不带路径）。填好之后 trial（体验版）与 release（正式版）
// 都会自动指向 https://<PROD_DOMAIN>/api/v1，图片也走同一个域。
// 例：const PROD_DOMAIN = 'api.your-domain.cn';
const PROD_DOMAIN = 'travel-api-346220-10-1359209266.sh.run.tcloudbase.com';

// ===== 微信云托管（推荐通道）=====
// 云托管默认域名被微信禁止用于正式环境（服务器域名会报"仅测试使用"），
// 因此小程序端改用 wx.cloud.callContainer：不需要配服务器域名、不过期。
const CLOUD_ENV = 'prod-d7gnymd9e909581e8';
const CLOUD_SERVICE = 'travel-api';

// 图片域名：cloudrun 默认域名同样不能用于 downloadFile 合法域名，
// 这里留空 → 小程序端走"无图占位"（淡底 + 名称前两字），不会裂图。
// 等你绑定了自己的已备案自定义域名（云托管 → 服务设置 → 自定义域名），把它填进来：
//   const IMAGE_BASE = 'https://img.你的域名';
const IMAGE_BASE = '';

// 云存储 fileID 前缀（cloud://<env>.<bucket>），图片按 /static/poi/... 原路径存放
const CLOUD_FILE_PREFIX = 'prod-d7gnymd9e909581e8.7072-prod-d7gnymd9e909581e8-1359209266';

// 图片单独走 CDN 时填这里；留空则与 PROD_DOMAIN 同域
const CDN_DOMAIN = '';
const PROD_API = PROD_DOMAIN ? 'https://' + PROD_DOMAIN + '/api/v1' : 'https://api.example.cn/api/v1';
const PROD_STATIC = CDN_DOMAIN ? 'https://' + CDN_DOMAIN : (PROD_DOMAIN ? 'https://' + PROD_DOMAIN : 'https://cdn.example.cn');


// 调试用：运行时覆盖后端地址（换 Wi-Fi 后自救用）
const HOST_KEY = 'travel_api_host';

function storedHost() {
  try {
    return String(wx.getStorageSync(HOST_KEY) || '').trim();
  } catch (e) {
    return '';
  }
}

/** 是否在开发者工具的「模拟器」里跑（不含真机、真机调试） */
function isDevtools() {
  try {
    // wx.getDeviceInfo 是 getSystemInfoSync 的替代（后者 2.20.1 起不再维护）
    const info = typeof wx.getDeviceInfo === 'function' ? wx.getDeviceInfo() : wx.getSystemInfoSync();
    const s = info || {};
    const platform = String(s.platform || '').toLowerCase();
    const brand = String(s.brand || '').toLowerCase();
    if (platform !== 'devtools') return false;
    // 模拟器 brand 固定为 devtools；「真机调试」platform 同样是 devtools，
    // 但 brand 是手机品牌（huawei / xiaomi / apple…），必须走局域网 IP。
    return brand === '' || brand === 'devtools';
  } catch (e) {
    // 拿不到系统信息（Node 模拟器 / 极低基础库）→ 按模拟器处理，退回 localhost 更稳
    return true;
  }
}

// 模拟器用 localhost，真机用局域网 IP；本地覆盖优先
const OVERRIDE = storedHost();
const LOCAL_ORIGIN = OVERRIDE
  || (isDevtools() ? 'http://127.0.0.1:8000' : 'http://' + LAN_HOST + ':8000');

const DOMAINS = {
  develop: {
    api: LOCAL_ORIGIN + '/api/v1',
    static: LOCAL_ORIGIN,
  },
  trial: {
    api: PROD_API,
    static: PROD_STATIC,
  },
  release: {
    api: PROD_API,
    static: PROD_STATIC,
  },
};

// 隐私指引版本号：内容有实质变更时 +1，用户需重新确认
const POLICY_VERSION = '2026.11.1';
const CONSENT_KEY = 'travel_privacy_consent_v1';

// T8 出行前一日订阅消息模板 ID：在微信公众平台申请后填入；
// 留空时前端不发起订阅授权，避免无效调用（后端开关同样默认关闭）。
const TRIP_REMINDER_TEMPLATE_ID = '';

/** 环境识别：开发版 / 体验版 / 正式版；异常时按 develop 处理，避免误连生产 */
function detectEnv() {
  try {
    const info = wx.getAccountInfoSync && wx.getAccountInfoSync();
    const v = info && info.miniProgram && info.miniProgram.envVersion;
    if (v === 'release' || v === 'trial' || v === 'develop') return v;
  } catch (e) { /* 低版本基础库或非小程序环境 */ }
  return 'develop';
}

const ENV = detectEnv();
const PICK = DOMAINS[ENV] || DOMAINS.develop;

/** 当前生效的请求/静态地址：优先本地覆盖（换网络后无需重启即可生效）
 *  注意：非 develop 环境绝不能回落到局域网 http 地址——真机上 http://LAN_HOST 必然失败，
 *  而且明文 HTTP 会被微信拦截（合法域名只允许 HTTPS）。体验版/正式版一律走 PROD_API。 */
function apiOrigin() {
  const o = storedHost();
  if (o) return o;
  if (ENV !== 'develop') return 'https://' + PROD_DOMAIN;
  return isDevtools() ? 'http://127.0.0.1:8000' : 'http://' + LAN_HOST + ':8000';
}
function getApiBase() { return apiOrigin() + '/api/v1'; }
// 图片基址：develop 用本机；trial/release 用 CDN，未配置则返回空 → 走 cloud:// 或占位图
function getStaticBase() {
  const o = storedHost();
  if (o) return o;
  if (ENV !== 'develop') return CDN_DOMAIN ? 'https://' + CDN_DOMAIN : (IMAGE_BASE || '');
  if (isDevtools()) return 'http://127.0.0.1:8000';
  return IMAGE_BASE;
}

module.exports = {
  ENV,
  DOMAINS,
  LAN_HOST,
  HOST_KEY,
  PROD_DOMAIN,
  API_BASE: PICK.api,
  STATIC_BASE: PICK.static,
  POLICY_VERSION,
  CONSENT_KEY,
  TRIP_REMINDER_TEMPLATE_ID,
  IS_PROD: ENV === 'release',
  isDevtools,
  apiOrigin, getApiBase, getStaticBase, CLOUD_ENV, CLOUD_SERVICE, IMAGE_BASE, CLOUD_FILE_PREFIX,
  /** 设置/清除后端地址（传空字符串表示恢复默认） */
  setHost(host) {
    const v = String(host || '').trim().replace(/\/+$/, '');
    try {
      if (v) wx.setStorageSync(HOST_KEY, v);
      else wx.removeStorageSync(HOST_KEY);
    } catch (e) { /* 忽略存储失败 */ }
    return v;
  },
};
