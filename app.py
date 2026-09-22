from __future__ import annotations

import importlib.util
import ipaddress
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from tkinter import END, BOTH, DISABLED, HORIZONTAL, LEFT, NORMAL, RIGHT, W, X
from tkinter import StringVar, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from urllib.parse import parse_qs, urlparse

from session_auth import BoundedBackgroundCall, DATA_ROOT, LoginSignals, is_auth_required, session_paths, site_label, with_direct_retry
from browser_media import PLAYER_SNAPSHOT, validate_snapshot, media_info, video_id
from share_urls import is_xhs_short, normalize_xhs_url, resolve_xhs_share


FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https?://[^\s<>\"\]]+")
FORMAT_OPTIONS = {
    "最佳画质": "bv*+ba/b",
    "最高 1080P": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "最高 720P": "bv*[height<=720]+ba/b[height<=720]/b",
}
PATH_RECORD_FILE = DATA_ROOT / "last_path.txt"
LEGACY_PATH_RECORD_FILE = Path(r"D:\视频下载器路径\last_path.txt")


class DownloadCancelled(RuntimeError):
    pass


def extract_url(value: str) -> str | None:
    match = URL_RE.search(value)
    return match.group(0).rstrip(".,;，。；！!）)]") if match else None


def normalize_video_url(url: str) -> str:
    cleaned = url.replace("\\_", "_").replace("\\&", "&").replace("&amp;", "&")
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "douyin.com" or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com"):
        direct = re.search(r"/video/(\d{8,})", parsed.path)
        if direct:
            return f"https://www.douyin.com/video/{direct.group(1)}"
        query = parse_qs(parsed.query)
        modal_id = next(iter(query.get("modal_id", [])), "")
        if not modal_id:
            match = re.search(r"(?:[?&]|^)modal(?:\\|%5[cC])?_id=(\d{8,})", cleaned)
            modal_id = match.group(1) if match else ""
        if re.fullmatch(r"\d{8,}", modal_id):
            return f"https://www.douyin.com/video/{modal_id}"
    return normalize_xhs_url(cleaned)


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持公开的 HTTP/HTTPS 链接。")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("不允许本机或局域网链接。")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("不允许本机或局域网链接。")


def default_output() -> str:
    for candidate in (PATH_RECORD_FILE, LEGACY_PATH_RECORD_FILE):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def save_output(value: str) -> Path:
    value = value.strip().strip('"')
    if not value:
        raise ValueError("下载目录为空。")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = PATH_RECORD_FILE.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(PATH_RECORD_FILE)
    return PATH_RECORD_FILE


def _cookie_expiry(value: str) -> int:
    if not value:
        return 0
    try:
        return max(0, int(parsedate_to_datetime(value).timestamp()))
    except (TypeError, ValueError, OverflowError):
        return 0


def export_session_cookies(cookie_jars: list, destination: Path) -> int:
    lines = ["# Netscape HTTP Cookie File", "# Generated locally by VideoDownloader"]
    names: set[str] = set()
    for jar in cookie_jars:
        for morsel in jar.values():
            name = str(getattr(morsel, "key", "") or "").strip()
            domain = str(morsel["domain"] or "").strip().lower()
            if not name or not domain:
                continue
            value = str(getattr(morsel, "value", "") or "").replace("\t", "").replace("\r", "").replace("\n", "")
            path = str(morsel["path"] or "/")
            secure = "TRUE" if bool(morsel["secure"]) else "FALSE"
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            expires = _cookie_expiry(str(morsel["expires"] or ""))
            lines.append("\t".join((domain, include_subdomains, path, secure, str(expires), name, value)))
            names.add(name)
    if not names:
        raise RuntimeError("内置浏览器还没有生成可用的站点 Cookie，请先完成登录或验证。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(destination)
    return len(names)


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    try:
        for attempt in range(20):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                # Windows can briefly deny rename while the other process reads the state.
                time.sleep(0.025)
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _append_session_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"[{stamp}] {message}\n")


