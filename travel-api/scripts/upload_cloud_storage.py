"""把 travel-api/static/poi 下的图片批量上传到微信云开发存储（供小程序 <image> 用 cloud:// 直接显示）。

为什么需要：小程序 <image> 受 downloadFile 合法域名限制，而云托管默认域名被微信禁止登记；
云开发存储的 `cloud://` fileID 不受该限制，可覆盖体验版/正式版。

用法：
    set WX_APPID=wx...
    set WX_SECRET=...
    python scripts/upload_cloud_storage.py --env prod-d7gnymd9e909581e8 --dry-run
    python scripts/upload_cloud_storage.py --env prod-d7gnymd9e909581e8

输出：
    scripts/cloud_images.json   { "static/poi/xxx.jpg": "cloud://env.bucket/static/poi/xxx.jpg", ... }
    并打印可用的 cloud 前缀（env.bucket）。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
STATIC = BASE / "static" / "poi"
OUT = BASE / "scripts" / "cloud_images.json"

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
UPLOAD_URL = "https://api.weixin.qq.com/tcb/uploadfile"
TIMEOUT = 40


def get_token(appid: str, secret: str) -> str:
    r = requests.get(
        TOKEN_URL,
        params={"grant_type": "client_credential", "appid": appid, "secret": secret},
        timeout=TIMEOUT,
    )
    data = r.json()
    if "access_token" not in data:
        raise SystemExit(f"获取 access_token 失败：{data}")
    return data["access_token"]


def collect_files() -> list[tuple[Path, str]]:
    """返回 [(本地路径, 云存储相对路径)]，保持 static/poi 目录结构。"""
    out: list[tuple[Path, str]] = []
    for f in sorted(STATIC.rglob("*")):
        if not f.is_file() or f.name == ".gitkeep":
            continue
        rel = f.relative_to(BASE).as_posix()          # static/poi/xxx.jpg
        out.append((f, rel))
    return out


def upload_one(token: str, env: str, local: Path, cloud_path: str) -> str:
    """换取上传凭证 → 传到 COS → 返回 file_id。"""
    r = requests.post(
        UPLOAD_URL,
        params={"access_token": token},
        json={"env": env, "path": cloud_path},
        timeout=TIMEOUT,
    )
    info = r.json()
    if info.get("errcode") not in (0, None):
        raise RuntimeError(f"{cloud_path} 取凭证失败：{info}")

    ctype = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
    files = {
        "key": (None, cloud_path),
        "Signature": (None, info["authorization"]),
        "x-cos-security-token": (None, info["token"]),
        "x-cos-meta-fileid": (None, info["cos_file_id"]),
        "file": (local.name, local.read_bytes(), ctype),
    }
    up = requests.post(info["url"], files=files, timeout=120)
    if up.status_code not in (200, 204):
        raise RuntimeError(f"{cloud_path} 上传失败：HTTP {up.status_code} {up.text[:200]}")
    return info["file_id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, help="云开发/云托管环境 ID")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只传前 N 个，调试用")
    args = ap.parse_args()

    appid = os.getenv("WX_APPID", "").strip()
    secret = os.getenv("WX_SECRET", "").strip()
    if not appid or not secret:
        raise SystemExit("请先设置 WX_APPID / WX_SECRET 环境变量")

    files = collect_files()
    if args.limit:
        files = files[: args.limit]
    total_bytes = sum(f.stat().st_size for f, _ in files)
    print(f"待上传 {len(files)} 个文件 / {total_bytes / 1048576:.1f} MB → env {args.env}")
    if args.dry_run:
        for f, p in files[:5]:
            print("  ", p)
        print("dry-run，未实际上传")
        return

    token = get_token(appid, secret)
    mapping: dict[str, str] = {}
    if OUT.exists():
        mapping = json.loads(OUT.read_text(encoding="utf-8"))
    ok = fail = 0
    for i, (local, cloud_path) in enumerate(files, 1):
        try:
            fid = upload_one(token, args.env, local, cloud_path)
            mapping[cloud_path] = fid
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  [{i}/{len(files)}] 失败 {cloud_path}: {exc}")
        if i % 10 == 0 or i == len(files):
            OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  进度 {i}/{len(files)}  成功 {ok} 失败 {fail}")
        time.sleep(0.05)  # 轻微限速，避免触发频控

    OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    prefixes = {v.split("/")[2] for v in mapping.values() if v.startswith("cloud://")}
    print(f"\n完成：成功 {ok}，失败 {fail}")
    print("cloud 前缀:", ", ".join(sorted(prefixes)) or "（无）")
    print("映射文件:", OUT)


if __name__ == "__main__":
    main()
