"""插件安装安全原语: SSRF 校验 + zip slip 防护 + 压缩包入口校验。

供 PluginInstaller (``isac/plugin/runtime/installer.py``) 复用。全仓此前无 SSRF
校验与安全解压生产代码 (T6 Phase 1 取证)。本模块在 utils 层, 不 import ``plugin.*``
(避免 plugin → utils 逆向导入破坏导入单向无环); 插件入口特征列表自定, 与
``loader.PluginLoader.detect_format`` 对齐。

已知限制: ``is_safe_url`` 不防 DNS 重绑定 (TOCTOU —— 校验时与连接时 DNS 可能变),
真正防护需 httpx transport 钩子做连接时校验, 超出 T6 范围, 记架构债。
"""

from __future__ import annotations

import ipaddress
import socket
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 插件入口特征 (与 loader.detect_format 一致; 本模块自定避免 plugin → utils 逆向导入)
PLUGIN_ENTRY_FILES: tuple[str, ...] = ("manifest.jsonc", "metadata.yaml", "mai_plugin.yaml")


def _is_ip_unsafe(ip: Any, allow_loopback: bool) -> bool:
    """IP 是否不安全 (loopback/private/link-local/reserved/multicast/0.0.0.0/8)。

    allow_loopback=True 时整体豁免 loopback —— 127.0.0.0/8 既是 loopback 也属
    private, 必须在 loopback 分支提前豁免, 否则会被 is_private 误拒。
    """
    if ip.is_loopback:
        return not allow_loopback
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return True
    # 0.0.0.0/8 ("当前网络") 统一拒
    return ip.version == 4 and str(ip).startswith("0.")


def is_safe_url(url: str, *, allow_loopback: bool = False) -> bool:
    """SSRF 防护: scheme 限 http/https, 解析 hostname 得到的 IP 不得是 private /
    loopback / link-local / reserved / multicast / 0.0.0.0/8。

    ``allow_loopback=True`` 时放行 127.0.0.1/localhost (本地市场源场景)。
    解析失败、scheme 非法、无 hostname 一律拒绝。
    """
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname == "localhost":
        return allow_loopback
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_ip_unsafe(ip, allow_loopback):
            return False
    return True


def safe_extractall(zip_ref: zipfile.ZipFile, target_dir: Path) -> None:
    """zip slip 防护: 逐 member 检查解压后绝对路径是否落在 ``target_dir`` 子树内。

    用 ``Path.resolve()`` 展开 symlink, 比 AstrBot ``os.path.abspath`` 严格。
    越界 (如 ``../../../etc/passwd`` 条目) raise ValueError。``target_dir`` 不存在则创建。
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_resolved = target_dir.resolve()
    for member in zip_ref.infolist():
        member_path = (target_dir / member.filename).resolve()
        try:
            member_path.relative_to(target_resolved)
        except ValueError as exc:  # pragma: no cover - 越界路径分支
            raise ValueError(
                f"zip slip 防护: 解压条目越界 {member.filename} -> {member_path}"
            ) from exc
        zip_ref.extract(member, target_dir)


def resolve_archive_root_dir(extract_dir: Path) -> Path:
    """压缩包内可能有顶层目录 (如 ``plugin-x.zip`` 解出 ``plugin-x/``)。

    若 ``extract_dir`` 下仅一个非隐藏子目录, 返回该子目录; 否则返回 ``extract_dir``
    本身 (多个文件直接平铺在根)。对标 AstrBot ``_resolve_archive_root_dir``。
    """
    extract_dir = Path(extract_dir)
    children = [c for c in extract_dir.iterdir() if not c.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def validate_plugin_archive(zip_ref: zipfile.ZipFile) -> None:
    """解压前校验: 压缩包内须含插件入口特征之一 (manifest.jsonc / metadata.yaml /
    mai_plugin.yaml), 在任意层级。无任一入口 → raise ValueError, 避免安装非插件包。
    """
    names = zip_ref.namelist()
    for name in names:
        basename = name.rsplit("/", 1)[-1]
        if basename in PLUGIN_ENTRY_FILES:
            return
    raise ValueError(
        f"压缩包不是合法插件: 未找到入口特征 {PLUGIN_ENTRY_FILES} 之一"
    )
