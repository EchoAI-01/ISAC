"""PluginInstaller: 从市场/Git/URL/上传安装插件到 plugins_dir。

对标 AstrBot ``PluginUpdator`` (``astrbot/core/star/updator.py``)。安全: SSRF 校验
(``is_safe_url``) + zip slip 防护 (``safe_extractall``) + 失败回滚 (删半成品目录)。
市场清单: 本地 ``data/plugin_marketplace.jsonc`` + 可配远程 ``marketplace_url``
(httpx 拉取, 远程失败降级为仅本地)。

安装源 ``source`` dict 的 ``type`` ∈ ``market``/``git``/``url``/``upload``:
- market: 从市场清单查条目取 repo_url/download_url。
- git: ``git clone --depth 1`` (git 不可用且有 download_url 时降级 url)。
- url: httpx 下载 zip (SSRF + 超时 + 限 3 跳重定向)。
- upload: 已落地 zip 路径或 ``zip_b64`` (控制面上传端点经 base64 传, 不引 multipart 依赖)。
"""

from __future__ import annotations

import asyncio
import base64
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger
from isac.utils.safe_install import (
    is_safe_url,
    resolve_archive_root_dir,
    safe_download_bytes,
    safe_extractall,
    validate_plugin_archive,
)

try:
    import json5

    _loads = json5.loads
except ImportError:  # pragma: no cover
    import json

    _loads = json.loads

logger = get_logger(__name__)

# Fix-39: 下载体积上限 (此前 resp.content 全量缓冲无上限 → OOM DoS)。
MAX_PLUGIN_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 插件 zip 包上限 100MB
MAX_MARKETPLACE_BYTES = 5 * 1024 * 1024  # 市场清单 JSON 上限 5MB
# N5b 批次C C6: 插件名正则 (防路径穿越: ../evil 等越界写盘) + 解压后体积上限 (防 zip bomb)。
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024  # 解压后总大小上限 500MB


def _validate_plugin_name(name: str, plugins_dir: Path) -> Path:
    """校验插件名合法 (防路径穿越) + 解析后断言在 plugins_dir 子树内。"""
    if not name or not _PLUGIN_NAME_RE.fullmatch(name):
        raise ValueError(
            f"非法插件名 '{name}' (仅允许字母数字下划线短横线, 防路径穿越)"
        )
    target = (plugins_dir / name).resolve()
    if not target.is_relative_to(plugins_dir.resolve()):
        raise ValueError(f"插件目录越界 (不在 plugins_dir 子树内): {name}")
    return target



