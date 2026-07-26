# ISAC 模块开发指南 (MODULE_GUIDE)

> 本文件把 ISAC 已验证的 **scaffolding (框架先行) 范式**固化为可复制步骤,让开发者按同一套方法给项目新增子系统,而不必每次重新设计接入方式。
> 适用对象: 给 ISAC 新增一个子系统/大节点 (如 L/M/N/O) 的开发者。先读本文件,再读对应节点在 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四的定义。
>
> 配套规范: 目录/导入/命名/测试见 [DEVELOP.md](./DEVELOP.md);架构分层见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 一、为什么框架先行 (scaffolding)

大型能力 (拟人化运行时、多模态、SubAgent) 一次性写完风险高、评审难、容易破坏既有链路。ISAC 采用两段式:

1. **框架阶段 (scaffolding)**: 只落地 **契约 + 类骨架 + 惰性默认关闭接线 + 骨架单测**,保证结构、分层、依赖方向正确,且**主链路零行为变化**。
2. **实现阶段**: 在骨架上逐个子节点填充业务逻辑,每个子节点按强化完成定义验收。

这样做的收益:

- **强可维护**: 契约先冻结,实现者不用再纠结接口;分层与依赖在框架阶段就校验通过。
- **强健壮**: 默认关闭 + 零行为变化,框架合入不会影响正在运行的能力。
- **模块化**: 每个子系统一个目录,单向依赖、无环,可独立测试。
- **可评审**: 框架 PR 小而清晰,实现 PR 聚焦单一子节点。

已按此范式落地的参考: D9 (进度报告)、J1 (用量计量)、J2 (多模态)、J4 (SubAgent)、L1 (ConversationRuntime)。

## 二、六个必备要素

一次合格的 scaffolding 提交,必须同时具备以下六项:

| # | 要素 | 说明 |
|---|------|------|
| 1 | **契约** | dataclass / StrEnum / ABC,字段与专项设计文档严格对齐,不自创 |
| 2 | **类骨架** | 方法签名 + 中文 docstring + 核心控制流;未实现处以 `TODO(节点号)` 标注 |
| 3 | **惰性默认关闭接线** | 通过 `enabled` 开关接入主链路,默认关闭 → 零行为变化 |
| 4 | **骨架单测** | 覆盖契约、状态转移、隔离与上限、默认关闭时零行为变化 |
| 5 | **ruff + mypy 全绿** | `ruff check` 与 `mypy isac/` 通过 |
| 6 | **文档同步** | DEVELOPMENT_PLAN.md 节点定义 + PROGRESS.md 标注 scaffolding |

**注意**: scaffolding **不标 `[x]` 完成**,不计入强化完成定义 (缺业务实现 + 集成/运行验证)。在 PROGRESS/PLAN 中标注为"框架已搭建 (scaffolding),业务实现待续"。

**接线是第二道坎(实现 ≠ 交付)**: scaffolding 之后即便填充了业务逻辑 + 单测,仍只是 `[~]` **实现完成待接线** —— 若不把能力接入生产主链路 (manager / loop / assembly / pipeline / gateway 的真实调用点),它就是"实现了却激活不了"的孤立代码 (ISAC 曾出现 L2-L5/M/N/O1-O3 全部实现却因未接线而无法工作)。**必须再完成主链路接线 + 集成验证才算 `[x]` 交付**。为避免接线待办散落各节点、导致功能各自孤立无法协同,应把它们统一收敛为一个成体系的接线节点组 (见 DEVELOPMENT_PLAN.md §四 **P 主链路接线与激活**),按依赖顺序整体推进,而非各写各的。

## 三、分层与依赖规则

新模块必须遵守 [DEVELOP.md](./DEVELOP.md) 1.2 的单向依赖链:

```
utils → provider → memory → persona → agent → gating → router
      → gateway → channel → commands → plugin → runtime → control → main
```

- **契约放哪层?** 只有某层需要就放该层,不要无脑塞进 `core/`。例: ConversationRuntime 契约只有 runtime 层用,放 `runtime/conversation/models.py`,不污染 core。
- **跨层怎么用?** 用运行时实例注入 (`services` 字典),不用 import 反向依赖。
- **不得成环**: 新模块被上层使用,不得反向 import 上层。

