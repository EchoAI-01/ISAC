# ISAC 发布准入检查清单

> 发布前必须逐项确认; 任一未达标阻塞发版。本清单对应 `docs/DEVELOPMENT_PLAN.md` K8-2 验收线。

## 一、CI 全绿 (必须)

- [ ] `.github/workflows/ci.yml` 的 `check` job 通过 (ruff + mypy + pytest --cov-fail-under=75)
- [ ] `build` job 通过 (wheel/sdist 构建 + 安装 smoke `python -c "import isac"`)
- [ ] `docker` job 通过 (镜像构建 + 容器启动 + `/health` 30s curl 探活)
- [ ] `browser` job 通过 (Playwright 安装 chromium + `tests/browser/` 黄金路径)

## 二、本地全量验证 (必须)

```bash
uv run python -m pytest --ignore=tests/browser -q          # 全量测试通过 (基线 1093+)
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

## 四、版本号一致 (必须)

- [ ] `pyproject.toml` version 与文档描述一致
- [ ] `isac/__init__.py:__version__` 与 pyproject.toml 一致
- [ ] Docker 镜像 tag 与版本号一致 (若推送 registry)

## 五、发布标签 (建议)

- [ ] `git tag v<version>` 在 dev 合并到 main 后打
- [ ] GitHub Release notes 引用 CHANGELOG

## 六、回滚预案 (建议)

- [ ] 确认上一版本 tag 可回滚 (main 分支历史完整)
- [ ] 数据迁移脚本 (若有) 已备份 `data/` 目录

## 七、发布后

- [ ] 监控告警规则 (`data/alerts.jsonc`) 已加载
- [ ] 第一个 24h 无 Critical 告警
- [ ] 用户反馈渠道畅通
