#!/usr/bin/env bash
# 生产库初始化：建库建号 → 导入 dump → 幂等补预设路线
#
# 用法（在服务器上、首次部署时执行一次）：
#   sudo DB_PASS='改成强密码' bash deploy/scripts/bootstrap_db.sh /root/travel.sql
#
# 前置：MySQL 8 已安装；/root/travel.sql 是从开发机导出的数据（含 308 条 POI 与图片 meta）
set -euo pipefail

DUMP="${1:?用法: bootstrap_db.sh <dump.sql>}"
DB_NAME="${DB_NAME:-travel}"
DB_USER="${DB_USER:-travel_app}"
DB_PASS="${DB_PASS:?请用环境变量 DB_PASS 传入强密码}"
APP_DIR="${APP_DIR:-/srv/travel/travel-api}"

echo "==> 建库与账号"
mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
ALTER USER '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "==> 导入数据 ${DUMP}"
mysql -uroot "${DB_NAME}" < "${DUMP}"

echo "==> 校验关键表行数"
mysql -uroot "${DB_NAME}" -e "
SELECT 'poi' AS t, COUNT(*) AS n FROM poi
UNION ALL SELECT 'trip_mode_config', COUNT(*) FROM trip_mode_config
UNION ALL SELECT 'preset_route', COUNT(*) FROM preset_route
UNION ALL SELECT 'qa_knowledge', COUNT(*) FROM qa_knowledge;
"

echo "==> 幂等补预设路线（已有则跳过）"
cd "${APP_DIR}"
if [ -x .venv/bin/python ]; then
  .venv/bin/python scripts/seed_preset_routes.py || true
else
  echo "（跳过：.venv 还没建，先跑 deploy/scripts/deploy.sh 再执行本段）"
fi

echo "完成。记得把 .env 的 DB_USER/DB_PASSWORD 改成 ${DB_USER}，不要用 root。"
