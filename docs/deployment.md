# ISAC Docker 部署指南

ISAC 提供 Docker 多阶段构建镜像 + docker-compose 一键部署。
本指南覆盖容器化部署、配置注入、数据持久化、运维场景。

---

## 目录

1. [镜像构建](#1-镜像构建)
2. [快速部署](#2-快速部署)
3. [环境变量](#3-环境变量)
4. [数据卷与持久化](#4-数据卷与持久化)
5. [生产部署建议](#5-生产部署建议)
6. [运维脚本](#6-运维脚本)
7. [常见问题](#7-常见问题)

---

## 1. 镜像构建

### 1.1 镜像特点

- **多阶段构建**: `builder` 阶段装依赖 + `runtime` 阶段最小镜像 (python:3.12-slim)
- **uv 装依赖**: `uv sync --no-dev --extra onebot` 仅装运行时依赖 (含 OneBot 适配器)
- **数据卷**: `/app/data` 持久化 (Agent 配置 / 记忆 / 审计日志 / Link)
- **健康检查**: `HEALTHCHECK` 调用 `/health` 端点
- **入口**: `CMD ["python", "-m", "isac"]`

### 1.2 构建镜像

```bash
# 用部署脚本
./scripts/docker_deploy.sh build

# 或直接 docker build
docker build -t isac:latest .
```

### 1.3 自定义构建

如需装额外依赖 (如 embed-local 本地嵌入模型):

```dockerfile
# 在 Dockerfile builder 阶段调整
RUN uv sync --no-dev --extra onebot --extra embed-local
```

---

## 2. 快速部署

### 2.1 .env 配置

在项目根目录创建 `.env` 文件 (不提交到 git):

```bash
# 必填
ISAC_API_TOKEN=your-strong-api-token-here

# LLM 配置
ISAC_LLM_PROVIDER=openai_compat
ISAC_LLM_API_KEY=sk-xxx
ISAC_LLM_MODEL=deepseek-chat

# 可选: OneBot 适配器
ISAC_ONEBOT_ENABLED=false
ISAC_ONEBOT_HOST=0.0.0.0
ISAC_ONEBOT_PORT=8080
```

### 2.2 启动

```bash
./scripts/docker_deploy.sh up
```

### 2.3 访问

- 控制面 API: http://127.0.0.1:8765/api/v1/
- API 文档: http://127.0.0.1:8765/docs
- WebUI 管理面板: http://127.0.0.1:8765/ui/

---

## 3. 环境变量

### 3.1 通用

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ISAC_CONTROL_HOST` | `0.0.0.0` (容器内) | 控制面绑定地址; 宿主访问需 0.0.0.0, 但 ISAC 会强制安全检查 |
| `ISAC_CONTROL_PORT` | `8765` | 控制面端口 |
| `ISAC_API_TOKEN` | (必填) | Bearer Token, 控制面认证 + MCP tools/call |
| `ISAC_LLM_PROVIDER` | `stub` | LLM Provider (openai_compat / stub) |
| `ISAC_LLM_API_KEY` | (空) | LLM API Key |
| `ISAC_LLM_MODEL` | (空) | 模型名 |

### 3.2 平台适配器

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ISAC_ONEBOT_ENABLED` | `false` | 启用 OneBot QQ 适配器 |
| `ISAC_ONEBOT_HOST` | `0.0.0.0` | OneBot 反向 WebSocket 监听地址 |
| `ISAC_ONEBOT_PORT` | `8080` | OneBot 监听端口 |
| `ISAC_TELEGRAM_BOT_TOKEN` | (空) | Telegram Bot Token |
| `ISAC_DISCORD_BOT_TOKEN` | (空) | Discord Bot Token |

---

## 4. 数据卷与持久化

### 4.1 isac_data 卷

`docker-compose.yml` 定义 `isac_data:/app/data` 卷, 持久化以下内容:

```
/app/data/
├── config.jsonc          # 全局配置
├── routing.jsonc         # 路由规则
├── links.jsonc           # 互联 Link
├── audit.ndjson          # 审计日志 (NDJSON)
├── agents/               # 各 Agent 配置
│   └── <agent_id>/
│       └── config.jsonc
└── memory/               # 记忆存储
    ├── metadata.db       # MetadataStore (SQLite + FTS5)
    ├── vectors.db        # VectorStore (sqlite-vec)
    └── graph.db          # GraphStore
```

### 4.2 备份与恢复

```bash
# 备份
docker run --rm -v isac_data:/data -v $(pwd):/backup alpine \
    tar czf /backup/isac-data-$(date +%Y%m%d).tar.gz -C /data .

# 恢复
docker run --rm -v isac_data:/data -v $(pwd):/backup alpine \
    tar xzf /backup/isac-data-20260723.tar.gz -C /data
```

### 4.3 插件目录

`./plugins` 目录以只读方式挂载 (`/app/plugins:ro`):
- ISAC 原生插件: `plugins/<name>/manifest.jsonc` + `plugin.py`
- AstrBot 插件: `plugins/<name>/metadata.yaml` + `plugin.py`
- MaiBot 插件: `plugins/<name>/mai_plugin.yaml` + `plugin.py`

---

## 5. 生产部署建议

### 5.1 安全

1. **改 ISAC_API_TOKEN**: 用强随机 token, 不用 `change-me-in-prod`
2. **前置 nginx + HTTPS**: 控制面默认仅 127.0.0.1, 对外通过 nginx 反代 + TLS
3. **限制 IP**: nginx allow/deny 限制访问来源
4. **审计日志监控**: 定期 `jq` 分析 `audit.ndjson` 找异常操作

### 5.2 nginx 反代示例

```nginx
server {
    listen 443 ssl http2;
    server_name isac.example.com;

    ssl_certificate /etc/letsencrypt/live/isac.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/isac.example.com/privkey.pem;

    allow 10.0.0.0/8;
    allow 192.168.0.0/16;
    deny all;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 5.3 资源限制

```yaml
# docker-compose.yml 加 deploy.resources
services:
  isac:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
        reservations:
          memory: 512M
```

---

## 6. 运维脚本

`scripts/docker_deploy.sh` 提供 8 个命令:

| 命令 | 说明 |
|------|------|
| `build` | 构建 Docker 镜像 |
| `up` | 启动容器 (后台) |
| `down` | 停止并删除容器 |
| `logs` | 查看实时日志 (tail 100) |
| `shell` | 进入容器 shell |
| `health` | 健康检查 (curl /health) |
| `restart` | 重启容器 |
| `rebuild` | 重建镜像 (no-cache) 并启动 |

```bash
./scripts/docker_deploy.sh help   # 查看所有命令
```

---

## 7. 常见问题

### Q1: 控制面无法从宿主访问?

A: 检查 `docker-compose.yml` 端口绑定是否 `127.0.0.1:8765:8765`。
   容器内 `ISAC_CONTROL_HOST=0.0.0.0` 让 uvicorn 监听所有接口,
   但 docker 层面限制只能从 127.0.0.1 访问。

### Q2: 容器启动后立即退出?

A: 看日志 `./scripts/docker_deploy.sh logs`, 常见原因:
   - `data/config.jsonc` 配置错误
   - LLM API Key 无效 (StubProvider 兜底, 但其他 provider 失败会退出)
   - 端口冲突 (8080/8765)

### Q3: 数据卷丢失?

A: 不要用 `docker compose down -v`, `-v` 会删除 volumes。
   `docker compose down` 只删容器不删 volume, 安全。

### Q4: 如何升级 ISAC?

```bash
git pull
./scripts/docker_deploy.sh rebuild
# data 卷里的配置与记忆会保留
```

### Q5: 如何在容器内调试?

```bash
./scripts/docker_deploy.sh shell
# 容器内:
python -c "from isac.memory.storage.metadata import MetadataStore; print(...)"
sqlite3 /app/data/memory/metadata.db ".tables"
```
