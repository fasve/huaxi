# 微信云托管 / 任意容器平台用的镜像（构建上下文 = 仓库根目录）
#
#   docker build -t travel-api .
#   docker run -p 8000:8000 --env-file travel-api/.env travel-api
#
# 云托管里：代码目录选仓库根，Dockerfile 路径填 `Dockerfile`，服务端口填 8000。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# 时区与最小的编译/健康检查依赖
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖先单独装，利用镜像层缓存
COPY travel-api/requirements.lock.txt ./requirements.lock.txt
RUN pip install --upgrade pip \
 && pip install -r requirements.lock.txt

# 业务代码 + 静态资源（POI 图 62MB，直接打进镜像；上传的新图在容器重建后会回到镜像内容）
COPY travel-api/app ./app
COPY travel-api/scripts ./scripts
COPY travel-api/static ./static
COPY travel-api/requirements.txt ./requirements.txt

# 非 root 运行
RUN useradd -m -u 10001 appuser \
 && mkdir -p /app/logs /app/static/poi \
 && chown -R appuser:appuser /app
USER appuser

# 云托管会注入 PORT；本地默认 8000
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" || exit 1

# 单 worker 便于云托管按实例扩缩；需要更高并发再调 workers
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
