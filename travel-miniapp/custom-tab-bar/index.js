// 自定义 tabBar：原生 tabBar 在开发者工具里加载图标异常（同文件用 <image> 显示正常），
// 这里用组件 + <image> 自绘，保证小程序 / 真机 / 开发者工具表现一致。
Component({
  data: {
    selected: 0,
    list: [
      {
        pagePath: '/pages/home/home',
        text: '首页',
        icon: '/assets/tabbar/ic-home.png',
        active: '/assets/tabbar/ic-home-on.png',
      },
      {
        pagePath: '/pages/explore/explore',
        text: '发现',
        icon: '/assets/tabbar/ic-discover.png',
        active: '/assets/tabbar/ic-discover-on.png',
      },
      {
        pagePath: '/pages/request/request',
        text: '定制',
        icon: '/assets/tabbar/ic-plan.png',
        active: '/assets/tabbar/ic-plan-on.png',
      },
      {
        pagePath: '/pages/mine/mine',
        text: '我的',
        icon: '/assets/tabbar/ic-mine.png',
        active: '/assets/tabbar/ic-mine-on.png',
      },
    ],
  },

  methods: {
    switchTab(e) {
      const data = e.currentTarget.dataset;
      const index = Number(data.index);
      if (index === this.data.selected) return;
      wx.switchTab({ url: data.path });
    },
  },
});
