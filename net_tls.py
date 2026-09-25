"""HTTPS 证书工具：解决 `CERTIFICATE_VERIFY_FAILED / unable to get local issuer certificate`。

背景（macOS 上最常踩）：Python 的标准库 `ssl` 默认只加载**证书文件本身**（例如
Homebrew 的 `/opt/homebrew/etc/openssl@3/cert.pem`、Linux 的 `/etc/ssl/certs/ca-certificates.crt`），
**不会加载它旁边的 `certs/` 哈希目录**。很多系统（尤其 Homebrew、conda、部分精简镜像）
的 pem 里只有根证书，缺中间证书，于是标准库校验链时会报
`unable to get local issuer certificate`；而浏览器/curl 会去查哈希目录，所以同一个站点
在浏览器里一切正常。

打包成 exe/app 后更脆弱：冻结环境里 `ssl.get_default_verify_paths()` 可能指向一个
并不存在的路径，于是"源码能跑、打包后必挂"。

这里的做法是**按可靠性依次尝试候选 CA 源**，谁能建立可用连接就用谁，并且**优先使用
`cafile + capath` 组合**（补上标准库不加载哈希目录这个坑）：

1. `certifi` 的 cacert.pem —— 与系统环境无关，打包后也稳定可靠（首选）；
2. 系统默认 `cafile` / `capath` 组合；
3. 几个常见的系统 CA 路径（Debian/Ubuntu、RHEL、macOS）。

不提供"跳过证书校验"的降级选项：宁可失败，也不静默地把请求暴露给中间人。
"""

import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

__all__ = [
    "certifi_cafile",
    "ssl_candidates",
    "ssl_context",
    "urlopen",
    "download_bytes",
    "insecure_ssl_allowed",
]

# CA 来源：("cafile" | "capath", 路径)
CaSource = Tuple[str, str]


def certifi_cafile() -> Optional[str]:
    """certifi 自带的 CA bundle 路径；不可用时返回 None（certifi 是硬依赖，但保持容错）。"""
    try:
        import certifi  # type: ignore

        path = Path(certifi.where())
        return str(path) if path.exists() else None
    except Exception:
        return None


def ssl_candidates() -> List[CaSource]:
    """按可靠性排序的 CA 候选，去重后返回。"""
    out: List[CaSource] = []

    cafile = certifi_cafile()
    if cafile:
        out.append(("cafile", cafile))

    try:
        defaults = ssl.get_default_verify_paths()
        if defaults.cafile:
            out.append(("cafile", defaults.cafile))
        if defaults.capath:
            out.append(("capath", defaults.capath))
    except Exception:
        pass

    for kind, path in (
        ("cafile", "/etc/ssl/certs/ca-certificates.crt"),  # Debian / Ubuntu
        ("capath", "/etc/ssl/certs"),
        ("cafile", "/etc/pki/tls/certs/ca-bundle.crt"),    # RHEL / CentOS
        ("cafile", "/opt/homebrew/etc/openssl@3/cert.pem"),  # macOS (Apple Silicon)
        ("cafile", "/usr/local/etc/openssl@3/cert.pem"),     # macOS (Intel)
        ("cafile", "/etc/ssl/cert.pem"),                     # macOS / LibreSSL
        ("capath", "/opt/homebrew/etc/openssl@3/certs"),
    ):
        out.append((kind, path))

    seen = set()
    uniq: List[CaSource] = []
    for kind, path in out:
        if not path or (kind, path) in seen:
            continue
        if not Path(path).exists():
            continue
        seen.add((kind, path))
        uniq.append((kind, path))
    return uniq


