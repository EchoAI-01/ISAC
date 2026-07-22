#!/usr/bin/env bash
# ISAC Docker 部署脚本 (I2)
#
# 用法:
#   ./scripts/docker_deploy.sh build         # 构建镜像
#   ./scripts/docker_deploy.sh up            # 启动容器
#   ./scripts/docker_deploy.sh down          # 停止容器
#   ./scripts/docker_deploy.sh logs          # 查看日志
#   ./scripts/docker_deploy.sh shell         # 进入容器 shell
#   ./scripts/docker_deploy.sh health        # 健康检查

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

COMMAND="${1:-help}"

case "$COMMAND" in
    build)
        echo "[ISAC] 构建 Docker 镜像..."
        docker build -t isac:latest .
        ;;
    up)
        echo "[ISAC] 启动容器..."
        if [ ! -f .env ]; then
            echo "提示: 未找到 .env 文件, 使用默认配置"
            echo "请创建 .env 包含 ISAC_API_TOKEN ISAC_LLM_API_KEY 等敏感配置"
        fi
        docker compose up -d
        echo "[ISAC] 容器已启动, 控制面: http://127.0.0.1:8765/ui/"
        ;;
    down)
        echo "[ISAC] 停止容器..."
        docker compose down
        ;;
    logs)
        docker compose logs -f --tail 100
        ;;
    shell)
        docker compose exec isac bash
        ;;
    health)
        echo "[ISAC] 健康检查..."
        curl -sf http://127.0.0.1:8765/health && echo " OK" || echo " FAIL"
        ;;
    restart)
        echo "[ISAC] 重启容器..."
        docker compose restart
        ;;
    rebuild)
        echo "[ISAC] 重建镜像并启动..."
        docker compose down
        docker compose build --no-cache
        docker compose up -d
        ;;
    help|*)
        cat <<EOF
ISAC Docker 部署脚本

用法: $0 <command>

命令:
  build     构建 Docker 镜像
  up        启动容器 (后台运行)
  down      停止并删除容器
  logs      查看实时日志 (tail 100)
  shell     进入容器 shell
  health    健康检查 (curl /health)
  restart   重启容器
  rebuild   重建镜像 (no-cache) 并启动

提示:
  - 首次部署前创建 .env 文件配置敏感信息:
    ISAC_API_TOKEN=<你的 API Token>
    ISAC_LLM_API_KEY=<LLM Provider Key>
    ISAC_LLM_PROVIDER=openai_compat
    ISAC_LLM_MODEL=deepseek-chat
  - 控制面 WebUI: http://127.0.0.1:8765/ui/
  - 控制面 API docs: http://127.0.0.1:8765/docs
EOF
        ;;
esac