## 四、标准步骤 (以新增一个子系统为例)

### 步骤 0 — 先写节点定义

在 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四加节点条目:**目标 / 验收 / 产出 / 依赖 / 当前**。这是蓝图,先于代码。

### 步骤 1 — 建模块目录与契约文件

新建 `isac/<layer>/<subsystem>/`,先写 `models.py`(纯数据契约,不含行为):

```python
"""<子系统> 数据契约 (<设计文档> §X)。

值对象: 均为纯数据、不含行为;行为在 <subsystem>.py。字段严格对齐专项设计文档,
供实现节点直接填充,不在骨架阶段自创字段。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum   # 注意: 用 StrEnum,不要 str + Enum (ruff UP042)

class SomeState(StrEnum):
    IDLE = "idle"
    ...

@dataclass
class SomeValueObject:
    required_field: str
    optional_field: float | None = None
    metadata: dict = field(default_factory=dict)
```

### 步骤 2 — 写类骨架

在 `<subsystem>.py` 写核心类:方法签名 + 中文 docstring + 能确定的控制流;未实现的业务以 `TODO(节点号)` 标注挂接点,并保持骨架级安全行为 (如恒返回 True、只做状态复位)。

```python
def should_trigger(self, debounce_seconds: float = 0.0) -> bool:
    """判断是否已过静默窗口、可以触发一次处理。

    TODO(L2): 实现真正的 debounce。骨架阶段恒返回 True,不改变现有行为。
    """
    return True
```

### 步骤 3 — 写 registry (若需 per-session/per-agent 实例)

复刻 `gating/system.py` 的 per-session dict 惰性创建 + `manager.py` 的 FIFO 上限,防止长期运行无界增长:

```python
def get(self, agent_id: str, session_id: str) -> Runtime:
    key = (agent_id, session_id)
    runtime = self._runtimes.get(key)
    if runtime is None:
        if len(self._runtimes) >= self._max:
            del self._runtimes[next(iter(self._runtimes))]   # FIFO 淘汰最旧
        runtime = Runtime(agent_id, session_id)
        self._runtimes[key] = runtime
    return runtime
```

### 步骤 4 — 惰性默认关闭接线

在 `assembly.py` 组装时创建实例注入 `services`,在主链路 (如 `manager.handle_message`) 用 `enabled` 开关接入,**默认走原路径**:

```python
# assembly.py
agent_services["conversation_registry"] = ConversationRuntimeRegistry()

# manager.py
conv_registry = instance.services.get("conversation_registry")
if conv_registry is not None and self._conversation_enabled():   # 默认 False
    conv_registry.get(agent_id, session.session_id).register_message(message)
```

`_xxx_enabled()` 读 `global_config` 对应开关,默认 `False`。

### 步骤 5 — 写骨架单测

在 `tests/unit/test_<subsystem>.py` 覆盖:

- 契约默认值与字段
- 状态机转移
- registry 按 (agent_id, session_id) 隔离 + FIFO 上限 + discard
- 队列 enqueue/poll FIFO
- **`enabled=False` 时主链路零行为变化** (最关键的一条)

### 步骤 6 — 门禁

```bash
uv run python -m pytest tests/unit/test_<subsystem>.py -q
uv run ruff check isac/<layer>/<subsystem>/
uv run python -m mypy isac/<layer>/<subsystem>/
```

全绿后,跑一次全量回归确认零行为变化,再提交。

### 步骤 7 — 文档同步

- DEVELOPMENT_PLAN.md: 节点"当前"标注"框架已搭建 (scaffolding, 日期)"。
- PROGRESS.md: 节点总览行 + 待实现能力表更新。
- 若引入新术语,加入 DEVELOPMENT_PLAN.md 术语表。

## 五、完整范例: ConversationRuntime (L1)

L1 是本范式的最新范例,可直接对照源码学习。