class PluginInstaller:
    """插件安装器 (T6)。"""

    def __init__(
        self,
        plugins_dir: str | Path,
        marketplace_url: str = "",
        marketplace_local_path: str | Path = "data/plugin_marketplace.jsonc",
        http_timeout: float = 30.0,
    ) -> None:
        self._plugins_dir = Path(plugins_dir)
        self._marketplace_url = marketplace_url
        self._marketplace_local_path = Path(marketplace_local_path)
        self._http_timeout = http_timeout
        self._marketplace_cache: list[dict[str, Any]] | None = None

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    async def install(self, source: dict[str, Any]) -> Path:
        """安装插件, 返回安装后的插件目录路径 (``plugins_dir/<name>``)。

        统一流: 下载/克隆 → 临时解压 → 校验入口 → 移到目标目录 → 失败回滚删目录。
        """
        stype = source.get("type", "")
        name = source.get("name", "")
        if not name:
            raise ValueError("安装源缺少 name")
        # N5b 批次C C6: name 正则校验 + 子树检查 (防 ../evil 路径穿越越界写盘)。
        _validate_plugin_name(name, self._plugins_dir)
        if stype == "upload":
            return await self._install_upload(source, name)
        if stype == "url":
            return await self._install_url(source, name)
        if stype == "git":
            return await self._install_from_git(
                source.get("repo_url", ""), name, source.get("download_url", "")
            )
        if stype == "market":
            return await self._install_from_market(name)
        raise ValueError(f"未知安装源类型: {stype}")

    async def update(self, name: str, source: dict[str, Any] | None = None) -> Path:
        """更新已安装插件: 装到临时目录 → 成功才原子 rename 替换旧目录 (失败保留旧目录)。

        N5b 批次C C6: 此前 = uninstall(删旧) + install(装新), install 失败时旧目录已删
        无回滚 → 插件丢失。改原子交换: 旧目录先重命名备份, 新目录装成功才替换, 失败回滚。
        """
        _validate_plugin_name(name, self._plugins_dir)
        target = (self._plugins_dir / name).resolve()
        backup: Path | None = None
        if target.exists():
            backup = target.with_name(f"{name}.__bak__")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            target.rename(backup)
        try:
            if source is None:
                installed = await self._install_from_market(name)
            else:
                installed = await self.install(source)
            # install 成功后 target 已建; 删备份
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return installed
        except Exception:
            # 回滚: 删半成品新目录, 恢复备份
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if backup is not None and backup.exists():
                backup.rename(target)
            raise

    async def uninstall(self, name: str) -> bool:
        """删除插件目录 ``plugins_dir/<name>``。不存在返回 False。"""
        target = self._plugins_dir / name
        if not target.exists():
            return False
        await asyncio.to_thread(shutil.rmtree, target)
        logger.info("插件目录已删除", name=name, path=str(target))
        return True

    async def load_marketplace(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        """加载市场清单: 本地 jsonc + 可选远程 (远程覆盖同名条目)。

        远程拉取失败时降级为仅本地清单 (记 warning, 不 raise)。结果进程内缓存,
        ``refresh=True`` 强制重拉远程。
        """
        if self._marketplace_cache is not None and not refresh:
            return [dict(e) for e in self._marketplace_cache]
        local: list[dict[str, Any]] = []
        if await asyncio.to_thread(self._marketplace_local_path.exists):
            try:
                text = await asyncio.to_thread(self._marketplace_local_path.read_text, "utf-8")
                data = _loads(text)
                local = list(data.get("plugins", [])) if isinstance(data, dict) else []
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "本地市场清单解析失败",
                    path=str(self._marketplace_local_path),
                    error=str(exc),
                )
        if self._marketplace_url:
            try:
                remote = await self._fetch_remote_marketplace()
                remote_names = {e.get("name") for e in remote}
                merged = [e for e in local if e.get("name") not in remote_names]
                merged.extend(remote)
                local = merged
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "远程市场清单拉取失败, 降级为仅本地",
                    url=self._marketplace_url,
                    error=str(exc),
                )
        self._marketplace_cache = list(local)
        return [dict(e) for e in self._marketplace_cache]

    # ── 各安装源 ─────────────────────────────────────────────

    async def _install_from_market(self, name: str) -> Path:
        entries = await self.load_marketplace()
        entry = next((e for e in entries if e.get("name") == name), None)
        if entry is None:
            raise ValueError(f"市场清单中未找到插件: {name}")
        download_url = entry.get("download_url", "")
        repo_url = entry.get("repo_url", "")
        if download_url:
            return await self._install_url({"url": download_url, "name": name}, name)
        if repo_url:
            return await self._install_from_git(repo_url, name, "")
        raise ValueError(f"市场条目 {name} 缺少 repo_url/download_url")

    async def _install_upload(self, source: dict[str, Any], name: str) -> Path:
        zip_path = source.get("zip_path")
        owning_tmp: Path | None = None
        if zip_path:
            zip_path = Path(zip_path)
        else:
            b64 = source.get("zip_b64")
            if not b64:
                raise ValueError("upload 源缺少 zip_path/zip_b64")
            zip_path, owning_tmp = await self._write_b64_temp(b64)
        try:
            return await self._install_from_zip(zip_path, name)
        finally:
            if owning_tmp is not None:
                await asyncio.to_thread(shutil.rmtree, owning_tmp, ignore_errors=True)

    async def _install_url(self, source: dict[str, Any], name: str) -> Path:
        url = source.get("url", "")
        if not is_safe_url(url):
            raise ValueError(f"下载 URL 不安全 (SSRF 防护拒绝): {url}")
        zip_path, dl_tmp = await self._download_url(url)
        try:
            return await self._install_from_zip(zip_path, name)
        finally:
            await asyncio.to_thread(shutil.rmtree, dl_tmp, ignore_errors=True)

    async def _install_from_git(self, repo_url: str, name: str, download_url: str) -> Path:
        if not is_safe_url(repo_url):
            raise ValueError(f"Git URL 不安全 (SSRF 防护拒绝): {repo_url}")
        target = self._plugins_dir / name
        tmp = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="isac_plugin_git_"))
        try:

            def _clone() -> None:
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(tmp / name)],
                    check=True,
                    capture_output=True,
                    timeout=120,
                )

            try:
                await asyncio.to_thread(_clone)
            except FileNotFoundError as exc:
                # git 未安装: 有 download_url 则降级, 否则 raise 友好提示
                if download_url:
                    logger.warning("git 不可用, 降级 download_url 安装", name=name)
                    return await self._install_url({"url": download_url, "name": name}, name)
                raise RuntimeError(
                    "git 未安装且无 download_url 可降级, 无法从 Git 安装"
                ) from exc
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
                raise RuntimeError(f"git clone 失败: {stderr}") from exc

            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
            await asyncio.to_thread(shutil.move, str(tmp / name), str(target))
            logger.info("插件已从 Git 安装", name=name, path=str(target))
            return target
        finally:
            await asyncio.to_thread(shutil.rmtree, tmp, ignore_errors=True)

    async def _install_from_zip(self, zip_path: Path, name: str) -> Path:
        """安全解压 zip 并移到 ``plugins_dir/<name>``。失败回滚删半成品目录。"""
        target = self._plugins_dir / name
        extract_tmp = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="isac_plugin_ex_"))
        try:
            with zipfile.ZipFile(zip_path) as zf:
                validate_plugin_archive(zf)
                # U0 Fix-86: 接入解压体积上限 (此前 MAX_EXTRACTED_BYTES 全仓零引用) ——
                # safe_extractall 流式累计实际写盘字节, 超限中止并清半成品 (防 zip bomb)。
                safe_extractall(zf, extract_tmp, max_extracted_bytes=MAX_EXTRACTED_BYTES)
            root = resolve_archive_root_dir(extract_tmp)
            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
            await asyncio.to_thread(shutil.move, str(root), str(target))
            logger.info("插件已从压缩包安装", name=name, path=str(target))
            return target
        except Exception:
            # 失败回滚: target 可能已被部分写入 (shutil.move 失败中途)
            await asyncio.to_thread(shutil.rmtree, target, ignore_errors=True)
            raise
        finally:
            await asyncio.to_thread(shutil.rmtree, extract_tmp, ignore_errors=True)

    # ── 辅助 ─────────────────────────────────────────────────

    async def _download_url(self, url: str) -> tuple[Path, Path]:
        """httpx 下载 zip 到临时目录, 返回 (zip_path, owning_tmp_dir)。

        Fix-39: safe_download_bytes 对重定向逐跳复跑 is_safe_url (此前
        follow_redirects=True 不校验重定向目标 → SSRF 绕过), 且流式体积上限
        防超大 zip 包 OOM。
        """
        tmp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="isac_plugin_dl_"))
        zip_path = tmp_dir / "plugin.zip"
        try:
            content = await safe_download_bytes(
                url, timeout_seconds=self._http_timeout, max_bytes=MAX_PLUGIN_DOWNLOAD_BYTES
            )
            await asyncio.to_thread(zip_path.write_bytes, content)
        except Exception:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
            raise
        return zip_path, tmp_dir

    async def _fetch_remote_marketplace(self) -> list[dict[str, Any]]:
        """httpx 拉取远程市场清单 (SSRF 校验, 重定向逐跳复校验 + 体积上限, Fix-39)。"""
        if not is_safe_url(self._marketplace_url):
            raise ValueError(f"市场 URL 不安全 (SSRF): {self._marketplace_url}")
        content = await safe_download_bytes(
            self._marketplace_url, timeout_seconds=self._http_timeout, max_bytes=MAX_MARKETPLACE_BYTES
        )
        data = _loads(content.decode("utf-8"))
        return list(data.get("plugins", [])) if isinstance(data, dict) else []

    async def _write_b64_temp(self, b64: str) -> tuple[Path, Path]:
        """base64 解码 zip 写到临时目录, 返回 (zip_path, owning_tmp_dir)。"""
        tmp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="isac_plugin_up_"))
        zip_path = tmp_dir / "plugin.zip"
        try:
            raw = base64.b64decode(b64)
        except Exception as exc:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
            raise ValueError(f"zip_b64 解码失败: {exc}") from exc
        await asyncio.to_thread(zip_path.write_bytes, raw)
        return zip_path, tmp_dir
