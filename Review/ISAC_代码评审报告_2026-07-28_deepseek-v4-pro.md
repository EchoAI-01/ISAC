# ISAC 代码评审报告

**评审日期：** 2026-07-28
**评审模型：** deepseek-v4-pro
**分支：** dev
**评审范围：** 当前工作区已修改和新增的全部文件

---

## 变更概览

| 类型 | 文件 | 行数 |
|------|------|------|
| 修改 | `isac/provider/video_gen/openai_compat.py` | +7 |
| 修改 | `isac/runtime/conversation/__init__.py` | +12 |
| 修改 | `isac/runtime/manager.py` | +16 |
| 修改 | `tests/unit/test_main_multimodal_registration.py` | +47 |
| 新增 | `isac/channel/adapters/feishu/adapter.py` | ~370 |
| 新增 | `isac/channel/adapters/qq_official/adapter.py` | ~404 |
| 新增 | `isac/channel/adapters/wechat/adapter.py` | ~82 |
| 新增 | 4 个 `__init__.py` (骨架) | ~4 |
| 删除 | `data/.gitkeep`, `data/config.sample.jsonc` | -248 |
| 新增 | 4 个 scaffolding 单测文件 | ~336 |

---

## 1. Correctness（正确性）

**`isac/runtime/conversation/__init__.py`**
导入的 4 个新 Producer 类（`CompositeTaskProducer`, `DateReminderProducer`, `MemoryAssociationProducer`, `TopicFollowupProducer`）均在 `producer.py` 中确有定义，`__all__` 导出列表完整无误。

**`isac/runtime/manager.py`**
`memory_consolidator` 的生命周期管理在 4 个位置（`start_agent`、`stop_agent`、`_stop_instance_services`、`reload_agent`）与 `proactive_scheduler` 完全对齐，采用相同的 `services.get()` + `is not None` 守卫模式，逻辑正确。

**`FeishuAdapter`**
AES-256-CBC 解密流程（SHA256(encrypt_key) → key, base64decode → IV + ciphertext, PKCS7 unpad）与飞书官方文档一致。tenant_access_token 缓存 + 提前 60s 刷新正确。URL 校验挑战（challenge 回传）符合飞书规范。

**Required: `QQOfficialAdapter.send()` 中 `code` 的 falsy 处理不一致**

```python
# QQOfficialAdapter.send() line 337 — 当前写法:
code = int(resp.get("code", 0) or 0)
```

这与 `FeishuAdapter` 和同文件中 `_handle_callback` 的处理方式不一致：

```python
# FeishuAdapter.send() line 289-290 — 正确的写法:
code_raw = resp.get("code")
code = -1 if code_raw is None else int(code_raw)

# QQOfficialAdapter._handle_callback() line 156-157 — 同文件内的一致写法:
op_raw = payload.get("op", -1)
op = -1 if op_raw is None else int(op_raw)
```

问题在于：当 API 响应中 `code` 字段显式为 `None` 时，`None or 0 = 0`，会错误地将失败判定为成功。且 `resp.get("code", 0)` 在字段缺失时默认返回 0，也与飞书适配器的 fail-closed 策略（缺失 → code=-1）不一致。应统一为 `code_raw = resp.get("code"); code = -1 if code_raw is None else int(code_raw)` 模式。

**`QQOfficialAdapter.send()` 中 line 315 body 过滤逻辑有副作用**

```python
body = {k: v for k, v in body.items() if v is not None and v != ""}
```

这会过滤掉空字符串 `""`，但 `"msg_id": ""` 在 body 构建时（line 311）已经被设为空字符串，导致 `msg_id` 字段被丢弃。如果将来 QQ API 要求 `msg_id` 字段即使为空也必须存在，这会导致问题。目前（主动推送场景）不传 `msg_id` 是正确行为，但如果元数据中的 `qq_official_source` 标识为被动回复场景（需要 `msg_id`），`message.reply_to` 非空时 `msg_id` 不会被过滤掉，逻辑是正确的。但需要注意 `event_id` 字段（line 312）被设为空字符串后也被过滤掉了——这是预期行为，因为当前不支持 event_id。

**测试文件**
所有 scaffolding 测试的 stub/fake 对象正确地模拟了依赖，断言覆盖了零行为变化、默认关闭、异常降级等关键路径。

---

## 2. Readability & Simplicity（可读性与简洁性）

**`FeishuAdapter` 和 `QQOfficialAdapter`**
代码结构清晰，方法职责单一。中文注释与项目整体风格一致。

**Nit: 飞书适配器中 `code=0` falsy 陷阱注释重复了两次**
`send()` line 287-290 和 `_get_tenant_access_token()` line 314-317 两处注释几乎完全相同，建议提取为模块级常量或私有静态方法消除重复。

