#!/usr/bin/env node
/**
 * 小程序静态自检（无微信开发者工具时的兜底校验）
 *
 * 覆盖：
 *  1) 所有 .json 能被 JSON.parse
 *  2) 所有 .js 通过语法检查（vm 编译，不执行副作用）
 *  3) app.json 里注册的页面四件套齐全（.js/.json/.wxml/.wxss 至少要 .js+.wxml）
 *  4) tabBar 的 pagePath 都在 pages 中，且顺序与 pages 不冲突
 *  5) WXML 标签闭合平衡
 *  6) WXML 中绑定的事件处理函数在对应 .js 中都存在
 *  7) WXML 中不出现 Math.* / 可选链（WXML 表达式不支持）
 *  8) 页面里 navigateTo / switchTab / redirectTo 的 url 均已注册
 *
 * 用法：node tools/check.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const failures = [];
const notes = [];

function fail(msg) { failures.push(msg); }
function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    if (name === 'node_modules' || name === '.git' || name === 'tools') continue;
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const files = walk(ROOT);
const rel = (p) => path.relative(ROOT, p).replace(/\\/g, '/');

// ---- 1) JSON ----
for (const f of files.filter((f) => f.endsWith('.json'))) {
  try {
    JSON.parse(fs.readFileSync(f, 'utf8'));
  } catch (e) {
    fail(`JSON 解析失败 ${rel(f)}: ${e.message}`);
  }
}

// ---- 2) JS 语法 ----
for (const f of files.filter((f) => f.endsWith('.js'))) {
  const src = fs.readFileSync(f, 'utf8');
  try {
    new vm.Script(src, { filename: f });
  } catch (e) {
    fail(`JS 语法错误 ${rel(f)}: ${e.message}`);
  }
}

// ---- 3) 页面注册 ----
const appJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'app.json'), 'utf8'));
const pages = appJson.pages || [];
if (!pages.includes('pages/home/home')) fail('app.json 首页 pages/home/home 未注册');
for (const p of pages) {
  for (const ext of ['.js', '.wxml']) {
    const f = path.join(ROOT, p + ext);
    if (!fs.existsSync(f)) fail(`app.json 注册了 ${p} 但缺少 ${p}${ext}`);
  }
}

// ---- 4) tabBar ----
const tabPages = ((appJson.tabBar && appJson.tabBar.list) || []).map((t) => t.pagePath);
for (const t of tabPages) {
  if (!pages.includes(t)) fail(`tabBar 里的 ${t} 未在 pages 中注册`);
}
if (tabPages.length < 2 || tabPages.length > 5) fail('tabBar 项数需为 2~5');
const firstTab = tabPages[0];
if (pages[0] !== firstTab) notes.push(`pages[0]=${pages[0]}，tabBar[0]=${firstTab}（建议一致，避免冷启动落错页）`);

// ---- 5/6/7) WXML ----
const VOID_OK = new Set(['image', 'input', 'slider', 'switch', 'checkbox', 'radio', 'icon', 'progress']);
const BIND_ATTR = /\b(?:bind|catch|capture-bind|capture-catch|mut-bind)[:]?([a-z]+)\s*=\s*"([^"{}]+)"/g;

for (const wxml of files.filter((f) => f.endsWith('.wxml'))) {
  const src = fs.readFileSync(wxml, 'utf8');
  const noComment = src.replace(/<!--[\s\S]*?-->/g, '');

  // 标签闭合
  const stack = [];
  const tagRe = /<(\/?)([a-zA-Z][\w-]*)((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>/g;
  let m;
  while ((m = tagRe.exec(noComment))) {
    const closing = m[1] === '/';
    const name = m[2];
    const selfClosed = m[4] === '/';
    if (closing) {
      if (VOID_OK.has(name)) continue; // 允许 <image ...></image> 这种写法
      const top = stack.pop();
      if (top !== name) {
        fail(`WXML 标签未正确闭合 ${rel(wxml)}: 期望 </${top}>，实际 </${name}>`);
        break;
      }
    } else if (!selfClosed && !VOID_OK.has(name)) {
      stack.push(name);
    }
  }
  if (stack.length) fail(`WXML 有未闭合标签 ${rel(wxml)}: ${stack.join(' > ')}`);

  // 事件处理函数存在性
  const jsPath = wxml.replace(/\.wxml$/, '.js');
  if (fs.existsSync(jsPath)) {
    const js = fs.readFileSync(jsPath, 'utf8');
    let a;
    BIND_ATTR.lastIndex = 0;
    while ((a = BIND_ATTR.exec(noComment))) {
      const handler = a[2].trim();
      if (!handler) continue;
      const re = new RegExp(`(^|[^\\w$])${handler}\\s*\\(`, 'm');
      if (!re.test(js)) fail(`${rel(wxml)} 绑定了 ${handler}，但 ${rel(jsPath)} 中找不到同名方法`);
    }
  }

  // 不支持的表达式
  const bad = noComment.match(/Math\.[a-zA-Z]+/g);
  if (bad) fail(`${rel(wxml)} 使用了 WXML 不支持的 ${[...new Set(bad)].join(', ')}（请在 JS 里预计算）`);
  if (/\?\./.test(noComment.replace(/"[^"]*"/g, ''))) {
    fail(`${rel(wxml)} 使用了可选链 ?.，WXML 表达式不支持`);
  }
}

// ---- 8) 跳转 url 已注册 ----
const NAV_RE = /wx\.(?:navigateTo|redirectTo|switchTab|reLaunch)\(\s*\{\s*url:\s*['"`](\/[^'"`?]+)/g;
for (const js of files.filter((f) => f.endsWith('.js') && !f.endsWith('check.js'))) {
  const src = fs.readFileSync(js, 'utf8');
  let m;
  NAV_RE.lastIndex = 0;
  while ((m = NAV_RE.exec(src))) {
    const url = m[1].replace(/^\//, '');
    if (!pages.includes(url)) fail(`${rel(js)} 跳转到未注册页面 ${url}`);
  }
  // 字符串拼接式（'/pages/x/y?id=' + ...）单独检查前缀
  const CONCAT_RE = /url:\s*['"`](\/pages\/[\w-]+\/[\w-]+)(?:\?[^'"`]*)?['"`]\s*\+/g;
  while ((m = CONCAT_RE.exec(src))) {
    const url = m[1].replace(/^\//, '');
    if (!pages.includes(url)) fail(`${rel(js)} 跳转到未注册页面 ${url}`);
  }
}

// ---- 9) WXSS：花括号平衡 + 变量有定义 + WXML 类名有样式 ----
const appWxss = fs.readFileSync(path.join(ROOT, 'app.wxss'), 'utf8');
const definedVars = new Set([...appWxss.matchAll(/--([a-z0-9-]+)\s*:/g)].map((m) => m[1]));
const wxssFiles = files.filter((f) => f.endsWith('.wxss'));
for (const f of wxssFiles) {
  const s = fs.readFileSync(f, 'utf8');
  const open = (s.match(/{/g) || []).length;
  const close = (s.match(/}/g) || []).length;
  if (open !== close) fail(`${rel(f)} 花括号不平衡（${open} 个 { / ${close} 个 }）`);
  for (const m of s.matchAll(/var\(--([a-z0-9-]+)/g)) {
    if (!definedVars.has(m[1])) fail(`${rel(f)} 使用了未定义的 CSS 变量 --${m[1]}`);
  }
}

// 状态类名（.on / .over / .up …）由各自父类限定，不单独要求规则
const STATE_CLASSES = new Set([
  'on', 'up', 'over', 'slight', 'within', 'ok', 'warn', 'gray', 'orange',
  'active', 'disabled', 'hide', 'loading',
]);
for (const wxml of files.filter((f) => f.endsWith('.wxml'))) {
  const pageWxss = wxml.replace(/\.wxml$/, '.wxss');
  const scope = fs.readFileSync(wxml, 'utf8') && appWxss
    + (fs.existsSync(pageWxss) ? fs.readFileSync(pageWxss, 'utf8') : '');
  const src = fs.readFileSync(wxml, 'utf8');
  const tokens = new Set();
  for (const m of src.matchAll(/class="([^"]*)"/g)) {
    // {{...}} 里只取「三元表达式的结果值」：其后紧跟 : 或前面是 ? 的字面量，
    // 避免把 mode === 'login' 这类比较值误当成类名
    const expanded = m[1].replace(/\{\{([^}]*)\}\}/g, (_, expr) => {
      let out = ' ';
      for (const lit of expr.matchAll(/'([^']*)'/g)) {
        const before = expr.slice(0, lit.index).trimEnd();
        const after = expr.slice(lit.index + lit[0].length).trimStart();
        if (before.endsWith('?') || after.startsWith(':')) out += lit[1] + ' ';
      }
      return out;
    });
    expanded.split(/\s+/).filter(Boolean).forEach((c) => tokens.add(c));
  }
  for (const c of tokens) {
    if (STATE_CLASSES.has(c)) continue;
    const re = new RegExp('\\.' + c.replace(/-/g, '\\-') + '([^a-z0-9-]|$)');
    if (!re.test(scope)) fail(`${rel(wxml)} 用了 class="${c}"，但 app.wxss 与本页 wxss 里都没有对应样式`);
  }
}

// ---- 输出 ----
if (notes.length) {
  console.log('提示：');
  notes.forEach((n) => console.log('  · ' + n));
}
if (failures.length) {
  console.log(`\n失败 ${failures.length} 项：`);
  failures.forEach((f) => console.log('  ✗ ' + f));
  process.exit(1);
}
console.log(`\n全部通过：${files.filter((f) => f.endsWith('.js')).length} 个 js / `
  + `${files.filter((f) => f.endsWith('.json')).length} 个 json / `
  + `${files.filter((f) => f.endsWith('.wxml')).length} 个 wxml，共 ${pages.length} 个页面`);
