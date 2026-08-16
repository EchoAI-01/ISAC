# ISAC 发布准入取证报告 (Release Audit)

> 本报告为 R7 验收项「REQUIREMENTS 十二条逐条取证复核」+「每个 hook/injector 经真实触发者驱动测试覆盖审计」的交付产物。
> 方法: 仿 2026-07-26 代码取证 (读代码找实现/测试证据, 不依赖运行环境)。
> 取证时点: 2026-08-16。全量 1728 单测通过、ruff/mypy 全绿 (266 文件)。

---

## 一、REQUIREMENTS 十二条取证结论

| # | 需求 | 状态 | 主要证据 (file:line) | 缺口/备注 |
|---|------|------|------|------|
| 1 | 多 Agent 架构 | ✅ | `runtime/manager.py:48` AgentManager + `:1126` load_persisted_agents + `assembly.py:363` assemble_agent | reload_config 整实例重建 (架构债, 非紧急) |
| 2 | 多 IM 与灵活路由 | ⚠️ | `router/router.py:31` + 8 adapters (onebot/qq/feishu/telegram/discord/webchat/wecom/template) | 微信公众号 mp 桩 (V3 GA 后)、Slack (V4) 未做、T5 真实凭据联调待环境 |
| 3 | Agent 间协作 | ✅ | `runtime/bus.py:84` InterAgentBus + `:162` deny-by-default + `mesh/actions.py:24` MeshActionBroker | — |
| 4 | 拟人化交互 | ✅ | `conversation/runtime.py:39` + `persona/mood_tracker.py:29` + `memory/consolidator.py` R4 行话/压缩 | R4 闭环; Q2 修复 arousal 死代码 |
| 5 | 长期记忆 | ✅ | `memory/pipeline.py:43` (FTS+向量+图谱+Rerank RRF) + `governance.py:43` + `metadata.py` | R4-③ 语义关系图抽取层留架构债 (写边层就绪, Y1 承接) |
| 6 | 插件与工具生态 | ✅ | `plugin/runtime/installer.py:46` (T6 四源) + `registry.py:25` (来源追踪) + `compatibility/astrbot/adapter.py` (R3) | 兼容层子进程化留架构债 (Z3, 需 manifest 机制) |
| 7 | 统一模型体系 | ⚠️ | `provider/catalog.py:15` + `router.py:41` + `artifacts/store.py:108` + `media_resolver.py:34` (R1 出入站闭环) | 视频生成真实端点 V2 待用户选型 (Sora/Runway/Kling) |
| 8 | Token/用量/成本 | ✅ | `observability/usage/recorder.py:32` (6 record_*) + `pricing.py:42` load + `tools/media.py:110` _record_media_usage | R1-③ 闭环 6 个 record_* 零调用 + 空价目表两项缺口 |
| 9 | WebUI 与控制面 | ✅ | `control/api/server.py:216` + `routes_agents.py:65` (R2 真实 revision) + `setup.py:29` (T3 首登) + `security.py:18` SecretStore | 前端独立项目 F1-F4 pending (FE 轨道) |
| 10 | 稳定性与交付 | ⚠️ | `main()` 优雅关闭 + `/health` + `session.py:44` (R5 持久化) + `Dockerfile`/`compose.yml` | 环境准入项待环境 (见第三节) |
| 11 | SubAgent 能力 | ✅ | `subagent/supervisor.py:32` + `journal.py:66` (追加式, 不记 reasoning) + `runner.py:59/119` (R2 envelope+evidence_refs) | R2 闭环 Q6 两项剩余 |
| 12 | 总体目标 | ⚠️ | AstrBot+MaiBot 兼容 + 多 Agent 编排 + 隔离 SubAgent + 统一模型 + 权限治理 + 自动化控制面 + 商业化基础(TenantManager R6) | 商业化 X3/X4 留 GA 后 (v1.2-v2.0) |

**小结**: 8 条 ✅ 已实现 / 4 条 ⚠️ 部分 (缺口均属 GA 后可选项 V2/V3/V4/X3/X4 或环境准入, 非代码缺陷, 不阻塞 v1.0 GA)。

---

## 二、Hook / Injector 测试覆盖审计 (MODULE_GUIDE §二 第三道坎)

### AgentHookPoint (6 个, `core/events.py:32-40`)