| 要素 | 落地位置 |
|------|---------|
| 契约 | `isac/runtime/conversation/models.py` — `ConversationState`/`WaitState`/`ProactiveTask`/`ForcedTurnState` |
| 类骨架 | `isac/runtime/conversation/runtime.py` — `ConversationRuntime`,`should_trigger`/`resolve_wait` 标 `TODO(L2)`,`request_interrupt` 标 `TODO(L4)` |
| registry | `isac/runtime/conversation/registry.py` — `ConversationRuntimeRegistry`,`MAX_RUNTIMES_PER_AGENT=1000` FIFO |
| 队列 | `isac/runtime/conversation/proactive.py` — `ProactiveTaskQueue`,enqueue/poll 标 `TODO(L3)` |
| 导出 | `isac/runtime/conversation/__init__.py` |
| 接线 | `assembly.py` 注入 `conversation_registry`;`manager.py::_dispatch_message` 用 `_conversation_enabled()` 守卫 (默认 False) |
| 挂接锚点 | `agent/tools/social/wait.py` 标 `TODO(L2)`;`agent/loop.py` 读 `interrupt_requested` 处标 `TODO(L4)` |
| 骨架单测 | `tests/unit/test_conversation_runtime.py` — 状态机/registry 隔离与上限/队列 FIFO/`enabled=False` 零行为变化 |
| 文档 | DEVELOPMENT_PLAN.md §四 L1;PROGRESS.md;本指南 |

依赖方向: `runtime/conversation` → core + gateway(Session) + utils;被 `runtime/manager`、`assembly` 使用,无反向依赖、无环。

### 更多 scaffolding 范例 (L/M/N/O 全部 14 子节点)

同一范式已应用到全部 14 个待建子节点,可对照学习不同层的落法:

| 节点 | 模块 | 要点 |
|------|------|------|
| L2-L5 | `runtime/conversation/{debounce,scheduler,recovery}.py` + `models.py` 枚举/InterruptState | 在既有包内扩展骨架文件 |
| M1/M2 | `runtime/mesh/` + `agent/tools/social/{notify,handoff,list,memory_query}_agent.py` | **新增 sibling 契约**避免改 `RoutingDecision`/`InterAgentLink`;工具默认 `deny` → LLM 不可见 |
| N1 | `isac/memory/model/memory_item.py` | 纯契约 + 适配桩,不动既有存储表 |
| N2 | `memory/model/governance.py` + `control/api/routes_memory_admin.py` | 控制面路由 store-None 时不挂载 |
| N3 | `isac/gateway/identity/` | **组合**既有 `UserMapper` 而非改动它 |
| O1/O3 | `runtime/{tenancy,workflow}/` | 默认单租户 passthrough / 引擎 no-op |
| O2 | `plugin/isolation/` | 不接管既有进程内 `loader.py` |
| O4 | `channel/adapters/template/` | 文档化模板,**不自动注册** |
| O5 | `provider/video_gen/` | 实现 ABC,`generate` 抛 `NotImplementedError` |

要点总结: **能新增就不改既有契约** (M1/M2/N3),**默认关闭/不注册/no-op** 保证零行为变化,每个节点用 `TODO(节点)` 标注挂接点。

## 六、检查清单 (合入前自查)

- [ ] 契约字段与专项设计文档一致,无自创字段
- [ ] 未实现处全部以 `TODO(节点号)` 标注,且保持骨架级安全行为
- [ ] 接线由 `enabled` 开关守卫,默认关闭
- [ ] 有一条测试专门验证 `enabled=False` 时主链路零行为变化
- [ ] registry/队列有上限,不会无界增长
- [ ] 依赖单向、无环;契约未无谓塞进 core
- [ ] `ruff check` + `mypy` 全绿;全量回归无新失败
- [ ] DEVELOPMENT_PLAN.md / PROGRESS.md 已标注 scaffolding,**未标 `[x]`**
- [ ] 中文 docstring;复杂逻辑注释"为什么"而非"是什么"

## 七、相关文档

- 节点定义: [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) §四
- 开发规范 (目录/导入/命名/测试/安全): [DEVELOP.md](./DEVELOP.md)
- 架构分层与目录结构: [ARCHITECTURE.md](./ARCHITECTURE.md)
- 数据模型与接口契约: [SPECIFICATION.md](./SPECIFICATION.md)
- 技术路线: [ROADMAP.md](./ROADMAP.md)
- 日志与可观测性: [LOGGING.md](./LOGGING.md)
