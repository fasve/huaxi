const api = require('../../utils/api');

Page({
  data: {
    mode: 'login', // login | register
    busy: false,
    err: '',
    form: {
      account: '', password: '',
      username: '', nickname: '', phone: '', password2: '',
    },
  },

  switchTab(e) {
    this.setData({ mode: e.currentTarget.dataset.mode, err: '' });
  },

  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ ['form.' + field]: e.detail.value, err: '' });
  },

  submit() {
    const f = this.data.form;
    const mode = this.data.mode;
    let err = '';

    if (mode === 'login') {
      if (!f.account.trim() || !f.password) err = '请填写账号和密码';
    } else if (!/^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$/.test(f.username.trim())) {
      err = '用户名需为 2~32 位中英文、数字或下划线';
    } else if (f.password.length < 6) {
      err = '密码至少 6 位';
    } else if (f.password !== f.password2) {
      err = '两次输入的密码不一致';
    } else if (f.phone.trim() && !/^1\d{10}$/.test(f.phone.trim())) {
      err = '手机号格式不正确（11 位数字）';
    }

    if (err) {
      this.setData({ err });
      return;
    }

    let task;
    if (mode === 'login') {
      task = api.login({ account: f.account.trim(), password: f.password });
    } else {
      const payload = { username: f.username.trim(), password: f.password };
      if (f.nickname.trim()) payload.nickname = f.nickname.trim();
      if (f.phone.trim()) payload.phone = f.phone.trim();
      task = api.register(payload);
    }

    this.setData({ busy: true, err: '' });
    task
      .then(() => {
        getApp().globalData.userInfo = api.getUser();
        wx.showToast({ title: mode === 'login' ? '登录成功' : '注册成功', icon: 'success' });
        setTimeout(() => this.goBack(), 600);
      })
      .catch((e) => this.setData({ busy: false, err: e.message || '操作失败' }));
  },

  guest() {
    this.setData({ busy: true, err: '' });
    api.guestLogin()
      .then(() => {
        getApp().globalData.userInfo = api.getUser();
        wx.showToast({ title: '已进入游客模式', icon: 'success' });
        setTimeout(() => this.goBack(), 600);
      })
      .catch((e) => this.setData({ busy: false, err: e.message || '操作失败' }));
  },

  goBack() {
    const pages = getCurrentPages();
    if (pages.length > 1) wx.navigateBack();
    else wx.switchTab({ url: '/pages/mine/mine' });
  },
});
