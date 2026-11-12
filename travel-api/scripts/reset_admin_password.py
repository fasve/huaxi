"""重置管理后台密码（忘记密码 / 首次改密用）。

用法：
    python scripts/reset_admin_password.py 新密码 [用户名]
不传用户名时默认重置 `admin`。会同时吊销该账号的全部登录会话。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import SessionLocal
from app.models import AdminUser
from app.services.admin_auth import (
    hash_password, init_admin_auth, revoke_all_sessions,
)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python scripts/reset_admin_password.py 新密码 [用户名]")
        raise SystemExit(1)
    new_password = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else settings.ADMIN_BOOTSTRAP_USERNAME
    if len(new_password) < 6:
        print("密码至少 6 位")
        raise SystemExit(1)

    init_admin_auth()  # 确保表与默认账号存在
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.username == username).first()
        if admin is None:
            print(f"账号不存在：{username}")
            raise SystemExit(1)
        admin.password_hash = hash_password(new_password)
        admin.status = 1
        db.commit()
        revoke_all_sessions(db, admin.id)
        print(f"已重置账号 {username} 的密码，全部会话已失效，请用新密码重新登录。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
