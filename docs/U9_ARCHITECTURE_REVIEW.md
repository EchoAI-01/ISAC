# U9 A+ 架构复评报告 (2026-08-18)

> 方法: 与 `isac-deep.md` 同款 —— 只读代码级审查 + 实测 (pytest/ruff/mypy 全量)。
> 范围: U1-U8 改造后的全部架构面。实测基线: **1962 passed + 4 skipped, 0 failed**;
> ruff 全绿; mypy strict 293 源文件全绿; 红线脚本 `scripts/check_redlines.py` 全绿。

## 一、逐模块评级

| 模块 | 评级 | 依据 |
|---|---|---|
| 会话内核 (U1 事件溯源) | **A** | append-only 事件表 + 原子 seq + torn-tail repair + "Model-visible ⟺ Logged" 全接线; 重放/压缩溯源/窗口派生/迁移幂等 24 例专项; 真机跨重启冒烟留档 (scripts/smoke_u1_history_continuity.py) |
| 租户隔离 (U4) | **A** | TenantBoundDB 机制强制 (谓词唯一实现, 调用方不可绕过) + 绕过点审计测试常驻 + 两租户共库集成全绿; tenancy.enabled=false 零行为变化有测试背书 |
| 工具权限 (U5) | **A** | 四段管线 + 单调 DenyGuard (事件表重建不可翻回) + HITL 三路闭环 (同意/拒绝/超时) 集成测试经真实 process_message; decision_reasons drift test 常驻 |
| 门控系统 (U3) | **A-** | GatingProfile/Strategy 四档 + 双语词表 + drift test; 默认零行为回归 236 例背书。扣分: llm-judge 档无真实模型 E2E (judge_fn 注入点有单测, 实模型验证留 N3 真机) |
| 插件隔离 (U6) | **A-** | 信任分级倒转 + rlimits 接线 + 卸载零残留测试; 兼容层降级为**文档化承诺** (宿主内加载+告警), 属已拍板的知情降级 (PLUGIN_COMPATIBILITY §5.4) |
| Provider/模型路由 (U7) | **A-** | 6666 模型能力快照 + CI 每周刷新 + 新鲜度 drift; record_health 生产接线; category 路由经 ModelRouter 数据驱动。扣分: 健康状态仅按 provider 粒度 (无 per-model 退化记忆) |
| 注入仲裁 (U8) | **A** | SessionWriteGate 预约/hold/fail-closed 三态语义 12 例 + AST 审计常驻 (门之外写入当场捕获); 快照回放无凭据跑整条链路; Fix-81/82 根因收编 |
| 装配层 (U2) | **A-** | main.py 2046→82 行 + 三模块 ≤500 + ServiceContainer 核心键类型化 + 红线测试常驻。扣分: 残余 205 处 services 字符串键访问 (棘轮冻结只减不增, 见 B-1) |
| 记忆系统 | **A-** | 向量/图谱/BM25/治理 + episodes 事件投影 + consolidator 后台闭环; 租户列全表覆盖。扣分: 语义关系抽取层仍是架构债 (R4-③, 见 B-2) |
| 控制面/治理门禁 | **A-** | 工具/配置 catalog drift CI + 快照回放 + evidence 规范化起步; setup 首登态 + scope 授权完备。扣分: evidence 留档纪律依赖流程自觉 (脚本已就位) |
| 可观测性 | **A-** | metrics/usage/pricing 全链路计量 + 控制面 /health 聚合; 降级文案错误映射。扣分: 无分布式 trace (单体架构下可接受) |
| 测试工程 | **A** | 1962 测试零失败; 红线/审计/drift 三类常驻门禁; smoke flake 根治 (就绪标记轮询); CI 覆盖率门禁 75% |

**汇总: 无 C 项, B 项 2 (见下), 其余 A-/A+** —— 满足 U9 验收 (无 C、B ≤ 2)。

## 二、B 项清单 (带收敛路径)

**B-1 services 字符串键访问残余 205 处** (装配层)
- 现状: ServiceContainer 已覆盖核心 14 键 (bootstrap/wiring 顶层已迁移 10 处);
  assembly/manager/工具层因 agent_services 为 `{**services, ...}` 派生裸 dict,
  属性访问需先包 ServiceContainer, 涉及面大未批清。
- 收敛路径: 红线棘轮 (≤205 只减不增) 已冻结; 逐文件迁移时把 `agent_services =
  ServiceContainer({**services, ...})` 一并包装; U9 后按域批清, 每批跑全量。

**B-2 语义关系图谱抽取层缺失** (记忆系统, R4-③ 遗留架构债)
- 现状: 写边层 GraphStore.add_edge 通用三元组就绪, mentioned_in 边在写;
  NER/关系抽取层从零未实现 (需 LLM prompt 工程 + 解析容错)。
- 收敛路径: 已文档化 (DEVELOPMENT_PLAN R4); 不阻塞 GA (检索面 episode/profile/
  jargon 三源完备, 关系图是增强项)。

## 三、"定义了未接线"清零结论

- 历史发现项全部接线: MAX_EXTRACTED_BYTES (Fix-86)、record_health (U7)、
  mcp restricted 服务映射 (Fix-87)、ContextEnvelopeBuilder (R2) 等。
- 常驻机制: `tests/unit/test_u9_release_gate.py` UNWIRED_LEDGER 登记册审计
  (定义外/内使用点检查) + 安全模块零 TODO 卫生检查, CI 每跑必过。
- 结论: **零残留** (登记册内 7 符号全部有真实使用点)。

## 四、红线指标 (CI 常驻)

`scripts/check_redlines.py` (catalog-drift job 内执行):

| 指标 | 基线 (冻结) | 当前 |
|---|---|---|
| main.py 行数 | ≤120 | 82 |
| dispatch/wiring/bootstrap 行数 | 各 ≤500 | 481/499/499 |
| services 袋键数 | ≤36 | 36 |
| 硬编码门控词条目数 | ≤27 (只减不增) | 27 |
| services 字符串键访问残余 | ≤205 (棘轮) | 205 |

## 五、GA 门槛对照

| 门槛 | 状态 |
|---|---|
| U0-U8 全部 [x] | ✅ (U0/U1/U4/U5/U6/U3/U7/U8/U2 依序完成) |
| U9 A+ 复评 (无 C、B≤2) | ✅ 本报告 |
| "定义了未接线"零残留 | ✅ 登记册审计常驻 |
| 红线指标 CI 常驻 | ✅ catalog-drift job |
| Minor 批清: smoke flake 根治 | ✅ 就绪标记轮询, 5/5 稳定 |
| Minor 批清: CHANGELOG 补齐 | ✅ 07-26 后全部轮次入库 |
| Minor 批清: 版本号策略定稿 | ✅ SemVer, 1.0.0 为 GA 目标, GA 前不打 tag |
| N2 环境准入 / N3 真机 / N4 前端 | 环境依赖项, 按既有排期 (不属代码侧) |

## 六、复评期间新增常驻资产

- `scripts/check_redlines.py` —— 红线 CI 检查器
- `tests/unit/test_u9_release_gate.py` —— 未接线登记册审计 + 红线 + 安全卫生
- `tests/integration/test_smoke_main_resident.py` —— flake 根治 (重写等待逻辑)
- CHANGELOG.md 补齐 + 版本号策略定稿
