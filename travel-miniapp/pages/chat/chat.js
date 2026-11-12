// 问小旅：问答页（复用 /qa/* 接口；未配置大模型时后端返回 degraded=true 的知识库摘录）
const api = require('../../utils/api');

const CONV_KEY = 'travel_qa_conv';
const AIGC_LABEL = '内容由 AI 生成，仅供参考';

function fmtRefs(refs) {
  return (refs || []).map((r) => ({
    kind: (r.kind || '').toUpperCase(),
    name: r.name || '',
    summary: r.summary || '',
    poi_id: r.poi_id || 0,
  }));
}

function nowText() {
  const d = new Date();
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

Page({
  data: {
    status: null,
    modeText: '正在连接…',
    suggestions: [],
    messages: [],
    input: '',
    sending: false,
    canSend: false,
    convId: '',
    anchor: '',
    historyOpen: false,
    historyLoading: false,
    historyList: [],
    disclaimer: '回答只基于站内资源库与实时天气，门票/开放时间以景区官方公告为准。',
  },

  onLoad() {
    const saved = wx.getStorageSync(CONV_KEY) || '';
    this.setData({ convId: saved });
    this.loadStatus();
  },

  loadStatus() {
    api.qaStatus()
      .then((s) => {
        const modelReady = !!(s && s.configured);
        this.setData({
          status: s,
          modeText: modelReady
            ? 'AI 助手 · ' + (s.model || '')
            : '知识库模式 · 未接入大模型',
        });
      })
      .catch(() => {
        this.setData({ modeText: '问答服务暂不可用' });
      });
    api.qaSuggestions()
      .then((res) => {
        this.setData({ suggestions: ((res && res.items) || []).slice(0, 6) });
      })
      .catch(() => {});
  },

  onInput(e) {
    const v = e.detail.value || '';
    this.setData({ input: v, canSend: !!v.trim() && !this.data.sending });
  },

  askSuggestion(e) {
    const q = e.currentTarget.dataset.q || '';
    if (!q) return;
    this.setData({ input: q, canSend: true });
    this.send();
  },

  send() {
    const text = (this.data.input || '').trim();
    if (!text || this.data.sending) return;
    const messages = this.data.messages.concat([
      { key: 'u' + Date.now(), role: 'user', text: text, time: nowText(), refs: [] },
    ]);
    this.setData({
      messages: messages, input: '', canSend: false, sending: true, anchor: 'msg-bottom',
    });
    api.qaChat({ message: text, conversation_id: this.data.convId || undefined })
      .then((res) => {
        const list = this.data.messages.concat([
          {
            key: 'a' + Date.now(),
            role: 'assistant',
            text: res.answer || '（空回答）',
            time: nowText(),
            refs: fmtRefs(res.refs),
            aigc: !!res.aigc,
            degraded: !!res.degraded,
            error: false,
          },
        ]);
        this.setData({ messages: list, sending: false, anchor: 'msg-bottom' });
        if (res.conversation_id) {
          this.setData({ convId: res.conversation_id });
          wx.setStorageSync(CONV_KEY, res.conversation_id);
        }
        if (res.degraded) {
          wx.showToast({ title: 'AI 暂不可用，以下为知识库摘录', icon: 'none' });
        }
      })
      .catch((err) => {
        const list = this.data.messages.concat([
          {
            key: 'e' + Date.now(),
            role: 'assistant',
            text: (err && err.message) || '问答服务暂时不可用，稍后再试',
            time: nowText(),
            refs: [],
            error: true,
          },
        ]);
        this.setData({ messages: list, sending: false, anchor: 'msg-bottom' });
      });
  },

  newChat() {
    wx.removeStorageSync(CONV_KEY);
    this.setData({ messages: [], convId: '', input: '', canSend: false });
  },

  toggleHistory() {
    if (!api.getToken()) {
      wx.showToast({ title: '登录后可查看历史会话', icon: 'none' });
      return;
    }
    const open = !this.data.historyOpen;
    this.setData({ historyOpen: open });
    if (open) this.loadHistory();
  },

  loadHistory() {
    this.setData({ historyLoading: true });
    api.qaConversations()
      .then((res) => {
        this.setData({
          historyList: (res && res.items) || [],
          historyLoading: false,
        });
      })
      .catch(() => {
        this.setData({ historyLoading: false });
        wx.showToast({ title: '历史会话加载失败', icon: 'none' });
      });
  },

  pickConversation(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    this.setData({ historyOpen: false, messages: [] });
    api.qaConversation(id)
      .then((res) => {
        const list = (res.messages || []).map((m, i) => ({
          key: 'h' + i,
          role: m.role === 'user' ? 'user' : 'assistant',
          text: m.content || '',
          time: '',
          refs: fmtRefs(m.refs),
          aigc: !!m.aigc,
          degraded: !!m.degraded,
        }));
        this.setData({ messages: list, convId: id, anchor: 'msg-bottom' });
        wx.setStorageSync(CONV_KEY, id);
      })
      .catch(() => {
        wx.showToast({ title: '会话打开失败', icon: 'none' });
      });
  },

  openRef(e) {
    const id = e.currentTarget.dataset.poi;
    if (id) wx.navigateTo({ url: '/pages/trip/trip?poi=' + id });
  },

  noop() {},

  closeHistory() {
    this.setData({ historyOpen: false });
  },

  copyLast() {
    const list = this.data.messages;
    if (!list.length) return;
    wx.setClipboardData({ data: list[list.length - 1].text || '' });
  },
});