**Nit: `QQOfficialAdapter.start()` 中的内部函数 `_callback`**
line 107-108 仅作为 `self._handle_callback` 的薄包装，可以直接传递绑定方法 `self._handle_callback` 给 `add_api_route`（FastAPI 支持异步绑定方法）。

---

## 3. Architecture（架构）

**`manager.py` 的 consolidator 生命周期管理**
遵循了与 `proactive_scheduler` 完全一致的模式，没有引入新的抽象或耦合。这是正确的做法——第二个同类实例出现时复制模式，第三个出现时再提取抽象。

**Optional: 两个 Webhook 适配器存在大量结构重复**
包括：
- `start()`/`stop()` 的 uvicorn Server 管理（~25 行重复）
- token 缓存逻辑（`_get_xxx_token` 方法结构相同，仅字段名不同）
- `_http_post()` 方法几乎完全一致
- `set_http_transport()` 注入模式

如果后续增加更多 webhook 类适配器（如 Telegram、Discord），建议提取 `WebhookPlatformAdapter(PlatformAdapter)` 基类，将 uvicorn 生命周期、token 缓存、HTTP 客户端统一管理。当前两个实例尚可接受，但第三个出现时就是明确的抽象信号。

**模块位置恰当**
`isac/channel/adapters/` 下的各平台适配器隔离在独立子包中，`__init__.py` 仅含一行 docstring（骨架阶段），符合项目分层约定。

---

## 4. Security（安全）

**`FeishuAdapter` — 整体安全设计良好**
- 明文模式下未配置 `verification_token` 时拒绝事件（fail-closed），注释明确说明了理由（防止 fail-open 注入）
- 加密模式由 `encrypt_key` 证明身份，解密失败直接丢弃
- 所有事件处理异常被吞掉并返回 `200 {}`，防止飞书重试放大攻击
- 密钥（`app_secret`, `encrypt_key`）不直接出现在日志中

**Consider: 当 `encrypt_key` 已配置时，明文事件跳过 `_verify_token`**

```python
# _handle_event() line 155-156
if not self._encrypt_key:
    self._verify_token(payload)
```

飞书生产环境不会混合加密/明文模式，但如果攻击者能直接向 webhook 端口发明文请求（绕过飞书基础设施），加密模式下的 webhook 将无认证接受该事件。建议在 `_decode_payload` 返回非加密 body 且 `encrypt_key` 已配置时，仍然执行 token 校验（或直接拒绝），做到双重保险。

**`QQOfficialAdapter` — 安全设计良好**
- Ed25519 验签覆盖所有 op=0 事件（`_verify_signature`）
- 未配置 `secret` 时拒绝所有事件（fail-closed）
- 验签失败返回 `{"opcode": 12}` 而非 401（不暴露过多信息给调用方）

**日志安全**
`FeishuAdapter.start()` 中 `app_id=self._app_id` 被记录到 info 日志。`app_id` 本身是公开标识符（出现在飞书应用页面 URL 中），不算敏感信息，可以接受。

---

## 5. Performance（性能）

**Consider: 每次 HTTP 请求创建新的 `httpx.AsyncClient`**

```python
# 两个适配器的 _http_post 都这样写:
async with httpx.AsyncClient(transport=transport) as client:
    resp = await client.post(...)
```

在低流量场景下这没有问题。如果预期高频消息收发（如群聊机器人），建议在适配器实例中维护一个复用的 `httpx.AsyncClient`（在 `start()` 创建、`stop()` 关闭），利用连接池减少 TCP 握手开销。

**token 缓存策略正确**
提前 60s 刷新窗口 + `time.monotonic()` 计时（不受系统时间调整影响），避免了每次 send 都换取 token。

---

## 6. 其他发现

**删除 `data/config.sample.jsonc`**
这个 248 行的示例配置文件被删除但没有替代。如果这是有意的（例如改为代码内生成或文档中说明），请确认相关文档已更新，否则新贡献者会缺少配置参考。

**`data/.gitkeep` 删除**
如果 `data/` 目录还有其他文件存在则无问题；如果 `data/` 变为空目录，git 不会追踪空目录，未来可能丢失这个目录结构。

---

## 审查结论

| 维度 | 评估 |
|------|------|
| Correctness | **需修改 1 处** — `QQOfficialAdapter.send()` code 判定 |
| Readability | 良好，有 2 个 nit |
| Architecture | 模式一致，有 1 个 optional 重构建议 |
| Security | 良好，有 1 个 consider 加固建议 |
| Performance | 可接受，有 1 个 consider 优化建议 |

**结论：Request Changes** — `QQOfficialAdapter.send()` 中 `code` 的 falsy 处理不一致问题需要修复。其余均为 Optional/Consider/Nit 级别，不阻塞合并。

---

*本报告由 deepseek-v4-pro 自动生成，评审基于 2026-07-28 dev 分支工作区变更。*