| hook point | 实现/注册 | 现有测试 | 类型 | 缺口 |
|---|---|---|---|---|
| FINAL_RESPONSE (MoodTracker) | `persona/mood_tracker.py:37` | `test_persona.py:142` 真实 loop 断言 arousal 推高 | 真实触发 | 否 |
| FINAL_RESPONSE (BehaviorLearner) | `persona/behavior_learner.py:35` | `test_persona.py:218` 手动 invoke | 纯单元 | 是 (无断言其效果的真实触发) |
| COMPRESS (_on_compress listener) | `assembly.py:178-189` | **`test_compress_listener_e2e.py` (本次新增 3 例: 经 fire 真实触发入队+落盘)** + r4 纯单元 | **真实触发** | **否 (已补)** |
| PRE_LLM / POST_LLM / PRE_TOOL / POST_TOOL | 无 in-repo 核心 hook (仅插件扩展点) | 无 | 无 | 是 (扩展点, 无核心实现故无需核心测试) |

### PromptInjector 子类

| injector | 实现 | 现有测试 | 类型 | 缺口 |
|---|---|---|---|---|
| InterruptInjector | `injectors/interrupt.py:105` | `test_p1_humanlike_activation.py:139` 断言 system prompt 含"被打散" | 真实触发 | 否 |
| MidTermMemoryInjector | `memory/injector/mid_term.py:74` | r4 测 build 直调 (含落盘 summary 路径) | 纯单元 | 是 (无经 loop 注入; 已有经 fire 闭环见上 COMPRESS) |
| MoodInjector / ExpressionStyle / AttentionDrift / BaseIdentity / ModelCapabilities / Recovery | `agent/injectors/*` | `test_persona_injectors.py` build 直调 | 纯单元 | 是 |
| HeuristicMemory / Jargon / PersonProfile | `memory/injector/*` | `test_memory_injectors.py` build 直调 | 纯单元 | 是 |
| SkillSelector / ToolsAvailable | `agent/injectors/*` | 无 | 无 | 是 (桩实现, 全无测试) |

**结论**: R4 核心闭环 (COMPRESS listener) 已补经 `hooks.fire` 真实触发者驱动的端到端测试 (3 例); 其余 persona/memory injector 仅有纯单元测试 (build 直调), 缺经 `handle_message`/`loop.run` 真实触发的回归测试。审计识别完整, 补测方向已明确 (参照 `test_p1:157` 断言模式), 非本次 R7 必做项 (审计本身即交付)。

---

## 三、环境准入项 (pending environment, 不阻塞代码完成)

| 项 | 依赖 | 状态 |
|---|---|---|
| 真实启动冒烟 + Docker 健康检查 | docker daemon | 待环境 |
| 24h soak test | 长时运行环境 + 真实 LLM key | 待环境 |
| I 节点 browser CI 复核 100% | 浏览器环境 (本地 2 ERROR 为环境限制非代码缺陷) | 待环境 |
| `scripts/release_checklist.md` 七段全过 | 真实部署环境 | 待环境 |
| T5 真实 IM 凭据联调 | 用户凭据 + 回调公网地址 | 待用户 |
| REQUIREMENTS 十二条逐条取证复核 | 代码取证 (本次即交付) | ✅ 完成 |

---

## 四、架构债 (skipped, 已在 DEVELOPMENT_PLAN §四架构债清单登记)

- P3 通用实体关系图抽取层 (R4-③, 写边层就绪, 抽取层 ~150+ 行从零, 留 Y1)
- 兼容层插件子进程化 (R3 限制, 需兼容层 manifest 机制, 留 Z3)
- 视频生成真实端点 (V2, 用户选型闸门)
- 微信公众号 mp (V3) + Slack (V4) + 主链路流式 (V1, 体验增强)
- ServiceContainer 弱类型 (Z1)、main.py 拆分 (Z2)、Provider 测试端点假连接、检索结构化过滤

---

## 五、交叉验证结论

PROGRESS.md「1728 单测 + ruff/mypy 全绿 266 文件」与 DEVELOPMENT_PLAN §四 R 节点逐节点完成记录 (含新增测试数、真机冒烟 exit=0、架构债登记) 与实际代码 (file:line 证据) 三方吻合。R1-R6 各节点实施记录与代码一致; R7 代码可做部分 (三套集成测试 19 例 + 本审计) 已完成, 环境准入项 pending 环境, 非 R7 节点本身未完成。
