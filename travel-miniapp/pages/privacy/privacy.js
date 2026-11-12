// 隐私保护指引 / 服务条款（设计方案 7.2 / 7.6 / 7.7 / 7.10）
// 文案口径与「旅游 - 旅游信息查询 / 工具类」类目一致：不出现预订、下单、购买、代订等交易表述。
const config = require('../../utils/config');

const DOCS = {
  privacy: {
    title: '小程序用户隐私保护指引',
    sections: [
      {
        title: '服务性质与适用范围',
        paragraphs: [
          '「花溪旅行」是由本小程序运营者提供的免费旅游信息查询与行程规划工具，面向花溪区公共资源信息展示、路线参考与费用估算。',
          '本服务仅提供信息参考，不提供酒店、门票、交通等交易或代办服务，不涉及在线支付、订单、预订、代订等环节。行程中的费用、耗时、开放时段均为估算或公开信息整理，请以现场实际情况为准。',
          '本指引适用于小程序游客端；PC 游客端与管理后台另按其自身说明处理。',
        ],
      },
      {
        title: '我们收集哪些信息',
        paragraphs: [
          '微信登录凭证：当你主动使用登录、保存行程等需要身份的功能时，小程序调用 wx.login 获取一次性 code，交由服务端向微信换取 openid 用于建立匿名标识。code 与 session_key 仅存于服务端，不下发到前端，不写入 JWT。',
          '账号信息：若你选择注册账号，我们会保存你填写的用户名与密码的不可逆哈希，不保存明文密码。我们不主动索取头像、昵称、手机号。',
          '本地存储：为免重复登录与保留偏好设置，我们会在你的设备本地存储登录令牌（有效期 7 天）、出行模式偏好、行程草稿与本次指引的确认状态。你可以随时清除。',
          '日志信息：服务端会记录请求时间、接口路径、状态码与网络地址用于故障排查与安全审计，不与第三方共享用于营销。',
        ],
      },
      {
        title: '位置信息（重点说明）',
        paragraphs: [
          '当前版本不调用 wx.getLocation，不收集你的精确位置、行踪轨迹或后台定位。地图展示使用已公开的 POI 坐标，默认以贵阳市花溪区为展示范围。',
          '如后续版本启用「附近资源排序与通勤估算」，我们会先更新本指引并在功能触发前通过微信隐私授权弹窗单独征求同意；你拒绝时自动回落为默认花溪区范围，不阻断浏览与行程生成。',
          '地图与地名解析会向地图服务提供方发送待查询的地点名称或公开 POI 坐标，不包含你的实时位置。',
        ],
      },
      {
        title: '我们不收集、不做的事',
        paragraphs: [
          '不收集手机号、通讯录、相册、身份证号、人脸等敏感个人信息；不索取与功能无关的隐私权限。',
          '不出售、出租或对外提供你的个人信息用于广告投放；不做跨站用户画像，不向第三方共享用于营销目的。',
          '不对用户生成内容做自动化营销推送；不提供任何形式的交易、预订、代订或支付能力。',
        ],
      },
      {
        title: '信息存储、保护与期限',
        paragraphs: [
          '全链路使用 HTTPS 传输；服务端数据库部署于中国内地，登录令牌为标准 JWT，有效期 7 天并支持到期前自动续期。',
          '注销或退出后，本地令牌立即清除；服务端会话可通过退出接口即时吊销。已保存的行程与账号信息在你主动删除后同步移除，日志按最短必要期限留存。',
          '若发生个人信息泄露等安全事件，我们将按法律法规要求及时告知并上报。',
        ],
      },
      {
        title: '第三方服务与 SDK',
        paragraphs: [
          '微信登录与小程序基础能力（腾讯）：用于换取 openid、实现登录与页面运行。',
          '腾讯地图（腾讯位置服务）：用于小程序内地图底图与点位标注；仅传递公开 POI 坐标。',
          '高德地图（高德软件）：仅服务端用于经纬度与地名互转（逆地理 / 城市级定位），不下发到前端。',
          'Open-Meteo：用于公开天气实况与预报；按行政区划或公开坐标查询，不携带个人标识。',
          '图片资源来自自有素材及 Wikimedia Commons、Openverse、Pixabay、Pexels 等授权来源，图片文件托管于本服务静态域名或 CDN。',
          '上述第三方仅在完成对应功能所必需范围内处理数据；如第三方政策更新，我们会同步评估并调整本指引。',
        ],
      },
      {
        title: '你的权利与操作路径',
        paragraphs: [
          '查看与撤回同意：进入「我的 → 隐私与协议」可随时重新阅读本指引、撤回同意或删除本地数据；撤回不影响撤回前基于同意已进行的处理。',
          '删除与注销：在「我的行程」中删除单条行程，或通过联系方式申请删除账号及其关联数据，我们将在核验身份后处理。',
          '拒绝提供非必要信息仍可浏览公开资源与生成匿名行程；仅保存行程、跨设备同步等需要身份的功能不可用。',
        ],
      },
      {
        title: '未成年人保护',
        paragraphs: [
          '本服务面向一般公众，不专门面向未满十四周岁儿童。若监护人发现儿童个人信息被提交，可通过下方联系方式申请删除。',
        ],
      },
      {
        title: '指引更新与联系方式',
        paragraphs: [
          '本指引版本号见页首；内容发生实质变更时，会在小程序内以弹窗形式重新征求同意。',
          '如对本指引有疑问、投诉或需行使权利，请联系运营者邮箱（上线前替换为真实邮箱）：privacy@example.cn，我们将在 15 个工作日内答复。',
          '运营主体、ICP 备案号与公安备案号以「我的 → 隐私与协议」页脚及小程序后台公示信息为准。',
        ],
      },
    ],
  },
  terms: {
    title: '服务条款',
    sections: [
      {
        title: '服务内容',
        paragraphs: [
          '本小程序提供花溪区旅游资源浏览、按模式生成参考行程、出行方式与开销估算、天气参考及游学路线讲解等信息服务。',
          '所有结果为基于公开数据与算法规则的参考建议，不构成出行承诺、价格承诺或商业邀约；本服务不含交易、预订、代订、支付功能。',
        ],
      },
      {
        title: '内容来源与知识产权',
        paragraphs: [
          'POI 名称、坐标、开放时段、票价等为公开信息整理，可能滞后或变更；图片来源与授权信息在管理端逐张登记。',
          '本服务的界面设计、算法配置与原创文案归运营者所有；第三方内容的权利归各自权利人所有。',
          '如当前版本启用 AI 生成的贴士或润色文案，会明确标注「内容由 AI 生成，仅供参考」；相关文案不作医疗、安全类绝对化承诺。',
        ],
      },
      {
        title: '用户行为规范',
        paragraphs: [
          '不得利用本服务发布或提交违法违规、侵害他人权益的内容；自定义文本提交前会经过内容安全检测，违规内容将被拒绝入库。',
          '不得对本服务进行逆向、抓取、压力测试或其他影响正常运行的操作。',
        ],
      },
      {
        title: '免责与适用法',
        paragraphs: [
          '因不可抗力、第三方服务中断、公开数据错误或用户自身判断导致的损失，运营者在法律允许范围内不承担责任。',
          '本条款适用中华人民共和国法律；争议优先协商解决，协商不成提交运营者所在地有管辖权的人民法院。',
        ],
      },
      {
        title: '条款变更',
        paragraphs: [
          '条款更新将在本页面公布并更新版本号；继续使用即视为接受更新后的条款，重大变更会另行提示。',
        ],
      },
    ],
  },
};

