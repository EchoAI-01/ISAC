# 快速开始（5 分钟跑通）

> 目标：从未接触过 ISAC 的人，5 分钟内在自己机器上把项目跑起来、发出一条消息并收到回复。
> 三条路径任选其一：**Docker 一键**（最快）、**源码运行**（最透明）、**接入真实 LLM**（可对话）。
> 详细配置项见 [SPECIFICATION.md](./SPECIFICATION.md)；完整说明见根目录 [README.md](../README.md)。

---

## 路径 A：Docker 一键（推荐，约 2 分钟）

前提：已安装 Docker 与 docker compose。

```bash
git clone https://github.com/EchoAI-01/ISAC.git
cd ISAC
# 用 .env 覆盖默认 token（可选；默认 change-me-in-prod）
ISAC_API_TOKEN=your-token docker compose up -d
```

启动后：
- 控制面 API + WebUI：`http://127.0.0.1:8765`
- 健康检查：`curl http://127.0.0.1:8765/health`
- 数据持久化在 `isac_data` 卷（Agent 配置 / 记忆 / 审计）

> 首次启动控制面需设置管理密码（T3-backend 首登强制设密码状态机）。Docker 模式默认未配 LLM，WebUI 会引导配置。

---

## 路径 B：源码运行（开发模式，约 3 分钟）

前提：Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/EchoAI-01/ISAC.git
cd ISAC
uv sync --all-extras --dev          # 安装依赖
mkdir -p data
echo '{"config_version": "1.0.0", "debug": false}' > data/config.jsonc   # 最小配置
uv run python -m isac                # 启动（内置 StubProvider，不调外部 LLM）
```

启动后会创建 `default` Agent 并进入就绪等待。验证进程：

```bash
curl http://127.0.0.1:8765/health   # 控制面健康（control 默认开）
```

> StubProvider 是开发态兜底：未配置任何 Provider 时返回引导文案，不消耗真实 Token。真实模型不可达时由 `chat_with_retry` 降级。

---

## 路径 C：接入真实 LLM（可真实对话，约 4 分钟）

在路径 B 基础上编辑 `data/config.jsonc`：

```jsonc
{
    "config_version": "1.0.0",
    "llm": {
        "provider": "openai_compat",
        "model": "gpt-4o-mini",
        "api_key": "sk-...",
        "base_url": "https://api.openai.com/v1"
    }
}
```

重新 `uv run python -m isac`，Agent 即用真实 `OpenAICompatProvider`（httpx + SSE + Tool Call）。

> 密钥安全：生产环境用 `secret:<key>` 前缀 + SecretStore（R5），API key 不落明文配置。开发态可直接填明文。

---

## 接入 IM（QQ / 飞书 / WebChat）

最短接入 QQ（OneBot 反向 WebSocket）：

```bash
uv sync --extra onebot               # 装 OneBot 依赖
```

`data/config.jsonc` 追加：

```jsonc
{
    "channels": { "onebot": { "enabled": true, "host": "127.0.0.1", "port": 8080 } },
    "bot_id": "你的QQ号"
}
```

在 NapCat 配置反向 WebSocket 连到 `ws://127.0.0.1:8080`，即可收发消息。

> 飞书 / QQ 官方 / 企业微信 / WebChat 等平台配置见 [SPECIFICATION.md](./SPECIFICATION.md) 配置规范。

---

## 验证清单（跑通即成功）

- [ ] 进程启动无报错（日志 `ISAC 已启动` 或 `/health` 返回 200）
- [ ] `default` Agent 就绪（`GET /agents` 含 `default`）
- [ ] （路径 C）WebChat 或 IM 发一条消息，收到回复
- [ ] 重启后 session_id 不变（R5 持久化生效）

---

## 常见问题

| 现象 | 原因 / 处置 |
|------|------|
| 启动报 401 / 占位 key | 未配 LLM 或 key 失效，StubProvider 兜底或检查 `llm.api_key` |
| 429 中文提示 | LLM 限流，等待或换模型（T4 错误可诊断） |
| `/health` 无响应 | control 未开或端口被占，检查 `control.enabled` / `control.port` |
| QQ 收不到消息 | NapCat 未连上反向 WS，检查 `onebot.port` 与 NapCat 配置 |

更多排查见 [MAINTENANCE.md](./MAINTENANCE.md) 排查树。
