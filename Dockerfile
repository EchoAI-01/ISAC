# ISAC Dockerfile (I2)
#
# 多阶段构建: builder 装依赖 + runtime 最小镜像
# 默认暴露控制面端口 8765, 数据卷 /app/data

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

# 安装 uv 用于快速装依赖
RUN pip install --no-cache-dir uv

WORKDIR /app

# 先复制依赖文件利用 Docker 层缓存
COPY pyproject.toml ./
COPY README.md ./

# 安装运行时依赖 (不含 dev 组)
RUN uv sync --no-dev --extra onebot

# 复制源码
COPY isac/ ./isac/
COPY scripts/ ./scripts/
COPY data/ ./data/

# ── runtime 阶段 ──────────────────────────────────────────

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# 安装运行时必要系统包 (sqlite 驱动 + ca-certificates 用于 HTTPS)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 复制 venv 与源码
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# 数据卷: data/ 目录持久化 (Agent 配置 / 记忆 / 审计日志)
VOLUME ["/app/data"]

# 控制面端口 (默认仅 127.0.0.1, 容器内需 0.0.0.0 才能被宿主访问)
# 注意: 实际绑定地址由 data/config.jsonc 决定, 容器部署需 host=0.0.0.0
EXPOSE 8765

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')" || exit 1

# 启动入口: 用 uv run 启动主程序
CMD ["python", "-m", "isac"]
