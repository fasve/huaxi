"""行程编辑接口自测：生成 → 加/移/复制/替换/删 → 判官 → 优化 → 跨天重排。"""
import json
import urllib.error
import urllib.request

B = "http://127.0.0.1:8000/api/v1"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


status, trip = call("POST", "/trips/generate", {
    "days": 2, "budget": 900, "mode": "leisure",
    "preferences": [], "party_type": "couple", "seed": 7,
})
assert status == 200, trip
tid = trip["trip_id"]
print("生成:", tid, "天数", len(trip["days_plan"]))
for d in trip["days_plan"]:
    print("  day", d["day_index"], [it["name"] for it in d["items"]])

# 取一个候选点位作为「待计划」加入
status, pois = call("GET", "/pois?category=food&page_size=3")
add_poi = pois["items"][0]
print("\n待计划加入:", add_poi["name"])
print("  add:", call("POST", f"/trips/{tid}/items/add", {"poi_id": add_poi["id"], "day": 1})[0])

status, detail = call("GET", f"/trips/{tid}")
day1 = detail["days_plan"][0]
item = day1["items"][-1]
print("  加完 day1 点位数:", len(day1["items"]))

print("  move:", call("POST", f"/trips/{tid}/items/{item['id']}/move",
                       {"target_day": 2, "target_index": 0})[0])
print("  copy:", call("POST", f"/trips/{tid}/items/{item['id']}/copy", {"target_day": 2})[0])

status, detail = call("GET", f"/trips/{tid}")
day2_items = detail["days_plan"][1]["items"]
print("  day2 点位数:", len(day2_items))

status, diag = call("GET", f"/trips/{tid}/diagnose")
print("  判官:", status, list(diag)[:6] if isinstance(diag, dict) else str(diag)[:120])

status, opt = call("POST", f"/trips/{tid}/optimize")
print("  优化:", status, (opt.get("saved_km") if isinstance(opt, dict) else str(opt)[:100]))

status, red = call("POST", f"/trips/{tid}/redistribute")
print("  跨天重排:", status, (red.get("days") if isinstance(red, dict) else str(red)[:100]))

status, detail = call("GET", f"/trips/{tid}")
print("\n最终：")
for d in detail["days_plan"]:
    print("  day", d["day_index"], "items", len(d["items"]), "cost", d["day_cost"])

status, out = call("DELETE", f"/trips/{tid}/items/{detail['days_plan'][0]['items'][0]['id']}")
print("\n删除一项:", status)
status, detail2 = call("GET", f"/trips/{tid}")
print("删除后 day1 点位数:", len(detail2["days_plan"][0]["items"]))
