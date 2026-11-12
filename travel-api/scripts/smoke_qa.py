"""问答模块自测：状态 / 推荐问题 / 降级问答 / 知识库 CRUD 生效 / 判官 / 会话读取。

无 LLM Key 时预期走「知识库直出」：degraded=true、aigc=false，仍带引用卡片。
"""
import json
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(B + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


ok = 0
fail = []


def check(cond, label):
    global ok
    if cond:
        ok += 1
        print(f"  ✔ {label}")
    else:
        fail.append(label)
        print(f"  ✘ {label}")


st, status = call("GET", "/qa/status")
check(st == 200 and status.get("enabled") is True, "状态：开关已启用")
check(status.get("configured") is False, "状态：未配置 Key（走降级）")

st, sug = call("GET", "/qa/suggestions")
check(st == 200 and isinstance(sug.get("items"), list) and sug["items"], "推荐问题非空")

st, ans = call("POST", "/qa/chat/sync", {"message": "青岩古镇门票多少，需要预约吗？"})
check(st == 200, "问答接口 200")
check(bool(ans.get("answer")), "有回答正文")
check(ans.get("degraded") is True, "标记 degraded（知识库直出）")
check(ans.get("aigc") is False, "标记 aigc=false（非 AI 生成）")
check(isinstance(ans.get("refs"), list) and ans["refs"], f"引用卡片 {len(ans.get('refs') or [])} 条")
conv_id = ans.get("conversation_id")
check(bool(conv_id), "返回会话 id")

# 管理端：新增知识条目 → 再问一次，应被检索到
st, login = call("POST", "/admin/login", {"username": "admin", "password": "admin123"})
check(st == 200 and login.get("token"), "管理端登录")
token = login.get("token")
st, created = call("POST", "/admin/qa/knowledge", {
    "title": "夜游自测：青岩打烊时间",
    "content": "花溪公园夜间 21:30 闭园，青岩古镇商铺 22:00 陆续打烊。",
    "category": "tip", "tags": ["夜游", "自测"], "enabled": True,
}, token=token)
check(st in (200, 201), f"新增知识条目 {st}")
kid = (created or {}).get("id") if isinstance(created, dict) else None

st, ans2 = call("POST", "/qa/chat/sync", {"message": "青岩商铺打烊时间是几点？"})
refs = ans2.get("refs") or []
names = " ".join(str(r.get("name", "")) for r in refs)
check("夜游自测" in names or any(r.get("kind") == "faq" for r in refs),
      "新知识被检索命中（引用里出现 faq/夜游自测）")

st, conv = call("GET", f"/qa/conversations/{conv_id}")
check(st == 200 and isinstance(conv, dict) and conv.get("messages"), "会话消息可读取")

# 判官
st, trip = call("POST", "/trips/generate", {
    "days": 1, "budget": 500, "mode": "leisure",
    "preferences": [], "party_type": "couple", "seed": 3,
})
if st == 200:
    st, judge = call("POST", "/qa/judge", {"trip_id": trip["trip_id"]})
    check(st == 200 and isinstance(judge, dict), "行程判官 200")
else:
    check(False, "生成行程用于判官")

if kid:
    st, _ = call("DELETE", f"/admin/qa/knowledge/{kid}", token=token)
    check(st in (200, 204), "删除自测知识条目")

print(f"\n通过 {ok} 项，失败 {len(fail)} 项")
if fail:
    print("失败项:", fail)
    raise SystemExit(1)
