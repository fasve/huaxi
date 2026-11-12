// 花溪旅行 · 游客端
const api = require('./utils/api');
const config = require('./utils/config');

App({
  globalData: {
    userInfo: null,
    // 保存的行程 id（"我的"页使用）
    savedTripId: '',
    // 最近一次生成的行程 id（行程页返回时复用）
    lastTripId: '',
    // tabBar 页之间传参：首页/对比页 → 定制页
    pendingMode: '',
    pendingPlan: null,
  },

  onLaunch() {
    // 体验版/正式版：先初始化云托管环境，保证 <image src="cloud://..."> 与 callContainer 都能用
    try {
      if (!config.isDevtools() && wx.cloud && config.CLOUD_ENV) {
        wx.cloud.init({ env: config.CLOUD_ENV, traceUser: false });
      }
    } catch (e) { /* 云能力不可用时自动回落 */ }

    // 只校验已有会话，不再自动创建游客身份；
    // 账号登录 / 游客体验由「我的」页显式选择，避免注册入口被静默登录盖掉。
    api.restoreUser().then((user) => {
      this.globalData.userInfo = user;
    });
    // 合规：首次启动 / 指引版本更新时征求同意（方案 7.6、7.10）
    setTimeout(() => this.ensurePrivacyConsent(), 400);
    this.checkWxPrivacy();
  },

  /** 版本化的首次同意弹窗；选择「查看指引」不写状态，用户决定后再记录 */
  ensurePrivacyConsent() {
    let rec = null;
    try { rec = wx.getStorageSync(config.CONSENT_KEY); } catch (e) { /* ignore */ }
    if (rec && rec.version === config.POLICY_VERSION) return;
    wx.showModal({
      title: '隐私指引与服务条款',
      content: '我们仅在你需要登录或保存行程时使用微信登录凭证，不收集精确位置，不提供交易与预订服务。继续即表示已阅读并同意《小程序用户隐私保护指引》。',
      confirmText: '同意并继续',
      cancelText: '查看指引',
      success: (res) => {
        if (res.confirm) {
          wx.setStorageSync(config.CONSENT_KEY, {
            version: config.POLICY_VERSION, accepted: true, at: Date.now(),
          });
        } else if (res.cancel) {
          wx.navigateTo({ url: '/pages/privacy/privacy?doc=privacy&from=consent' });
        }
      },
    });
  },

  /** 微信侧隐私校验兼容：仅在后台已开启且基础库支持时生效，失败不阻断主流程 */
  checkWxPrivacy() {
    if (typeof wx.getPrivacySetting !== 'function') return;
    wx.getPrivacySetting({
      success: (res) => {
        if (res.needAuthorization && typeof wx.requirePrivacyAuthorize === 'function') {
          wx.requirePrivacyAuthorize({ success() {}, fail() {} });
        }
      },
      fail() {},
    });
  },
});
