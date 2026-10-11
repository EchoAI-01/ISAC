# N3-1 真实 IM 凭据准备清单

> **用途**: T5 真机接入验收 (N3-2 逐平台联调) 的前置凭据准备清单, 交付部署者**在代码联调前**逐项准备。
> 原则: **OneBot 先行** (门槛最低, 无需企业资质); 其余平台按准备难度递增排列。
> 每项均标注: 需要什么 / 去哪申请 / 填到 ISAC 哪个配置键 / 验收时验证什么。
>
> 安全: 凭据只填进 `data/config.jsonc` (不提交 git) 或 `isac secret set` 加密存储 (R5);
> 本清单只记键名, 永不记值。联调完成后建议轮换全部凭据。

## 0. 通用前置 (所有平台共用)

| 项 | 说明 |
|---|---|
| 公网回调地址 | 飞书/QQ 官方/wecom 是 **Webhook 回调模式**, 需要一个能从公网访问 ISAC 宿主的 HTTP 端点 (域名或公网 IP; 家庭网络需内网穿透, 如 frp/cloudflared)。OneBot/Telegram 不需要 (OneBot 反向 WS 由对端连入; Telegram 是 Bot 主动轮询) |
| LLM API Key | 联调对话质量用; `llm.api_key` (或 `isac secret set llm_key` + 配置填 `secret:llm_key`) |

## 1. OneBot / NapCat (QQ) — 推荐先行

**门槛最低**: 一个测试 QQ 号 + 本机跑 NapCat 即可, 无需公网回调。

| 准备项 | 操作 | 填入配置 |
|---|---|---|
| 测试 QQ 号 | 注册一个专用小号 (勿用主号, 封号风险自担) | — |
| NapCat | 本机 Docker/CLI 部署 [NapCat](https://github.com/NapNeko/NapCatQQ), 登录测试号, 开启反向 WebSocket 指向 `ws://<ISAC宿主>:8080/onebot/v11/ws` | — |
| access_token (可选) | NapCat 侧设置任意随机串 | `channels.onebot.access_token` (两侧一致) |
| 监听端口 | — | `channels.onebot.host/port` (默认 127.0.0.1:8080) |

**验收点 (N3-2 第一站)**: 私聊必回 / 群聊 @ 触发 / 图片收发 (R1 入站下载 + 出站 artifact) / 断线重连不重复回复 (M4 去重)。

## 2. 飞书 (Lark) 自建应用

| 准备项 | 操作 | 填入配置 |
|---|---|---|
| 开发者账号 | [open.feishu.cn](https://open.feishu.cn) → 创建**企业自建应用** | `channels.feishu.app_id` / `app_secret` |
| 事件订阅 | 应用后台「事件与回调」→ 订阅方式选 **将事件发送至开发者服务器**, Request URL 填 `http://<公网地址>:9099/feishu/events` | `channels.feishu.webhook_host/port/path` |
| 加密密钥 | 事件订阅页开启加密, 记录 Encrypt Key | `channels.feishu.encrypt_key` (强烈建议开) |
| 校验 Token | 同页 Verification Token | `channels.feishu.verification_token` |
| 机器人能力 | 「添加应用能力」→ 机器人; 权限开 `im:message` / `im:message.group_at_msg` / `im:resource` (图片下载必需) / `im:message:send_as_bot` | — |
| 发布 | 应用版本创建 + 管理员审核通过 (企业内自建应用一般即审即过) | — |

**验收点**: URL 校验挑战通过 / 私聊与群 @ 收发 / 加密模式解密 / **图片入站** (富媒体二波 resources API 鉴权下载) / 图片出站 (im/v1/images 上传)。

## 3. QQ 官方机器人

| 准备项 | 操作 | 填入配置 |
|---|---|---|
| 开发者资质 | [q.qq.com](https://q.qq.com) 注册机器人 (个人沙箱即可起步; 正式上架需企业资质) | — |
| AppID / Secret | 机器人管理页 | `channels.qq_official.app_id` / `secret` |
| 回调地址 | 开发设置 → 配置 `http://<公网地址>:8443/qq_official/callback` (**端口限 80/443/8080/8443**) | `channels.qq_official.webhook_host/port/path` |
| Ed25519 | 平台自动 (Secret 即签名种子, 适配器已按官方文档实现) | — |
| 沙箱 | 起步用沙箱环境 | `channels.qq_official.sandbox: true` |

**验收点**: 握手签名 (op=13) / 三类消息事件 (频道/群/@ 私聊) / 被动回复。

## 4. 企业微信 (wecom)

| 准备项 | 操作 | 填入配置 |
|---|---|---|
| 企业 | [work.weixin.qq.com](https://work.weixin.qq.com) 注册测试企业 (个人可注册, 无需真实公司) | — |
| 自建应用 | 应用管理 → 创建自建应用, 记录 AgentId 与 Secret | `channels.wechat.agent_id` / `secret` |
| 企业 ID | 我的企业页 CorpId | `channels.wechat.corp_id` |
| 回调配置 | 应用的「接收消息」页: URL `http://<公网地址>:9099/wechat/events`, 自定义 Token + EncodingAESKey | `channels.wechat.token` / `encoding_aes_key` (适配器已按 WXBizMsgCrypt 布局实现, Fix-37 修正后可用) |
| 可信 IP | 部分接口需把出口 IP 加入应用可信清单 | — |

**验收点**: 回调 URL 校验 (echostr 解密回显) / AES 消息收发 / 文本回复主动下发。

## 5. Telegram / Discord (可选, 非阻塞)

- Telegram: @BotFather 创建 bot 拿 token → `channels.telegram.bot_token`; 无需公网 (polling); **入站媒体已支持** (阶段3-1), 出站媒体留后续。
- Discord: [discord.com/developers](https://discord.com/developers/applications) 建 Application → Bot token → `channels.discord.bot_token` + 频道 ID 列表 `watch_channel_ids`; **入站附件与出站 multipart 已支持** (富媒体二波)。

## 联调节奏 (N3-2 执行序)

```
OneBot 先行 (门槛最低, 验证主链路) → 飞书 (加密回调 + 富媒体二波)
→ QQ 官方 (Ed25519) → wecom (AES) → (可选) Telegram/Discord
每平台附: 真人连续对话 N 轮无异常栈、无消息丢失的实证 (evidence/ 留档, 验收铁律)。
```

准备过程中的任何疑问 (如内网穿透方案选型) 随时提出; 凭据就绪一项即可联调一项, 无需全部备齐。
