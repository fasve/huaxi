const api = require('../../utils/api');
const config = require('../../utils/config');

Page({
  data: {
    trips: [],
    loading: true,
    user: null,
    apiHost: '',
    // 正式版不暴露「改后端地址」入口：用户能把请求指向任意地址，属审核与安全隐患
    canDebugHost: config.ENV !== 'release',
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 3 });
    }
    this.setData({ user: api.getUser(), apiHost: api.BASE });
    this.refresh();
  },

  /** 校验会话 → 取回身份 → 加载该身份的行程 */
  refresh() {
    if (!api.getToken()) {
      this.setData({ user: null, trips: [], loading: false });
      return;
    }
    api.getMe()
      .then((u) => {
        getApp().globalData.userInfo = u;
        this.setData({ user: u });
        return this.fetchTrips();
      })
      .catch((e) => {
        if (e.status && e.status < 500) {
          api.clearToken();
          this.setData({ user: null, trips: [], loading: false });
        } else {
          this.setData({ loading: false });
          wx.showToast({ title: e.message, icon: 'none' });
        }
      });
  },

  fetchTrips() {
    if (!api.getToken()) {
      this.setData({ trips: [], loading: false });
      return Promise.resolve();
    }
    this.setData({ loading: true });
    return api.myTrips()
      .then((res) => {
        const items = (res.items || []).map((t) => Object.assign({}, t, {
          emoji: api.MODE_EMOJI[t.mode] || '🧭',
          status_name: t.status === 'saved' ? '已保存' : '草稿',
          created_text: t.created_at ? String(t.created_at).replace('T', ' ').slice(0, 16) : '',
          usage_percent: t.budget > 0 ? Math.round((t.total_cost / t.budget) * 100) : 0,
        }));
        this.setData({ trips: items, loading: false });
      })
      .catch((e) => {
        this.setData({ loading: false });
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 去定制 tab（tabBar 页不能带参数） */
  goPlan() {
    wx.switchTab({ url: '/pages/request/request' });
  },

  gotoLogin() {
    wx.navigateTo({ url: '/pages/login/login' });
  },

  guestLogin() {
    wx.showLoading({ title: '请稍候' });
    api.guestLogin()
      .then((u) => {
        wx.hideLoading();
        getApp().globalData.userInfo = u;
        this.setData({ user: u });
        wx.showToast({ title: '已进入游客模式', icon: 'success' });
        return this.fetchTrips();
      })
      .catch((e) => {
        wx.hideLoading();
        wx.showToast({ title: e.message, icon: 'none' });
      });
  },

  /** 调试：改后端地址（换 Wi-Fi / IP 变了不用改代码，重启小程序生效） */
  editApiHost() {
    const current = config.API_BASE.replace('/api/v1', '');
    wx.showModal({
      title: '后端地址',
      editable: true,
      placeholderText: 'http://192.168.1.10:8000',
      content: current,
      success: (res) => {
        if (!res.confirm) return;
        const v = String(res.content || '').trim();
        config.setHost(v);
        wx.showToast({ title: v ? '已保存，重启小程序生效' : '已恢复默认', icon: 'none' });
      },
    });
  },

  openPolicy(e) {
    const doc = e.currentTarget.dataset.doc === 'terms' ? 'terms' : 'privacy';
    wx.navigateTo({ url: '/pages/privacy/privacy?doc=' + doc });
  },

  /** 撤回同意：清除版本化确认状态，下次启动重新征求；不删除已保存行程 */
  withdrawConsent() {
    wx.showModal({
      title: '撤回隐私同意',
      content: '撤回后将清除本地确认状态并退出登录，下次启动会重新征求同意。已保存的行程不会被删除。',
      confirmText: '撤回',
      confirmColor: '#e6533a',
      success: (res) => {
        if (!res.confirm) return;
        try { wx.removeStorageSync(config.CONSENT_KEY); } catch (e) { /* ignore */ }
        api.logout().catch(() => {}).then(() => {
          getApp().globalData.userInfo = null;
          this.setData({ user: null, trips: [], loading: false });
          wx.showToast({ title: '已撤回', icon: 'success' });
        });
      },
    });
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需重新登录才能查看已保存的行程',
      confirmText: '退出',
      confirmColor: '#e6533a',
      success: (res) => {
        if (!res.confirm) return;
        api.logout()
          .catch(() => {}) // 会话已过期也清本地状态
          .then(() => {
            getApp().globalData.userInfo = null;
            this.setData({ user: null, trips: [], loading: false });
            wx.showToast({ title: '已退出', icon: 'success' });
          });
      },
    });
  },

  openTrip(e) {
    wx.navigateTo({ url: '/pages/trip/trip?id=' + e.currentTarget.dataset.id });
  },

  removeTrip(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '删除行程',
      content: '删除后不可恢复，确定删除？',
      confirmText: '删除',
      confirmColor: '#e6533a',
      success: (res) => {
        if (!res.confirm) return;
        api.deleteTrip(id)
          .then(() => {
            wx.showToast({ title: '已删除', icon: 'success' });
            this.fetchTrips();
          })
          .catch((e2) => wx.showToast({ title: e2.message, icon: 'none' }));
      },
    });
  },
});
