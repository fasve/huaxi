#!/usr/bin/env bash
# 服务器端发布：装依赖 → 建表/迁移 → 校验 → 重启 → 健康检查
#
# 用法（服务器上，代码已通过 upload.ps1 同步到 /srv/travel 后执行）：
#   bash /srv/travel/deploy/scripts/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/travel/travel-api}"
SERVICE="${SERVICE:-travel-api}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"

cd "${APP_DIR}"
mkdir -p logs static/poi

echo "==> Python 版本"
python3.11 --version

echo "==> 虚拟环境与依赖"
if [ ! -d .venv ]; then
  python3.11 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip wheel >/dev/null
.venv/bin/pip install -r requirements.lock.txt

echo "==> 建表 / 补列（幂等，不动数据）"
.venv/bin/python - <<'PY'
from app.database import Base, engine
from app import models  # noqa: F401  触发所有模型注册
Base.metadata.create_all(bind=engine)
print("tables ok")
PY

echo "==> 预设路线 / 价格档 / 问答表（启动时也会幂等执行，这里先跑一遍便于排查）"
.venv/bin/python scripts/seed_preset_routes.py || true

echo "==> 重启服务"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE}" >/dev/null 2>&1 || true
sudo systemctl restart "${SERVICE}"
sleep 4

echo "==> 健康检查 ${BASE_URL}/health"
for i in 1 2 3 4 5; do
  if curl -fsS --max-time 5 "${BASE_URL}/health"; then
    echo
    echo "OK"
    break
  fi
  echo "第 ${i} 次未就绪，2s 后重试…"
  sleep 2
  [ "${i}" = "5" ] && { echo "启动失败，查看：sudo journalctl -u ${SERVICE} -n 80 --no-pager"; exit 1; }
done

echo "==> 数据自检"
curl -fsS --max-time 8 "${BASE_URL}/pois?page_size=1" | head -c 200; echo
echo "发布完成。"
