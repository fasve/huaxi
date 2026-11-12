// 校验 config.js 的环境探测：develop 走本机/局域网，trial/release 必须走 HTTPS 正式域名
//
// 覆盖两层：
//   1) 模块导出的 API_BASE / STATIC_BASE（按 envVersion 选择）
//   2) 运行时的 getApiBase() / getStaticBase()（api.js 实际调用的入口）
//      —— 这里出错的后果最严重：体验版/正式版回落到 http://LAN_HOST 会直接请求失败。
//
// 注意：config.js 的函数读全局 wx，所以每个场景必须在设置 stub 后 **立即取值**，
// 不能先批量加载再统一断言（否则全局 wx 已被后面的场景覆盖）。
function probe(envVersion, platform, brand) {
  global.wx = {
    getAccountInfoSync: () => ({ miniProgram: { envVersion } }),
    getDeviceInfo: () => ({ platform, brand: brand || '' }),
    getStorageSync: () => '',
  };
  delete require.cache[require.resolve('../utils/config.js')];
  const cfg = require('../utils/config.js');
  return {
    env: envVersion,
    apiBase: cfg.API_BASE,
    staticBase: cfg.STATIC_BASE,
    api: cfg.getApiBase(),
    stat: cfg.getStaticBase(),
    lanHost: cfg.LAN_HOST,
  };
}

const sim = probe('develop', 'devtools', 'devtools');
const phone = probe('develop', 'android', 'huawei');
const trial = probe('trial', 'android', 'huawei');
const release = probe('release', 'ios', 'apple');

console.log('[develop/模拟器] API =', sim.api, '| STATIC =', sim.stat);
console.log('[develop/真机]   API =', phone.api, '| LAN_HOST =', phone.lanHost);
console.log('[trial]          API =', trial.api, '| STATIC =', JSON.stringify(trial.stat));
console.log('[release]        API =', release.api, '| STATIC =', JSON.stringify(release.stat));

const fail = (m) => { throw new Error(m); };
const isPrivate = (u) => /127\.0\.0\.1|localhost|192\.168\.|10\.\d+\.|172\.(1[6-9]|2\d|3[01])\./.test(u);

if (!sim.api.includes('127.0.0.1')) fail('develop 模拟器应走 127.0.0.1');
if (!phone.api.includes(phone.lanHost)) fail('develop 真机应走局域网 IP');
if (!trial.api.startsWith('https://')) fail('trial 必须是 HTTPS 正式域名');
if (!release.api.startsWith('https://')) fail('release 必须是 HTTPS 正式域名');
if (isPrivate(release.api)) fail('release 不允许回落到内网地址：' + release.api);
if (isPrivate(trial.api)) fail('trial 不允许回落到内网地址：' + trial.api);
if (release.stat && !release.stat.startsWith('https://')) {
  fail('release 图片基址必须是 HTTPS（留空则走 cloud:// 或占位图）');
}
console.log('配置检查通过');
