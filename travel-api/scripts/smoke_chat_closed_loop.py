"""对话式闭环自测：chat-edit（无模型走规则）+ parse-guide（粘贴攻略解析）。"""
import json
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


st, trip = call("POST", "/trips/generate", {
    "days": 2, "budget": 900, "mode": "leisure",
    "preferences": [], "party_type": "couple", "seed": 11,
})
assert st == 200, trip
tid = trip["trip_id"]
print("trip", tid)

st, res = call("POST", f"/trips/{tid}/chat-edit", {"text": "把最后一段改成骑行"})
print("chat-edit(骑行):", st, json.dumps(res, ensure_ascii=False)[:220] if isinstance(res, dict) else res)

st, res2 = call("POST", f"/trips/{tid}/chat-edit", {"text": "第 1 天 8 点出发"})
print("chat-edit(出发时间):", st, json.dumps(res2, ensure_ascii=False)[:160] if isinstance(res2, dict) else res2)

st, detail = call("GET", f"/trips/{tid}")
rides = [it.get("transport_mode") for d in detail["days_plan"] for it in d["items"]]
print("transport_mode 写入:", rides)
print("day1 首个开始时间:", detail["days_plan"][0]["items"][0]["start_time"])

guide = (
    "第一天上午去青岩古镇，中午吃青岩状元蹄，下午逛花溪公园，晚上回酒店。"
    "第二天去十里河滩国家城市湿地公园，午餐吃花溪飞碗牛肉粉，下午去天河潭。"
)
st, parsed = call("POST", "/trips/parse-guide", {
    "text": guide, "start_date": "2026-12-01", "mode": "leisure", "budget": 800,
})
print("parse-guide:", st)
if isinstance(parsed, dict):
    print("  匹配点位:", parsed.get("matched_count"), "| 创建行程:", parsed.get("trip_id"))
    tp = parsed.get("trip") or {}
    for d in (tp.get("days_plan") or [])[:2]:
        print("   day", d.get("day_index"), [i.get("name") for i in d.get("items", [])])
else:
    print("  ", parsed)