def _build_context(sources: Iterable[CaSource]) -> Optional[ssl.SSLContext]:
    """用给定 CA 源建一个校验型 SSLContext；一个都没加载成功则返回 None。

    关键点是 `cafile` 与 `capath` **一起传给同一个 context**（load_verify_locations
    可以同时接收两者），这样哈希目录里的中间证书也能被找到。
    """
    cafiles = [p for k, p in sources if k == "cafile"]
    capaths = [p for k, p in sources if k == "capath"]
    if not cafiles and not capaths:
        return None
    ctx = ssl.create_default_context()
    loaded = False
    if cafiles or capaths:
        try:
            ctx.load_verify_locations(
                cafile=cafiles[0] if cafiles else None,
                capath=capaths[0] if capaths else None,
            )
            loaded = True
        except Exception:
            loaded = False
    if not loaded:
        return None
    return ctx


_cached_context: Optional[ssl.SSLContext] = None
_context_ready = False
_warned = False


def _log(msg: str) -> None:
    print(f"[TLS] {msg}", file=sys.stderr)


def ssl_context() -> Optional[ssl.SSLContext]:
    """返回一个能通过校验的 SSLContext（进程内缓存）。

    候选分两轮：先把 `cafile` + `capath` 组合起来（解决缺中间证书），再逐个单独尝试。
    全部失败时返回 None，让调用方用标准库默认行为（并如实报错）。
    """
    global _cached_context, _context_ready, _warned

    if _context_ready:
        return _cached_context
    _context_ready = True

    candidates = ssl_candidates()
    if not candidates:
        if not _warned:
            _warned = True
            _log("未找到任何可用的 CA 证书文件，将使用标准库默认设置。")
        return None

    # 第一轮：cafile 与 capath 组合（macOS/Homebrew 上最常见的缺中间证书场景）。
    best_cafile = candidates[0]
    best_capath = next((c for c in candidates if c[0] == "capath"), None)
    combined = [best_cafile] + ([best_capath] if best_capath else [])
    ctx = _build_context(combined)
    if ctx is not None:
        _cached_context = ctx
        return ctx

    # 第二轮：逐个单独尝试。
    for source in candidates:
        ctx = _build_context([source])
        if ctx is not None:
            _cached_context = ctx
            return ctx

    if not _warned:
        _warned = True
        _log("CA 证书加载失败，将使用标准库默认设置。")
    return None


def insecure_ssl_allowed() -> bool:
    """是否允许跳过证书校验（默认否；仅供测试/自签环境，不用于修复线上问题）。"""
    import os

    return os.environ.get("BTAB_INSECURE_SSL", "").strip() in ("1", "true", "yes")


def _open(req, timeout: float):
    """依次用各 CA 候选发起请求，返回第一个成功的响应。

    失败时抛**最后一个**异常（而不是第一个），因为组合上下文失败后，
    单独 cafile 的尝试往往才是真正的结论——这样报错信息才指向真实原因。
    """
    import certifi  # noqa: F401  (保证 certifi 随打包一起被收集)

    if insecure_ssl_allowed():
        ctx = ssl._create_unverified_context()  # noqa: SLF001
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)

    attempts: List[Tuple[str, Optional[ssl.SSLContext]]] = []
    primary = ssl_context()
    if primary is not None:
        attempts.append(("组合 CA (cafile+capath)", primary))

    # 再补上"只用 certifi"与"只用系统默认"两条独立路径。
    for source in ssl_candidates()[:3]:
        ctx = _build_context([source])
        if ctx is not None:
            label = "certifi" if "certifi" in source[1] else source[1]
            attempts.append((label, ctx))

    attempts.append(("系统默认", None))

    last_error: Optional[BaseException] = None
    for _label, ctx in attempts:
        try:
            if ctx is None:
                return urllib.request.urlopen(req, timeout=timeout)
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except Exception as exc:  # 网络类错误也换下一个候选没意义，但成本很低
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("无法发起 HTTPS 请求。")


def urlopen(req, timeout: float = 15):
    """`urllib.request.urlopen` 的证书安全版：自动处理 CA 缺失导致的校验失败。"""
    return _open(req, timeout)


def download_bytes(url: str, timeout: float = 8, headers: Optional[dict] = None) -> bytes:
    """下载 URL 内容（带超时与证书回退）。失败时抛异常，由调用方决定如何降级。"""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "BiliTabCapture"})
    with _open(req, timeout) as resp:
        return resp.read()
