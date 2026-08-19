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
from urllib.parse import urljoin, urlparse

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 插件入口特征 (与 loader.detect_format 一致; 本模块自定避免 plugin → utils 逆向导入)
PLUGIN_ENTRY_FILES: tuple[str, ...] = ("manifest.jsonc", "metadata.yaml", "mai_plugin.yaml")

# 重定向状态码集合 (safe_download_bytes 手动逐跳跟随)
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

# U0 Fix-86: safe_extractall 流式解压的读块大小 (累计实际写盘字节用)
_EXTRACT_CHUNK_BYTES = 65536

# 2026-08-19 (M6): RFC6598 CGNAT 段 —— ipaddress.is_private 不覆盖, 须显式拒。
# 对齐 isac/utils/ssrf.py 的 is_private_or_reserved_ip 口径 (此前插件下载与入站媒体
# 下载经 safe_download_bytes 可指向 CGNAT 内网, 与 webhook 投递的 SSRF 口径不一致)。
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_ip_unsafe(ip: Any, allow_loopback: bool) -> bool:
    """IP 是否不安全 (loopback/private/link-local/reserved/multicast/CGNAT/0.0.0.0/8)。

    allow_loopback=True 时整体豁免 loopback —— 127.0.0.0/8 既是 loopback 也属
    private, 必须在 loopback 分支提前豁免, 否则会被 is_private 误拒。
    """
    if ip.is_loopback:
        return not allow_loopback
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return True
    # M6: CGNAT (100.64.0.0/10) 是运营商级内网, is_private 不覆盖, 显式拒。
    if ip in _CGNAT_NETWORK:
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


async def safe_download_bytes(
    url: str,
    *,
    timeout_seconds: float = 30.0,
    max_bytes: int = 50 * 1024 * 1024,
    max_redirects: int = 3,
    allow_loopback: bool = False,
) -> bytes:
    """SSRF 安全的 HTTP 下载 (Fix-39, 供 incoming_media/installer 等统一复用)。

    此前入站媒体与插件安装器只校验**初始** URL 后 ``follow_redirects=True`` ——
    重定向目标不再经任何校验, ``302 → http://169.254.169.254/...`` 即经典 SSRF
    绕过; 且 ``resp.content`` 全量缓冲无上限 (超大响应 OOM DoS)。

    本实现: ``follow_redirects=False`` 手动跟随重定向, **每一跳** (含 Location
    解析出的相对/绝对地址) 重新跑 :func:`is_safe_url`; 流式累计字节, 超过
    ``max_bytes`` 立即中止并 raise ValueError。不安全/超限均 raise ValueError
    (调用方按业务降级)。DNS rebinding TOCTOU 仍受 is_safe_url 固有限制 (模块
    docstring 已述), 但重定向绕过与体积攻击两个确定性漏洞在此关闭。

    Fix-62: is_safe_url 内的 socket.getaddrinfo 是同步阻塞调用, 直接跑会停摆
    事件循环 (入站媒体在主链路逐 segment 串行, 慢 DNS 时放大为全 bot 卡死);
    经 asyncio.to_thread 卸载。
    """
    import asyncio

    import httpx

    current = url
    for _ in range(max_redirects + 1):
        if not await asyncio.to_thread(is_safe_url, current, allow_loopback=allow_loopback):
            raise ValueError(f"URL 不安全 (SSRF 拒绝): {current}")
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            async with client.stream("GET", current) as resp:
                if resp.status_code in _REDIRECT_CODES:
                    location = resp.headers.get("location")
                    if not location:
                        raise ValueError("重定向响应缺 Location 头")
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"下载超过大小上限 ({max_bytes} 字节)")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError(f"超过最大重定向次数 ({max_redirects})")


def safe_extractall(
    zip_ref: zipfile.ZipFile,
    target_dir: Path,
    *,
    max_extracted_bytes: int | None = None,
) -> None:
    """zip slip 防护 + (U0 Fix-86) 解压体积上限。

    zip slip: 逐 member 检查解压后绝对路径是否落在 ``target_dir`` 子树内, 用
    ``Path.resolve()`` 展开 symlink, 比 AstrBot ``os.path.abspath`` 严格。越界
    (如 ``../../../etc/passwd`` 条目) raise ValueError。``target_dir`` 不存在则创建。

    体积上限 (U0 Fix-86): ``max_extracted_bytes`` 非 None 时, 对文件条目流式解压并
    累计**实际写盘字节** (zip 中央目录的 ``file_size`` 元数据可被伪造, 不可信, 以
    实际解压字节为准), 累计超限即 raise ValueError 并清理已解出的半成品文件 (不留
    残留)。防 zip bomb: 小压缩包解压成巨大文件撑爆磁盘/配额。``max_extracted_bytes=None``
    时不检查体积 (向后兼容既有调用)。
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_resolved = target_dir.resolve()
    total_bytes = 0
    written_files: list[Path] = []
    try:
        for member in zip_ref.infolist():
            member_path = (target_dir / member.filename).resolve()
            try:
                member_path.relative_to(target_resolved)
            except ValueError as exc:  # pragma: no cover - 越界路径分支
                raise ValueError(
                    f"zip slip 防护: 解压条目越界 {member.filename} -> {member_path}"
                ) from exc
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            # 先登记再写盘: 超限中止时该 (可能半截) 文件也在清理清单里
            written_files.append(member_path)
            with zip_ref.open(member) as src, member_path.open("wb") as dst:
                while True:
                    chunk = src.read(_EXTRACT_CHUNK_BYTES)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if max_extracted_bytes is not None and total_bytes > max_extracted_bytes:
                        raise ValueError(
                            f"解压体积超限 (累计 > {max_extracted_bytes} 字节), "
                            f"疑似 zip bomb, 中止于条目: {member.filename}"
                        )
                    dst.write(chunk)
    except Exception:
        # U0 Fix-86: 超限/越界中止时清理已解出的半成品文件 (不残留)
        for path in written_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


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