def run_session_browser(url: str, destination: Path | None = None, state_file: Path | None = None) -> int:
    paths = session_paths(url)
    destination = destination or paths.cookies
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.profile.mkdir(parents=True, exist_ok=True)
    label = site_label(url)
    session_log = paths.root / "session-browser.log"
    try:
        paths.error.unlink(missing_ok=True)
        _append_session_log(session_log, f"启动 {label} 独立登录窗口。")
        import webview
        logging.getLogger("pywebview").setLevel(logging.CRITICAL)

        class SessionApi:
            def __init__(self) -> None:
                self.window = None
                self.attempt = int(_read_state(state_file).get("attempt", 0)) if state_file else 0
                self.signals = LoginSignals()
                self.native_refs = {}

        api = SessionApi()
        window = webview.create_window(
            f"视频下载器 · {label} 登录或验证",
            url,
            width=1080,
            height=760,
            min_size=(760, 560),
            text_select=False,
        )
        result = {"ok": False, "attempt": api.attempt}
        window_closed = threading.Event()
        window.events.closed += window_closed.set

        def monitor(active_window) -> None:
            last_message = "请在页面中完成登录或验证，然后点击“我已登录，重新下载”。"
            exporter = BoundedBackgroundCall(timeout_seconds=15.0)
            is_douyin = paths.key == 'douyin' and bool(state_file)
            if is_douyin:
                last_message = '正在复用浏览器会话；原视频播放后将自动下载，也可点击重试。'
            expected_id = video_id(url)
            auto_until = time.monotonic() + 60
            next_probe = 0.0
            auto_submitted = False
            explicit_probe = False
            last_failure_attempt = None

            def capture_session():
                if is_douyin:
                    snapshot = validate_snapshot(active_window.evaluate_js(PLAYER_SNAPSHOT), expected_id)
                    return {'media': snapshot, 'count': 0}
                return {'count': export_session_cookies(active_window.get_cookies(), destination)}
            form = None
            status_label = None
            retry_button = None

            def install_native_toolbar() -> bool:
                nonlocal form, status_label, retry_button
                try:
                    from System import Action
                    from System.Drawing import Color, Font, FontStyle, ContentAlignment
                    from System.Windows.Forms import DockStyle, Padding, ToolStrip, ToolStripButton, ToolStripGripStyle, ToolStripLabel, ToolStripRenderMode
                    from webview.platforms import winforms

                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        form = winforms.BrowserView.instances.get(active_window.uid)
                        if form is not None:
                            break
                        time.sleep(0.05)
                    if form is None:
                        raise RuntimeError("没有找到 WebView2 原生窗口。")

                    ready = threading.Event()

                    def add_toolbar() -> None:
                        nonlocal status_label, retry_button
                        toolbar = ToolStrip()
                        toolbar.Dock = DockStyle.Top
                        toolbar.Height = 52
                        toolbar.Padding = Padding(12, 7, 12, 7)
                        toolbar.GripStyle = ToolStripGripStyle.Hidden
                        toolbar.RenderMode = ToolStripRenderMode.System
                        toolbar.BackColor = Color.FromArgb(238, 244, 255)
                        toolbar.Font = Font("Microsoft YaHei UI", 10.5, FontStyle.Regular)

                        status_label = ToolStripLabel(last_message)
                        status_label.AutoSize = False
                        status_label.Width = 620
                        status_label.TextAlign = ContentAlignment.MiddleLeft

                        retry_button = ToolStripButton("我已登录，重新下载")
                        retry_button.AutoSize = False
                        retry_button.Width = 190
                        cancel_button = ToolStripButton("取消")
                        cancel_button.AutoSize = False
                        cancel_button.Width = 80

                        def on_retry(_sender, _args) -> None:
                            if api.signals.request_retry():
                                retry_button.Enabled = False
                                status_label.Text = "正在解析当前播放视频…" if is_douyin else "正在安全导出登录状态…"

                        def on_cancel(_sender, _args) -> None:
                            api.signals.request_cancel()
                            if state_file:
                                _write_state(state_file, {"status": "cancelled", "attempt": api.attempt})
                            form.Close()

                        retry_button.Click += on_retry
                        cancel_button.Click += on_cancel
                        toolbar.Items.Add(status_label)
                        toolbar.Items.Add(retry_button)
                        toolbar.Items.Add(cancel_button)
                        form.Controls.Add(toolbar)
                        toolbar.BringToFront()
                        api.native_refs.update({
                            "toolbar": toolbar, "retry": retry_button, "cancel": cancel_button,
                            "on_retry": on_retry, "on_cancel": on_cancel,
                        })
                        ready.set()

                    form.BeginInvoke(Action(add_toolbar))
                    if not ready.wait(10):
                        raise RuntimeError("创建原生登录控制栏超时。")
                    _append_session_log(session_log, "WebView2 已启动，原生登录控制栏已就绪。")
                    return True
                except Exception as exc:
                    _append_session_log(session_log, f"原生控制栏初始化失败：{exc}")
                    if state_file:
                        _write_state(state_file, {"status": "failed", "attempt": api.attempt, "message": str(exc)})
                    return False

            def update_toolbar(message: str, retry_enabled: bool) -> None:
                if form is None or status_label is None or retry_button is None:
                    return
                try:
                    from System import Action

                    def update() -> None:
                        status_label.Text = message
                        retry_button.Enabled = retry_enabled

                    form.BeginInvoke(Action(update))
                except Exception:
                    pass

            def close_window() -> None:
                if form is None:
                    return
                try:
                    from System import Action
                    form.BeginInvoke(Action(form.Close))
                except Exception:
                    pass

            if not install_native_toolbar():
                close_window()
                return

            last_signature = None
            while not window_closed.is_set():
                time.sleep(0.1)
                try:
                    if api.signals.cancelled() or (state_file and _read_state(state_file).get('status') == 'cancelled'):
                        if state_file:
                            _write_state(state_file, {"status": "cancelled", "attempt": api.attempt})
                        _append_session_log(session_log, "用户取消登录。")
                        close_window()
                        return
                    requested = api.signals.consume_retry()
                    automatic = (is_douyin and not auto_submitted and time.monotonic() < auto_until
                                 and time.monotonic() >= next_probe and not exporter.active())
                    if requested or automatic:
                        explicit_probe = requested
                        started = exporter.start(capture_session)
                        if started:
                            next_probe = time.monotonic() + 2
                            if requested:
                                _append_session_log(session_log, '用户点击重试，开始解析当前视频。' if is_douyin else '用户确认登录，开始异步导出 Cookie。')
                                update_toolbar('正在解析当前播放视频…' if is_douyin else '正在安全导出登录状态…', False)

                    export_result = exporter.poll()
                    if export_result:
                        export_status, value = export_result
                        if export_status == "success":
                            count = int(value['count'])
                            api.attempt += 1
                            auto_submitted = True
                            message = '已识别当前视频，正在下载，请保留此窗口…' if is_douyin else f"已保存 {count} 项会话信息，正在重新下载…"
                            _append_session_log(session_log, message)
                            if state_file:
                                _write_state(state_file, {"status": "retry_requested", "attempt": api.attempt, "message": message, 'media': value.get('media')})
                            else:
                                result["ok"] = True
                                close_window()
                                return
                            update_toolbar(message, False)
                        elif export_status == "failed":
                            if is_douyin and not explicit_probe:
                                continue
                            last_message = str(value) if is_douyin else f"导出登录状态失败：{value}"
                            _append_session_log(session_log, last_message)
                            if state_file:
                                _write_state(state_file, {"status": "failed", "attempt": api.attempt, "message": last_message})
                            update_toolbar(last_message, True)
                        else:
                            auto_submitted = True
                            last_message = "页面解析超过 15 秒，请等待视频播放后点击重试。"
                            _append_session_log(session_log, "Cookie 导出超过 15 秒，已解除等待。")
                            if state_file:
                                _write_state(state_file, {"status": "failed", "attempt": api.attempt, "message": last_message})
                            update_toolbar(last_message, True)

                    state = _read_state(state_file) if state_file else {}
                    status = state.get("status")
                    message = str(state.get("message") or last_message)
                    if status == "success":
                        result["ok"] = True
                        _append_session_log(session_log, "主程序重试下载成功，关闭登录窗口。")
                        update_toolbar("下载成功，正在关闭登录窗口…", False)
                        time.sleep(0.6)
                        close_window()
                        return
                    signature = (status, message, state.get('attempt'))
                    if signature != last_signature:
                        last_signature = signature
                        if status == "failed":
                            last_message = message
                            update_toolbar(message, True)
                            # Every failed attempt must re-enable retry, including an identical error.
                            last_failure_attempt = state.get('attempt')
                        elif status == 'downloading':
                            update_toolbar(message, False)
                    if status == 'failed' and state.get('attempt') != last_failure_attempt:
                        last_failure_attempt = state.get('attempt')
                        update_toolbar(message, True)
                except Exception as exc:
                    _append_session_log(session_log, f"登录监控异常：{exc}")
                    if state_file and _read_state(state_file).get("status") == "success":
                        return

        webview.start(
            monitor,
            (window,),
            gui="edgechromium",
            private_mode=False,
            storage_path=str(paths.profile),
        )
        if result["ok"]:
            return 0
        if state_file and _read_state(state_file).get("status") not in {"cancelled", "success"}:
            _write_state(state_file, {"status": "cancelled", "attempt": api.attempt})
        if not paths.error.exists():
            paths.error.write_text("登录窗口已关闭，下载未继续。", encoding="utf-8")
        return 1
    except Exception as exc:
        paths.error.parent.mkdir(parents=True, exist_ok=True)
        paths.error.write_text(str(exc), encoding="utf-8")
        _append_session_log(session_log, f"登录窗口异常退出：{exc}")
        return 1