Page({
  data: {
    doc: 'privacy',
    title: DOCS.privacy.title,
    version: config.POLICY_VERSION,
    updated: '2026-11-11',
    sections: [],
    showAgree: false,
  },

  onLoad(options) {
    const doc = options && options.doc === 'terms' ? 'terms' : 'privacy';
    const fromConsent = !!options && options.from === 'consent';
    this.setData({ doc, showAgree: fromConsent });
    this.applyDoc(doc);
    wx.setNavigationBarTitle({ title: DOCS[doc].title });
  },

  applyDoc(doc) {
    this.setData({ title: DOCS[doc].title, sections: DOCS[doc].sections });
  },

  switchDoc(e) {
    const doc = e.currentTarget.dataset.doc === 'terms' ? 'terms' : 'privacy';
    if (doc === this.data.doc) return;
    this.setData({ doc });
    this.applyDoc(doc);
    wx.setNavigationBarTitle({ title: DOCS[doc].title });
  },

  /** 同意并继续：记录版本化确认状态，供启动检查与「我的」页撤回 */
  agree() {
    wx.setStorageSync(config.CONSENT_KEY, {
      version: config.POLICY_VERSION,
      accepted: true,
      at: Date.now(),
    });
    wx.showToast({ title: '已同意', icon: 'success' });
    this.backToMain();
  },

  /** 暂不同意：不阻断主流程，下次不再重复弹窗；可在「我的」页重新确认 */
  later() {
    wx.setStorageSync(config.CONSENT_KEY, {
      version: config.POLICY_VERSION,
      accepted: false,
      at: Date.now(),
    });
    this.backToMain();
  },

  backToMain() {
    setTimeout(() => {
      wx.navigateBack({
        fail() { wx.switchTab({ url: '/pages/home/home' }); },
      });
    }, 350);
  },

  openPrivacyFromMine() {
    this.switchDoc({ currentTarget: { dataset: { doc: 'privacy' } } });
  },
});
