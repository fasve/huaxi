#!/usr/bin/env node
/**
 * 在微信开发者工具里跑一遍六个主页面，逐页截图（真机渲染，不是 HTML 模拟）。
 *
 * 前置：
 *   1. 微信开发者工具已打开本项目（travel-miniapp），且「设置 → 安全设置 → 服务端口」为开；
 *   2. 后端 travel-api 已在 http://127.0.0.1:8000 运行（行程页需要真实数据）；
 *   3. 本机装过 miniprogram-automator（不在小程序依赖里，避免被打包）：
 *        npm i miniprogram-automator --prefix %TEMP%/wxauto
 *      Windows 下可直接把下面 require 的路径改成该目录。
 *      automation 端口启动：cli auto --project <项目路径> --auto-port 9420
 *
 * 用法：node tools/devtools-shots.js [输出目录]
 */
const fs = require('fs');
const path = require('path');

// 允许通过环境变量指向临时安装的 automator
const AUTOMATOR = process.env.MINIPROGRAM_AUTOMATOR_PATH || 'miniprogram-automator';
const automator = require(AUTOMATOR);

const OUT = process.argv[2] || path.join(__dirname, '..', '..', 'design', 'devtools');
const API = 'http://127.0.0.1:8000/api/v1';
const WS = process.env.AUTOMATOR_WS || 'ws://127.0.0.1:9420';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function shot(mp, name) {
  const file = path.join(OUT, name + '.png');
  await mp.screenshot({ path: file });
  return file;
}

async function generate(payload) {
  const res = await fetch(API + '/trips/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('生成行程失败 ' + res.status);
  return res.json();
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const mp = await automator.connect({ wsEndpoint: WS });
  const report = { shots: [] };

  // 1 首页
  await mp.switchTab('/pages/home/home');
  await wait(4000);
  report.shots.push(await shot(mp, '01-home'));

  // 2 发现
  await mp.switchTab('/pages/explore/explore');
  await wait(3000);
  report.shots.push(await shot(mp, '02-explore'));

  // 3 定制
  await mp.switchTab('/pages/request/request');
  await wait(2500);
  report.shots.push(await shot(mp, '03-request'));

  // 4 对比（带条件自动出结果）
  await mp.navigateTo('/pages/compare/compare?days=2&budget=1200&party=couple&prefs=');
  await wait(4500);
  report.shots.push(await shot(mp, '04-compare'));
  await mp.navigateBack();
  await wait(1200);

  // 5 我的
  await mp.switchTab('/pages/mine/mine');
  await wait(2000);
  report.shots.push(await shot(mp, '05-mine'));

  // 6 两天普通行程：顶部 / 时间轴 / 操作区 / 地图展开
  const trip = await generate({
    days: 2, budget: 1500, mode: 'checkin',
    preferences: ['photospot'], party_type: 'couple', seed: 33,
  });
  await mp.navigateTo('/pages/trip/trip?id=' + trip.trip_id);
  await wait(4000);
  let page = await mp.currentPage();
  report.shots.push(await shot(mp, '06-trip'));

  await mp.callWxMethod('pageScrollTo', { scrollTop: 620, duration: 0 });
  await wait(1200);
  report.shots.push(await shot(mp, '07-trip-timeline'));

  await mp.callWxMethod('pageScrollTo', { scrollTop: 1400, duration: 0 });
  await wait(1200);
  report.shots.push(await shot(mp, '08-trip-days'));

  await mp.callWxMethod('pageScrollTo', { scrollTop: 0, duration: 0 });
  await wait(600);
  const mapHead = await page.$('.map-head');
  if (mapHead) await mapHead.tap();
  await wait(2000);
  report.shots.push(await shot(mp, '09-trip-map'));

  // 7 游学行程：展开逐站讲解
  const study = await generate({
    days: 1, budget: 800, mode: 'leisure', preferences: [], party_type: 'couple',
    seed: 21, preset_route_code: 'gzu_campus_study_tour', visit_date: '2026-11-11',
  });
  await mp.navigateTo('/pages/trip/trip?id=' + study.trip_id);
  await wait(4000);
  page = await mp.currentPage();
  const data = await page.data();
  const idx = data.trip.days_plan[0].items.findIndex((i) => i.has_narration);
  if (idx >= 0) {
    await page.setData({ ['trip.days_plan[0].items[' + idx + '].narr_open']: true });
    await wait(800);
    await mp.callWxMethod('pageScrollTo', { scrollTop: 1000, duration: 0 });
    await wait(800);
    report.shots.push(await shot(mp, '10-trip-narration'));
  }

  fs.writeFileSync(path.join(OUT, 'shot-report.json'), JSON.stringify(report, null, 2), 'utf8');
  console.log('截图完成：' + OUT);
  await mp.disconnect();
})().catch((e) => {
  console.error('失败：', e && (e.stack || e));
  process.exit(1);
});