def enable_windows_high_dpi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class QueueLogger:
    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        self.events = events

    def debug(self, message: str) -> None:
        if message and not message.startswith("[debug]"):
            self.events.put(("log", message))

    def warning(self, message: str) -> None:
        self.events.put(("log", f"WARNING: {message}"))

    def error(self, message: str) -> None:
        self.events.put(("log", f"ERROR: {message}"))


class DownloaderApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("视频下载器")
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        width = min(900, max(720, screen_width - 100))
        height = min(780, max(620, screen_height - 140))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(720, width), min(650, height))
        self.root.configure(background="#F3F6FB")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.output_var = StringVar(value=default_output())
        self.quality_var = StringVar(value="最佳画质")
        self.status_var = StringVar(value="就绪")

        self._configure_styles()
        self._build()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 11))
        style.configure("App.TFrame", background="#F3F6FB")
        style.configure("Header.TFrame", background="#132238")
        style.configure(
            "HeaderTitle.TLabel",
            background="#132238",
            foreground="#FFFFFF",
            font=("Microsoft YaHei UI", 20, "normal"),
        )
        style.configure("HeaderSub.TLabel", background="#132238", foreground="#B9C8DD")
        style.configure("Card.TFrame", background="#FFFFFF", relief="flat")
        style.configure(
            "CardTitle.TLabel",
            background="#FFFFFF",
            foreground="#172033",
            font=("Microsoft YaHei UI", 12, "normal"),
        )
        style.configure("CardText.TLabel", background="#FFFFFF", foreground="#697386")
        style.configure("CardLabel.TLabel", background="#FFFFFF", foreground="#334155")
        style.configure(
            "Accent.TButton",
            background="#2563EB",
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(18, 9),
            font=("Microsoft YaHei UI", 11, "normal"),
        )
        style.map("Accent.TButton", background=[("active", "#1D4ED8"), ("disabled", "#93B4EE")])
        style.configure("Soft.TButton", background="#EAF1FF", foreground="#2456A6", borderwidth=0, padding=(11, 7))
        style.map("Soft.TButton", background=[("active", "#DCE8FF")])
        style.configure("Quiet.TButton", background="#F1F4F9", foreground="#475569", borderwidth=0, padding=(11, 7))
        style.map("Quiet.TButton", background=[("active", "#E5EAF2")])
        style.configure("Modern.TEntry", fieldbackground="#F8FAFD", bordercolor="#D7DFEB", padding=7)
        style.configure("Modern.TCombobox", fieldbackground="#F8FAFD", padding=6)
        style.configure(
            "Blue.Horizontal.TProgressbar",
            background="#2563EB",
            troughcolor="#E5ECF6",
            bordercolor="#E5ECF6",
            lightcolor="#2563EB",
            darkcolor="#2563EB",
        )
        style.configure("Status.TLabel", background="#F3F6FB", foreground="#526074")

    def _build(self) -> None:
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(24, 16))
        header.pack(fill=X)
        ttk.Label(header, text="视频下载器", style="HeaderTitle.TLabel").pack(anchor=W)
        ttk.Label(
            header,
            text="粘贴公开链接，选择保存位置，视频会直接下载到本地。",
            style="HeaderSub.TLabel",
        ).pack(anchor=W, pady=(2, 0))

        container = ttk.Frame(self.root, style="App.TFrame", padding=(20, 14))
        container.pack(fill=BOTH, expand=True)

        link_card = ttk.Frame(container, style="Card.TFrame", padding=14)
        link_card.pack(fill=X)
        ttk.Label(link_card, text="01  视频链接", style="CardTitle.TLabel").pack(anchor=W)
        ttk.Label(link_card, text="支持直接链接，也支持包含链接的整段分享文案。", style="CardText.TLabel").pack(
            anchor=W, pady=(2, 7)
        )
        self.input_box = ScrolledText(
            link_card,
            height=3,
            wrap="word",
            font=("Microsoft YaHei UI", 11),
            background="#F8FAFD",
            foreground="#172033",
            insertbackground="#172033",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#D7DFEB",
            highlightcolor="#2563EB",
            padx=9,
            pady=7,
        )
        self.input_box.pack(fill=X)
        input_buttons = ttk.Frame(link_card, style="Card.TFrame")
        input_buttons.pack(fill=X, pady=(7, 0))
        ttk.Button(input_buttons, text="粘贴链接", style="Soft.TButton", command=self._paste_link).pack(side=LEFT)
        ttk.Button(input_buttons, text="清空", style="Quiet.TButton", command=self._clear_link).pack(side=LEFT, padx=7)

        settings_card = ttk.Frame(container, style="Card.TFrame", padding=14)
        settings_card.pack(fill=X, pady=(10, 0))
        ttk.Label(settings_card, text="02  保存与画质", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=5, sticky=W
        )
        ttk.Label(settings_card, text="下载目录", style="CardLabel.TLabel").grid(row=1, column=0, sticky=W, pady=(10, 0))
        self.output_entry = ttk.Entry(settings_card, textvariable=self.output_var, style="Modern.TEntry")
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=(11, 7), pady=(10, 0))
        self.output_entry.bind("<FocusOut>", self._persist_output)
        self.output_entry.bind("<Return>", self._persist_output)
        ttk.Button(settings_card, text="浏览", style="Soft.TButton", command=self._choose_output).grid(
            row=1, column=2, pady=(10, 0)
        )
        ttk.Button(settings_card, text="打开目录", style="Quiet.TButton", command=self._open_output).grid(
            row=1, column=3, padx=(7, 0), pady=(10, 0)
        )

        ttk.Label(settings_card, text="视频画质", style="CardLabel.TLabel").grid(row=2, column=0, sticky=W, pady=(9, 0))
        ttk.Combobox(
            settings_card,
            textvariable=self.quality_var,
            values=list(FORMAT_OPTIONS),
            state="readonly",
            style="Modern.TCombobox",
            width=18,
        ).grid(row=2, column=1, sticky=W, padx=(11, 7), pady=(9, 0))
        ttk.Button(settings_card, text="自动会话说明", style="Quiet.TButton", command=self._open_advanced).grid(
            row=2, column=2, columnspan=2, sticky="e", pady=(9, 0)
        )
        settings_card.columnconfigure(1, weight=1)

        action_bar = ttk.Frame(container, style="App.TFrame")
        action_bar.pack(fill=X, pady=(12, 8))
        self.download_button = ttk.Button(action_bar, text="开始下载", style="Accent.TButton", command=self._start)
        self.download_button.pack(side=LEFT)
        self.cancel_button = ttk.Button(
            action_bar, text="取消下载", style="Quiet.TButton", command=self._cancel, state=DISABLED
        )
        self.cancel_button.pack(side=LEFT, padx=8)

        self.progress = ttk.Progressbar(
            container,
            orient=HORIZONTAL,
            mode="determinate",
            maximum=100,
            style="Blue.Horizontal.TProgressbar",
        )
        self.progress.pack(fill=X)
        ttk.Label(container, textvariable=self.status_var, style="Status.TLabel").pack(anchor=W, pady=(5, 0))

        self.log = ScrolledText(
            container,
            height=7,
            wrap="word",
            state=DISABLED,
            font=("Microsoft YaHei UI", 11),
            background="#111827",
            foreground="#C9D5E7",
            insertbackground="#FFFFFF",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log.pack(fill=BOTH, expand=True, pady=(7, 0))

    def _paste_link(self) -> None:
        try:
            value = self.root.clipboard_get()
        except Exception:
            messagebox.showwarning("剪贴板", "剪贴板里没有可读取的文本。")
            return
        self.input_box.delete("1.0", END)
        self.input_box.insert("1.0", value)

    def _clear_link(self) -> None:
        self.input_box.delete("1.0", END)
        self.input_box.focus_set()

    def _choose_output(self) -> None:
        initial = self.output_var.get()
        selected = filedialog.askdirectory(initialdir=initial if initial and Path(initial).is_dir() else str(Path.home()))
        if selected:
            self.output_var.set(selected)
            self._persist_output()

    def _persist_output(self, _event=None) -> None:
        value = self.output_var.get().strip().strip('"')
        if not value:
            return
        try:
            record = save_output(value)
            self.status_var.set(f"已记录下载目录：{record}")
        except (OSError, ValueError) as exc:
            self.status_var.set(f"目录可继续使用，但无法保存路径记录：{exc}")

    def _open_advanced(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("自动会话")
        dialog.geometry("680x390")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.configure(background="#F3F6FB")

        frame = ttk.Frame(dialog, style="Card.TFrame", padding=18)
        frame.pack(fill=BOTH, expand=True, padx=14, pady=14)
        ttk.Label(frame, text="各网站独立登录会话", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=W
        )
        session_root = DATA_ROOT / "site-sessions"
        session_count = len([path for path in session_root.iterdir() if path.is_dir()]) if session_root.is_dir() else 0
        session_status = f"已保存 {session_count} 个网站的独立会话" if session_count else "尚未建立，遇到登录要求时会自动创建"
        ttk.Label(
            frame,
            text=f"当前状态：{session_status}",
            style="CardLabel.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky=W, pady=(10, 5))
        ttk.Label(
            frame,
            text="程序优先直接下载，失败时复用该网站已保存的独立浏览器会话。抖音会识别页面中当前播放的视频并自动下载；需要时请完成页面验证或点击重试。浏览器提取模式保存当前播放器清晰度，可先在页面调整画质。其他网站使用导出的会话重试。",
            style="CardText.TLabel",
            wraplength=590,
            justify=LEFT,
        ).grid(row=2, column=0, columnspan=3, sticky=W, pady=(0, 14))
        ttk.Label(frame, text="会话数据位置", style="CardLabel.TLabel").grid(
            row=3, column=0, columnspan=3, sticky=W
        )
        ttk.Label(
            frame,
            text=str(DATA_ROOT),
            style="CardText.TLabel",
            wraplength=590,
            justify=LEFT,
        ).grid(row=4, column=0, columnspan=3, sticky=W, pady=(3, 14))
        ttk.Button(frame, text="打开数据目录", style="Soft.TButton", command=self._open_data_root).grid(
            row=5, column=0, sticky=W
        )
        ttk.Button(frame, text="重置全部网站会话", style="Quiet.TButton", command=self._reset_auto_session).grid(
            row=5, column=1, sticky=W, padx=(8, 0)
        )
        ttk.Button(frame, text="完成", style="Accent.TButton", command=dialog.destroy).grid(
            row=6, column=2, sticky="e", pady=(24, 0)
        )
        frame.columnconfigure(0, weight=1)
        dialog.grab_set()

    def _open_data_root(self) -> None:
        try:
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                ["explorer.exe", str(DATA_ROOT)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            messagebox.showerror("无法打开数据目录", str(exc))

    def _reset_auto_session(self) -> None:
        if not messagebox.askyesno(
            "重置自动会话",
            "这会删除下载器为各网站单独保存的登录会话。下次需要登录时会重新打开窗口，是否继续？",
        ):
            return
        try:
            session_root = DATA_ROOT / "site-sessions"
            if session_root.is_dir():
                shutil.rmtree(session_root)
            self.status_var.set("自动会话已重置")
            messagebox.showinfo("重置完成", "所有网站会话已删除，下次需要登录时会重新建立。")
        except OSError as exc:
            messagebox.showerror("重置失败", str(exc))

    def _append_log(self, value: str) -> None:
        self.log.configure(state=NORMAL)
        self.log.insert(END, value.rstrip() + "\n")
        self.log.see(END)
        self.log.configure(state=DISABLED)

    def _start(self) -> None:
        raw = self.input_box.get("1.0", END).strip()
        url = extract_url(raw)
        if not url:
            messagebox.showerror("链接无效", "没有找到 http:// 或 https:// 开头的视频链接。")
            return
        try:
            url = normalize_video_url(url)
            validate_public_url(url)
        except ValueError as exc:
            messagebox.showerror("链接不允许", str(exc))
            return

        output_value = self.output_var.get().strip().strip('"')
        if not output_value:
            messagebox.showerror("请选择下载目录", "下载目录当前为空，请输入路径或点击“浏览”。")
            return
        self._persist_output()
        output = Path(output_value).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            output = output.resolve()
        except OSError as exc:
            messagebox.showerror("保存目录不可用", str(exc))
            return

        self.cancel_event.clear()
        self.progress["value"] = 0
        self.progress.configure(mode='indeterminate')
        self.progress.start(15)
        self.status_var.set("正在准备下载…")
        self.download_button.configure(state=DISABLED)
        self.cancel_button.configure(state=NORMAL)
        self._append_log(f"URL: {url}")
        self._append_log(f"保存目录: {output}")
        paths = session_paths(url)
        self._append_log(f"站点会话: {site_label(url)}（独立保存，不读取本机浏览器）")
        selected_format = FORMAT_OPTIONS[self.quality_var.get()]
        self.worker = threading.Thread(
            target=self._download,
            args=(url, output, selected_format),
            daemon=True,
        )
        self.worker.start()

    def _download(
        self,
        url: str,
        output: Path,
        selected_format: str,
    ) -> None:
        try:
            from yt_dlp import YoutubeDL

            def check_cancel():
                if self.cancel_event.is_set():
                    raise DownloadCancelled('用户取消下载')

            check_cancel()
            url = normalize_video_url(url)
            if is_xhs_short(url):
                self.events.put(('status', '正在解析小红书分享链接…'))
                url = with_direct_retry(
                    lambda direct: resolve_xhs_share(url, direct=direct, check_cancel=check_cancel),
                    lambda: self.events.put(('log', '分享链接连接中断，正在直连重试…')),
                )
                self.events.put(('log', '已自动转换为小红书笔记链接，访问参数已保留。'))

            def progress_hook(data: dict) -> None:
                if self.cancel_event.is_set():
                    raise DownloadCancelled("用户取消下载")
                status = data.get("status")
                if status == "downloading":
                    downloaded = float(data.get("downloaded_bytes") or 0)
                    total = float(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                    if total > 0:
                        self.events.put(("progress", min(100.0, downloaded * 100.0 / total)))
                    speed = data.get("_speed_str", "").strip()
                    eta = data.get("_eta_str", "").strip()
                    if speed or eta:
                        self.events.put(("status", f"正在下载  速度 {speed}  剩余 {eta}"))
                elif status == "finished":
                    self.events.put(("progress", 100.0))
                    self.events.put(("status", "文件下载完成，正在确认结果…"))

            def postprocessor_hook(data: dict) -> None:
                if data.get("postprocessor") != "Merger":
                    return
                if data.get("status") == "started":
                    self.events.put(("status", "正在合并音视频…"))
                elif data.get("status") == "finished":
                    self.events.put(("status", "音视频合并完成，正在确认结果…"))

            def download_once(active_cookie: Path | None, browser_media: dict | None = None) -> int:
                options = {
                    "format": selected_format,
                    "paths": {"home": str(output)},
                    "outtmpl": {"default": "%(title).120s [%(id)s].%(ext)s"},
                    "noplaylist": True,
                    "windowsfilenames": True,
                    "merge_output_format": "mp4",
                    "writethumbnail": False,
                    "progress_hooks": [progress_hook],
                    "postprocessor_hooks": [postprocessor_hook],
                    "logger": QueueLogger(self.events),
                    "quiet": True,
                    "no_warnings": False,
                    "socket_timeout": 20,
                    "retries": 2,
                    "extractor_retries": 1,
                }
                if active_cookie and active_cookie.is_file():
                    options["cookiefile"] = str(active_cookie.resolve())
                if browser_media:
                    options['format'] = 'best'
                    options['proxy'] = ''
                    self.events.put(('log', f"已识别浏览器当前清晰度：{browser_media['width']}×{browser_media['height']}。"))
                    self.events.put(('status', '正在下载浏览器当前播放的视频…'))
                try:
                    import imageio_ffmpeg

                    options["ffmpeg_location"] = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    self.events.put(("log", "WARNING: 未定位到内置 FFmpeg，部分高清音视频可能无法合并。"))
                def attempt(direct: bool) -> int:
                    if self.cancel_event.is_set():
                        raise DownloadCancelled("用户取消下载")
                    route_options = dict(options)
                    if direct:
                        route_options["proxy"] = ""
                    with YoutubeDL(route_options) as downloader:
                        if browser_media:
                            downloader.process_ie_result(media_info(browser_media), download=True)
                            return 0
                        return int(downloader.download([url]) or 0)

                return with_direct_retry(attempt, lambda: self.events.put((
                    "log", "网络连接被中断，正在绕过代理直连重试一次（无需重新登录）…"
                )))

            paths = session_paths(url)
            try:
                # Public videos should work without login. Do not force a saved session.
                code = download_once(None)
            except Exception as first_error:
                if not is_auth_required(first_error, url):
                    raise
                label = site_label(url)
                paths = session_paths(url)
                if paths.cookies.is_file():
                    self.events.put(("status", f"正在尝试已保存的 {label} 会话…"))
                    try:
                        code = download_once(paths.cookies)
                    except Exception as saved_error:
                        if not is_auth_required(saved_error, url):
                            raise
                        first_error = saved_error
                    else:
                        self.events.put(("log", f"已复用 {label} 独立会话，下载成功。"))
                        self.events.put(("done", int(code or 0)))
                        return
                self.events.put(("status", f"正在打开 {label} 浏览器解析视频…"))
                self.events.put(("log", f"{label} 接口提取失败，尝试在浏览器中解析；已有登录会话会自动复用。"))
                paths.root.mkdir(parents=True, exist_ok=True)
                state_file = paths.root / f"retry-{uuid.uuid4().hex}.json"
                _write_state(state_file, {
                    "status": "waiting", "attempt": 0,
                    "message": "请等待原视频播放，程序将自动识别；必要时完成页面验证并点击重试。",
                })
                helper_args = [sys.executable]
                if not FROZEN:
                    helper_args.append(str(Path(__file__).resolve()))
                helper_args.extend(("--session-browser", url, str(paths.cookies), str(state_file)))
                process = subprocess.Popen(helper_args)
                handled_attempt = 0
                deadline = time.monotonic() + 900
                code = 1
                try:
                    while time.monotonic() < deadline:
                        if self.cancel_event.is_set():
                            _write_state(state_file, {"status": "cancelled", "attempt": handled_attempt})
                            raise DownloadCancelled("用户取消下载")
                        state = _read_state(state_file)
                        if state.get("status") == "cancelled":
                            raise DownloadCancelled("用户取消登录")
                        attempt = int(state.get("attempt", 0) or 0)
                        if state.get("status") == "retry_requested" and attempt > handled_attempt:
                            handled_attempt = attempt
                            message = '已识别视频，正在连接下载服务器…' if state.get('media') else f"正在使用 {label} 独立会话重新下载…"
                            self.events.put(("status", message))
                            self.events.put(('log', message))
                            _write_state(state_file, {'status': 'downloading', 'attempt': attempt, 'message': message})
                            try:
                                code = download_once(paths.cookies, state.get('media'))
                                if code:
                                    raise RuntimeError(f'下载器返回失败状态 {code}')
                                _write_state(state_file, {"status": "success", "attempt": attempt})
                                self.events.put(("log", f"{label} 下载成功，浏览器会话保留供下次使用。"))
                                break
                            except Exception as retry_error:
                                message = str(retry_error)
                                friendly = (
                                    "已取得会话，但网站接口仍拒绝请求。重复登录未必有效，可取消本次下载。"
                                    if is_auth_required(retry_error, url)
                                    else f"下载仍失败：{message[:500]}"
                                )
                                _write_state(state_file, {"status": "failed", "attempt": attempt, "message": friendly})
                                self.events.put(("log", friendly))
                                self.events.put(('status', '下载未完成，请查看浏览器提示或取消'))
                        if process.poll() is not None and state.get("status") != "success":
                            raise RuntimeError("登录窗口已关闭，下载未继续。") from first_error
                        time.sleep(0.25)
                    else:
                        raise RuntimeError("等待登录超时，请重新开始下载。")
                finally:
                    if process.poll() is None and _read_state(state_file).get('status') != 'success':
                        _write_state(state_file, {'status': 'cancelled', 'attempt': handled_attempt})
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                    if process.poll() is None and _read_state(state_file).get("status") == "success":
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                    state_file.unlink(missing_ok=True)
            self.events.put(("done", int(code or 0)))
        except DownloadCancelled:
            self.events.put(("cancelled", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _drain_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(value))
                elif event == "progress":
                    self.progress.stop()
                    self.progress.configure(mode='determinate')
                    self.progress["value"] = float(value)
                    self.status_var.set(f"正在下载：{float(value):.1f}%")
                elif event == "status":
                    self.status_var.set(str(value))
                elif event == "done":
                    self._finish(int(value))
                elif event == "cancelled":
                    self._finish(1, cancelled=True)
                elif event == "error":
                    self._finish(1, str(value))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _finish(self, return_code: int, error: str | None = None, cancelled: bool = False) -> None:
        self.progress.stop()
        self.progress.configure(mode='determinate')
        self.download_button.configure(state=NORMAL)
        self.cancel_button.configure(state=DISABLED)
        if return_code == 0:
            self.progress["value"] = 100
            self.status_var.set("下载完成")
            messagebox.showinfo("下载完成", f"视频已经保存到：\n{self.output_var.get()}")
        elif cancelled:
            self.status_var.set("下载已取消")
            self._append_log("下载已由用户取消。")
        else:
            self.status_var.set("下载失败")
            if error:
                self._append_log(error)
            messagebox.showerror(
                "下载未完成",
                "请查看窗口下方日志。链接失效、平台规则变化、网络错误或登录限制都可能导致失败。",
            )

    def _cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.cancel_button.configure(state=DISABLED)
            self.status_var.set("正在取消…")

    def _open_output(self) -> None:
        try:
            output_value = self.output_var.get().strip().strip('"')
            if not output_value:
                messagebox.showwarning("下载目录为空", "请先输入目录或点击“浏览”选择目录。")
                return
            self._persist_output()
            output = Path(output_value).expanduser()
            output.mkdir(parents=True, exist_ok=True)
            output = output.resolve()
            if os.name == "nt":
                subprocess.Popen(
                    ["explorer.exe", str(output)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                subprocess.Popen(["xdg-open", str(output)])
            self.status_var.set(f"已打开目录：{output}")
        except Exception as exc:
            messagebox.showerror("无法打开目录", f"{exc}\n\n你仍可以复制界面中的目录地址到资源管理器。")

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("退出", "下载仍在进行，确定取消并退出吗？"):
                return
            self.cancel_event.set()
        self.root.destroy()


def self_test(output_path: Path | None = None) -> int:
    ffmpeg_path = None
    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    result = {
        "python": sys.executable,
        "frozen": FROZEN,
        "yt_dlp": importlib.util.find_spec("yt_dlp") is not None,
        "imageio_ffmpeg": importlib.util.find_spec("imageio_ffmpeg") is not None,
        "ffmpeg": ffmpeg_path,
        "ffmpeg_exists": bool(ffmpeg_path and Path(ffmpeg_path).is_file()),
        "tkinter": importlib.util.find_spec("tkinter") is not None,
        "pywebview": importlib.util.find_spec("webview") is not None,
        "default_output": str(default_output()),
        "path_record": str(PATH_RECORD_FILE),
        "data_root": str(DATA_ROOT),
        "session_root": str(DATA_ROOT / "site-sessions"),
    }
    result["ok"] = all(
        result[key] for key in ("yt_dlp", "imageio_ffmpeg", "ffmpeg_exists", "tkinter", "pywebview")
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if output_path:
        output_path.write_text(rendered, encoding="utf-8")
    elif sys.stdout:
        print(rendered)
    return 0 if result["ok"] else 1


def download_check(url: str, output: Path, report: Path) -> int:
    """Run the exact GUI worker for packaged end-to-end regression checks."""
    url = normalize_video_url(url)
    validate_public_url(url)
    output.mkdir(parents=True, exist_ok=True)
    instance = object.__new__(DownloaderApp)
    instance.events = queue.Queue()
    instance.cancel_event = threading.Event()
    worker = threading.Thread(target=instance._download, args=(url, output, 'bv*+ba/b'), daemon=True)
    worker.start()
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            event, value = instance.events.get(timeout=1)
        except queue.Empty:
            continue
        if event in ('done', 'error', 'cancelled'):
            ok = event == 'done' and value == 0
            _write_state(report, {'ok': ok, 'event': event, 'value': value})
            return 0 if ok else 1
    instance.cancel_event.set()
    worker.join(30)
    _write_state(report, {'ok': False, 'event': 'timeout'})
    return 2


if __name__ == "__main__":
    if '--download-check' in sys.argv:
        index = sys.argv.index('--download-check')
        raise SystemExit(download_check(sys.argv[index+1], Path(sys.argv[index+2]), Path(sys.argv[index+3])))
    if "--session-browser" in sys.argv:
        index = sys.argv.index("--session-browser")
        session_url = sys.argv[index + 1]
        session_destination = Path(sys.argv[index + 2]) if len(sys.argv) > index + 2 else None
        state_file = Path(sys.argv[index + 3]) if len(sys.argv) > index + 3 else None
        raise SystemExit(run_session_browser(session_url, session_destination, state_file))
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        destination = Path(sys.argv[index + 1]).resolve() if len(sys.argv) > index + 1 else None
        raise SystemExit(self_test(destination))
    enable_windows_high_dpi()
    window = Tk()
    DownloaderApp(window)
    window.mainloop()
