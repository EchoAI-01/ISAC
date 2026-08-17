# u8-gate-and-governance

- **日期**: 2026-08-18
- **验收项**: DEVELOPMENT_PLAN §四 U8 注入仲裁门 + 治理门禁
- **结论**: PASS

## 证据清单

- `snapshot_replay_output.txt`: mock IM 事件流快照回放 (无真实凭据跑整条 bot 链路)
  2 例通过 —— 5 条脱敏事件经 EventBus → Router → Session/Gating → AgentManager →
  LLM → Channel 回放, 4 条回复按 scripted 顺序对齐 (群聊短反应被门控 WAIT),
  SessionWriteGate 在场时反应式链路零干扰、无残留租约。
- 门语义单测 12 例 (tests/unit/test_u8_write_gate.py): 预约/提交/取消、单写者仲裁、
  hold 窗口超时 fail-closed、未登记来源拒绝、AST 审计 (门之外 forced_turn 赋值/
  transition_to 调用当场捕获)、catalog drift 一致性。
- catalog 生成: 29 工具 + 21 顶层配置键入库 (data/catalogs/), CI catalog-drift job
  --check 生效 (.github/workflows/ci.yml)。

## 复现方式

```
.venv/bin/python -m pytest tests/unit/test_u8_write_gate.py tests/integration/test_u8_snapshot_replay.py -q
.venv/bin/python scripts/gen_tool_catalog.py --check
.venv/bin/python scripts/gen_config_catalog.py --check
```
