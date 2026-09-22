from __future__ import annotations

import re
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar
from urllib.parse import urlparse


DATA_ROOT = Path(r"D:\视频下载器数据")
SESSION_ROOT = DATA_ROOT / "site-sessions"


def is_connection_interrupted(error: object) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in (
        "unexpected_eof_while_reading", "eof occurred in violation of protocol",
        "connection reset", "proxyerror", "proxy error", "remote end closed",
    ))


def with_direct_retry(operation, on_retry=None):
    """Keep the configured network route; retry a broken connection once directly."""
    try:
        return operation(False)
    except Exception as exc:
        if not is_connection_interrupted(exc):
            raise
        if on_retry:
            on_retry()
        return operation(True)


_SITE_GROUPS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be", "googlevideo.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com", "xhslink.cn"),
    "weibo": ("weibo.com", "weibo.cn"),
    "kuaishou": ("kuaishou.com", "gifshow.com"),
}

_NETWORK_MARKERS = (
    "timed out", "timeout", "temporary failure", "name resolution", "dns",
    "connection refused", "connection reset", "network is unreachable",
    "no route to host", "unable to connect", "远程主机", "网络连接",
)
_AUTH_MARKERS = (
    "fresh cookies", "sign in", "login required", "login to", "log in",
    "authentication required", "cookies are needed", "cookie is required",
    "account required", "confirm your age", "members only", "private video",
    "access restricted", "not available in your account", "captcha",
    "verify you are human", "security verification", "risk control",
    "扫码登录", "请登录", "登录后", "账号登录", "安全验证", "完成验证",
    "拖动滑块", "验证码", "访问受限", "风控", "风险验证", "人机验证",
)


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def site_key(value: str) -> str:
    host = (urlparse(value).hostname or value).lower().strip().rstrip(".")
    for key, domains in _SITE_GROUPS.items():
        if any(_matches(host, domain) for domain in domains):
            return key
    cleaned = re.sub(r"[^a-z0-9.-]+", "-", host).strip("-.")
    return cleaned[:80] or "generic"


def site_label(value: str) -> str:
    labels = {
        "douyin": "抖音", "bilibili": "哔哩哔哩", "youtube": "YouTube",
        "xiaohongshu": "小红书", "weibo": "微博", "kuaishou": "快手",
    }
    key = site_key(value)
    return labels.get(key, (urlparse(value).hostname or key))


@dataclass(frozen=True)
class SessionPaths:
    key: str
    root: Path
    profile: Path
    cookies: Path
    error: Path


def session_paths(value: str, data_root: Path = DATA_ROOT) -> SessionPaths:
    key = site_key(value)
    root = data_root / "site-sessions" / key
    return SessionPaths(key, root, root / "browser-profile", root / "cookies.txt", root / "last-error.txt")


def is_auth_required(error: object, url: str = "") -> bool:
    text = str(error or "").lower()
    if any(marker in text for marker in _NETWORK_MARKERS):
        return False
    key = site_key(url)
    if key == "bilibili" and re.search(r"(?:http\s*error\s*)?412\b", text):
        return True
    if key == "bilibili" and any(marker in text for marker in ("-352", "-412", "风控校验", "账号风控")):
        return True
    return any(marker in text for marker in _AUTH_MARKERS)


class RetryGate:
    """Allow one automatic retry; later retries must be explicit user actions."""

    def __init__(self, automatic_limit: int = 1) -> None:
        self.automatic_limit = automatic_limit
        self.automatic_attempts = 0

    def take_automatic(self) -> bool:
        if self.automatic_attempts >= self.automatic_limit:
            return False
        self.automatic_attempts += 1
        return True


class LoginSignals:
    """Thread-safe, non-blocking messages from the WebView JS bridge."""

    def __init__(self) -> None:
        self._retry = threading.Event()
        self._cancel = threading.Event()

    def request_retry(self) -> bool:
        if self._retry.is_set():
            return False
        self._retry.set()
        return True

    def consume_retry(self) -> bool:
        if not self._retry.is_set():
            return False
        self._retry.clear()
        return True

    def request_cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()


T = TypeVar("T")


class BoundedBackgroundCall(Generic[T]):
    """Run a possibly blocking browser call without ever blocking the UI loop.

    pywebview's Windows backend waits on unbounded semaphores for WebView2
    JavaScript and cookie operations. A navigation can strand that wait forever.
    This coordinator gives each call a deadline and ignores late completions so
    the login window and its native controls remain responsive.
    """

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._results: queue.Queue[tuple[int, bool, object]] = queue.Queue()
        self._job_id = 0
        self._active_job: int | None = None
        self._started_at = 0.0

    def start(self, operation: Callable[[], T], now: float | None = None) -> bool:
        with self._lock:
            if self._active_job is not None:
                return False
            self._job_id += 1
            job_id = self._job_id
            self._active_job = job_id
            self._started_at = time.monotonic() if now is None else now

        def worker() -> None:
            try:
                self._results.put((job_id, True, operation()))
            except BaseException as exc:
                self._results.put((job_id, False, exc))

        threading.Thread(target=worker, name=f"bounded-browser-call-{job_id}", daemon=True).start()
        return True

    def poll(self, now: float | None = None) -> tuple[str, object] | None:
        with self._lock:
            active_job = self._active_job
            started_at = self._started_at
        if active_job is None:
            return None

        while True:
            try:
                job_id, succeeded, value = self._results.get_nowait()
            except queue.Empty:
                break
            if job_id != active_job:
                continue
            with self._lock:
                self._active_job = None
            return ("success" if succeeded else "failed", value)

        current = time.monotonic() if now is None else now
        if current - started_at >= self.timeout_seconds:
            with self._lock:
                if self._active_job == active_job:
                    self._active_job = None
            return "timeout", None
        return None

    def active(self) -> bool:
        with self._lock:
            return self._active_job is not None
