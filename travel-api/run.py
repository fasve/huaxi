"""PyCharm / 命令行通用启动入口。

直接右键运行本文件即可，无需配置模块名或工作目录：
    python run.py

若需热重载（改代码自动重启）：
    set RELOAD=1 && python run.py      (Windows cmd)
    $env:RELOAD=1; python run.py       (PowerShell)
"""
import os
import sys
from pathlib import Path

# 关键：无论从哪个目录启动，都把 travel-api 根目录放到 sys.path 首位，
# 保证 `import app.xxx` 与 .env 读取都正确。
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

if __name__ == "__main__":
    import socket

    import uvicorn

    from app.config import settings

    def _lan_ips() -> list[str]:
        """本机可被手机访问的局域网 IPv4（真机调试/预览要用）。"""
        ips: set[str] = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except OSError:
            pass
        try:
            # 不真正发包，只让系统选一个出口网卡
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ips.add(s.getsockname()[0])
        except OSError:
            pass

        def rank(ip: str) -> int:
            # 家用/办公 Wi-Fi 一般是 192.168；其次 10.x；链路本地（169.254）直接丢掉
            if ip.startswith("192.168."):
                return 0
            if ip.startswith("10."):
                return 1
            return 2

        usable = [ip for ip in ips if not ip.startswith(("127.", "169.254."))]
        return sorted(usable, key=rank)

    host = settings.API_HOST or "0.0.0.0"
    reload_flag = os.getenv("RELOAD", "").lower() in ("1", "true", "yes")

    print(f"[travel-api] 启动中 → http://127.0.0.1:{settings.API_PORT}  (docs: /docs)")
    # 监听 0.0.0.0 时手机/真机调试必须用局域网 IP，这里直接把可用地址打出来
    if host in ("0.0.0.0", "::"):
        for ip in _lan_ips():
            print(f"[travel-api] 手机/真机调试 → http://{ip}:{settings.API_PORT}/api/v1")
    print(f"[travel-api] 监听地址: {host}:{settings.API_PORT}")
    print(f"[travel-api] 数据库: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=settings.API_PORT,
        reload=reload_flag,
        reload_dirs=[str(BASE_DIR)] if reload_flag else None,
    )
