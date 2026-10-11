# ISAC 发布准入检查清单

> 发布前必须逐项确认; 任一未达标阻塞发版。本清单对应 `docs/DEVELOPMENT_PLAN.md` K8-2 验收线。
>
> **CD 机器化 (2026-10-11)**: `.github/workflows/release.yml` 把本清单的机器可验部分
> 自动化 —— 打 `v*` tag 触发 (§四版本一致强校验 + §一全量复验 + 构建推送 + GitHub
> Release); `workflow_dispatch` 演练模式随时全链路空跑 (GA 前不打 tag, 用演练保持
> 链路可发布)。本清单剩余人工部分: §三文档同步、§六回滚预案、§七发布后观察。

## 一、CI 全绿 (必须)

- [ ] `.github/workflows/ci.yml` 的 `check` job 通过 (ruff + mypy + pytest --cov-fail-under=75)
- [ ] `build` job 通过 (wheel/sdist 构建 + 安装 smoke `python -c "import isac"`)
- [ ] `docker` job 通过 (镜像构建 + 容器启动 + `/health` 30s curl 探活)
- [ ] `browser` job 通过 (Playwright 安装 chromium + `tests/browser/` 黄金路径)
- [ ] 以上四项在 `release.yml` 的 `verify` job 中全量复验 (发布不信任历史, tag 指向的快照必须当场全绿)

## 二、本地全量验证 (必须)

```bash
uv run python -m pytest --ignore=tests/browser -q          # 全量测试通过 (基线 2346+, 2026-10-10)
uv run ruff check .                                          # Lint 全绿
uv run mypy isac/                                            # 类型全绿
uv run python -m isac                                        # 冒烟: RESIDENT_AFTER_3S + SIGTERM EXIT_CODE=0
```

## 三、文档同步 (必须)

- [ ] `docs/PROGRESS.md` 节点总览表 + 待实现能力表更新
- [ ] `docs/DEVELOPMENT_PLAN.md` 各节点"当前"段 + `[x]` 标记
- [ ] `docs/ROADMAP.md` 阶段状态更新
- [ ] `README.md` / `AGENTS.md` 能力描述与版本号一致
- [ ] `CHANGELOG.md` (若存在) 记录本次发版变更

## 四、版本号一致 (必须; 按 CHANGELOG「版本号策略」执行)

- [ ] 发版时 `pyproject.toml` / `isac/__init__.py:__version__` / `docs/api/openapi.json` /
      Docker 镜像 tag 四处统一 (当前 0.0.1a1 = Alpha-0.0.1, 未达 MVP; 三处同源由
      test_api_contract 契约测试锁定)
      —— **已由 `release.yml` verify job 强校验**: tag 与两处版本不一致即 `::error` 拒绝发布
      (演练模式只告警不阻塞, 正式 tag 机器拒绝)
- [ ] Docker 镜像 tag 与版本号一致 —— **已自动化**: `release.yml` 用 PEP 440 版本串
      直出镜像 tag (`0.0.1a1`); 稳定版 (无 `aN/bN/rcN` 后缀) 额外打 `latest`,
      prerelease 不占 latest

## 五、发布标签 (建议)

- [ ] `git tag v<version>` 在 dev 合并到 main 后打 (Alpha 期如 `v0.0.1a1`) ——
      **推送 tag 即触发 `release.yml`**: verify 全量复验 → wheel/sdist 构建 + 安装
      smoke → 多平台镜像推 `ghcr.io/echoai-01/isac` (推送前本地探活 + 推送后按
      digest 拉回探活) → GitHub Release (CHANGELOG 段落 + 产物附件, `aN/bN/rcN`
      后缀自动标 prerelease 不占 latest)
- [ ] GitHub Release notes 引用 CHANGELOG —— **已自动化**: release job 从
      `CHANGELOG.md` 提取 `## [X.Y.Z]` 段落 (缺失回退 Unreleased 并标注)

## 六、回滚预案 (建议)

- [ ] 确认上一版本 tag 可回滚 (main 分支历史完整)
- [ ] 数据迁移脚本 (若有) 已备份 `data/` 目录

## 七、发布后

- [ ] 监控告警规则 (`data/alerts.jsonc`) 已加载
- [ ] 第一个 24h 无 Critical 告警
- [ ] 用户反馈渠道畅通
