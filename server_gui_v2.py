"""Secure Local Video Server (SLVS) v2.1.0

本机 Tkinter 界面 + Flask 内网服务 + Cloudflare Quick Tunnel。
分享一个本地视频，链接带随机 Token、自动过期、可随时撤销。
"""

from __future__ import annotations

import hashlib
import html
import mimetypes
import os
import re
import secrets
import string
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque

import tkinter as tk
from tkinter import filedialog, messagebox

from flask import Flask, Response, abort, make_response, request
from werkzeug.serving import make_server


# ============================================================
# 基本信息
# ============================================================

APP_NAME = "Secure Local Video Server"
APP_VERSION = "2.1.1"

HOST = "127.0.0.1"
# 端口 0 = 由系统分配空闲端口，避免固定 8000 被占用导致启动失败。
PORT = 0

CHUNK_SIZE = 256 * 1024
MAX_LOG_LINES = 400
MAX_SESSIONS = 6

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CLOUDFLARED_PATH = os.path.join(BASE_DIR, "cloudflared.exe")

EXPIRE_CHOICES = {
    "5 分钟": 5 * 60,
    "10 分钟": 10 * 60,
    "30 分钟": 30 * 60,
    "1 小时": 60 * 60,
    "3 小时": 3 * 60 * 60,
    "6 小时": 6 * 60 * 60,
    "12 小时": 12 * 60 * 60,
    "24 小时": 24 * 60 * 60,
}

VIDEO_EXTS = (
    ".mp4", ".webm", ".mov", ".m4v", ".mkv",
    ".avi", ".wmv", ".flv", ".mpeg", ".mpg", ".ts",
)

# 常见下载器 / 命令行工具的 UA 特征。
DENY_UA = re.compile(
    r"(curl|wget|wget2|aria2|axel|python-requests|python-urllib|urllib|aiohttp|"
    r"httpx|httpie|postman|insomnia|go-http-client|java/|libwww|perl|ruby|"
    r"node-fetch|axios|okhttp|ffmpeg|ffprobe|yt-dlp|youtube-dl|you-get|"
    r"vlc|mpv|mplayer|internet download manager|idm|thunder|xunlei|"
    r"powershell|dotnet|scrapy|guzzle|mechanize|httpclient)",
    re.IGNORECASE,
)

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".ogg": "video/ogg",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".ts": "video/mp2t",
}


def get_mime_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


# ============================================================
# 分享状态
# ============================================================

class ShareState:
    """一次分享的全部运行时状态（只在内存里，绝不落盘）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.active = False
        self.file_path = ""
        self.link_token = ""
        self.created_at = 0.0
        self.expires_at = 0.0
        self.revoked = True
        self.public_url = ""
        self.public_host = ""
        self.local_url = ""
        self.sessions: dict[str, dict] = {}

    # ---------- 生命周期 ----------

    def start(self, file_path: str, seconds: int) -> None:
        with self._lock:
            self.reset()
            self.active = True
            self.revoked = False
            self.file_path = os.path.abspath(file_path)
            self.link_token = generate_token(40)
            self.created_at = time.time()
            self.expires_at = self.created_at + seconds
            self.sessions = {}

    def set_public_url(self, url: str) -> None:
        with self._lock:
            self.public_url = url
            self.public_host = urllib.parse.urlsplit(url).netloc

    def set_local_url(self, url: str) -> None:
        with self._lock:
            self.local_url = url

    def reset(self) -> None:
        with self._lock:
            self.active = False
            self.revoked = True
            self.file_path = ""
            self.link_token = ""
            self.created_at = 0.0
            self.expires_at = 0.0
            self.public_url = ""
            self.public_host = ""
            self.local_url = ""
            self.sessions = {}

    # ---------- 查询 ----------

    def remaining(self) -> int:
        with self._lock:
            if not self.active or self.revoked:
                return 0
            return max(0, int(self.expires_at - time.time()))

    def live(self) -> bool:
        with self._lock:
            if not self.active or self.revoked:
                return False
            if time.time() >= self.expires_at:
                return False
            if not self.file_path or not os.path.isfile(self.file_path):
                return False
            return True

    def link_ok(self, token: str) -> bool:
        with self._lock:
            if not self.live():
                return False
            return secrets.compare_digest(str(token), self.link_token)

    def file_size(self) -> int:
        try:
            return os.path.getsize(self.file_path)
        except OSError:
            return 0

    def filename(self) -> str:
        return os.path.basename(self.file_path) if self.file_path else ""

    # ---------- 会话 ----------

    def new_session(self, user_agent: str) -> dict | None:
        with self._lock:
            if not self.live():
                return None
            if len(self.sessions) >= MAX_SESSIONS:
                oldest = min(self.sessions, key=lambda k: self.sessions[k]["created"])
                self.sessions.pop(oldest, None)
            session = {
                "sid": secrets.token_urlsafe(18),
                "ua": ua_fingerprint(user_agent),
                "ticket": secrets.token_urlsafe(24),
                "created": time.time(),
                "hits": deque(maxlen=600),
            }
            self.sessions[session["sid"]] = session
            return session

    def session_ok(self, sid: str, ticket: str, user_agent: str) -> dict | None:
        with self._lock:
            if not self.live():
                return None
            session = self.sessions.get(sid)
            if session is None:
                return None
            if not secrets.compare_digest(session["ticket"], str(ticket)):
                return None
            if not secrets.compare_digest(session["ua"], ua_fingerprint(user_agent)):
                return None
            # 简单限速：同一会话每分钟最多 180 次媒体请求。
            now = time.time()
            hits = session["hits"]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= 180:
                return None
            hits.append(now)
            return session

    def forget_session(self, sid: str) -> None:
        with self._lock:
            self.sessions.pop(sid, None)


STATE = ShareState()


# ============================================================
# 工具函数
# ============================================================

def generate_token(length: int = 32) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def ua_fingerprint(user_agent: str) -> str:
    return hashlib.sha256((user_agent or "").strip().encode("utf-8", "replace")).hexdigest()


def mask(token: str, keep: int = 4) -> str:
    if not token:
        return ""
    return token[:keep] + "…" + token[-2:]


def format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def ua_blocked(user_agent: str) -> bool:
    ua = (user_agent or "").strip()
    if len(ua) < 20:
        return True
    return bool(DENY_UA.search(ua))


# ============================================================
# 页面
# ============================================================

BASE_STYLE = """
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
        margin: 0; padding: 18px;
        background: radial-gradient(circle at 50% 0%, #1b1b1f 0%, #0b0b0d 70%);
        color: #f2f2f2;
        font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
        display: flex; flex-direction: column; align-items: center;
        min-height: 100%;
    }
    h1 { font-size: 17px; font-weight: 600; margin: 4px 0 6px; max-width: 96vw;
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .meta { color: #9a9aa2; font-size: 13px; margin-bottom: 12px; }
    .meta b { color: #d8d8e0; font-variant-numeric: tabular-nums; }
    .player { position: relative; width: min(100%, 1200px); }
    video { width: 100%; max-height: 78vh; background: #000;
            border-radius: 12px; display: block;
            -webkit-touch-callout: none; -webkit-user-select: none; user-select: none; }
    .wm { position: absolute; left: 12%; top: 78%; opacity: .16; color: #fff;
          font-size: 12px; letter-spacing: 1px; pointer-events: none;
          transition: left 1.2s ease, top 1.2s ease; }
    .note { color: #6f6f78; font-size: 12px; margin-top: 12px; text-align: center; }
    .dead video { filter: grayscale(1) brightness(.35); }
"""

EXPIRED_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>链接已失效</title>
<style>
    body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
           background:#0b0b0d; color:#eee; font-family:"Segoe UI","Microsoft YaHei",sans-serif; }
    .box { text-align:center; padding:40px 46px; background:#17171b; border-radius:16px;
           border:1px solid #24242a; }
    h1 { font-size:22px; margin:0 0 10px; }
    p { color:#8b8b94; font-size:13px; margin:0; }
</style></head>
<body><div class="box"><h1>链接已失效</h1>
<p>该分享已过期、被撤销，或链接不正确。</p></div></body></html>"""

DENIED_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>无法访问</title>
<style>
    body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
           background:#0b0b0d; color:#eee; font-family:"Segoe UI","Microsoft YaHei",sans-serif; }
    .box { text-align:center; padding:36px 40px; background:#17171b; border-radius:16px;
           border:1px solid #24242a; }
    h1 { font-size:20px; margin:0 0 8px; }
    p { color:#8b8b94; font-size:13px; margin:0; }
</style></head>
<body><div class="box"><h1>无法访问</h1>
<p>请使用浏览器打开分享链接。</p></div></body></html>"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="robots" content="noindex,nofollow,noarchive,noimageindex">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#0b0b0d">
<title>@@TITLE@@</title>
<style>@@STYLE@@</style>
</head>
<body>
<div class="player">
    <h1>@@FILENAME@@</h1>
    <div class="meta">剩余时间 <b id="t">@@TIME@@</b> · 到期自动失效</div>
    <video id="p" controls playsinline webkit-playsinline x5-playsinline
           preload="metadata" controlslist="nodownload noplaybackrate noremoteplayback"
           disablepictureinpicture oncontextmenu="return false;">
        <source src="@@SRC@@" type="@@MIME@@">
        你的浏览器不支持 HTML5 视频。
    </video>
    <div id="wm" class="wm">@@MARK@@</div>
    <p class="note">私有临时分享 · 请勿转发 · 到期或撤销后立即失效</p>
</div>
<script>
(function () {
    var player = document.getElementById("p");
    var timer = document.getElementById("t");
    var box = document.querySelector(".player");
    var left = @@REMAIN@@;

    function fmt(sec) {
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = sec % 60;
        var mm = String(m).padStart(2, "0");
        var ss = String(s).padStart(2, "0");
        return h > 0 ? h + ":" + mm + ":" + ss : mm + ":" + ss;
    }

    function stopPlayback() {
        try {
            player.pause();
            player.removeAttribute("src");
            player.load();
        } catch (e) {}
        if (box) { box.classList.add("dead"); }
    }

    function tick() {
        if (left <= 0) {
            timer.textContent = "已过期";
            stopPlayback();
            return;
        }
        timer.textContent = fmt(left);
        left -= 1;
    }

    tick();
    setInterval(tick, 1000);

    player.addEventListener("error", function () {
        timer.textContent = "链接已失效";
        stopPlayback();
    });

    // 去掉浏览器自带的下载 / 画中画 / 远程播放入口（支持的浏览器才有效）。
    try {
        player.controlsList.add("nodownload");
        player.controlsList.add("noplaybackrate");
        player.controlsList.add("noremoteplayback");
        player.disablePictureInPicture = true;
        player.disableRemotePlayback = true;
    } catch (e) {}

    document.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    document.addEventListener("dragstart", function (e) { e.preventDefault(); });
    document.addEventListener("keydown", function (e) {
        var key = (e.key || "").toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (key === "s" || key === "u")) {
            e.preventDefault();
            e.stopPropagation();
        }
    });

    // 走动水印：降低录屏后裁剪的可用性。
    var wm = document.getElementById("wm");
    if (wm) {
        setInterval(function () {
            wm.style.left = (6 + Math.random() * 72) + "%";
            wm.style.top = (12 + Math.random() * 70) + "%";
        }, 9000);
    }
})();
</script>
</body>
</html>
"""


def render_page(token: str, session: dict) -> str:
    filename = STATE.filename()
    safe_name = html.escape(filename[:160])
    media_url = f"/s/{session['sid']}/{session['ticket']}"
    remaining = STATE.remaining()
    page = PAGE_TEMPLATE
    page = page.replace("@@STYLE@@", BASE_STYLE)
    page = page.replace("@@TITLE@@", safe_name or "Video")
    page = page.replace("@@FILENAME@@", safe_name)
    page = page.replace("@@TIME@@", format_seconds(remaining))
    page = page.replace("@@SRC@@", media_url)
    page = page.replace("@@MIME@@", get_mime_type(filename))
    page = page.replace("@@MARK@@", html.escape(session["sid"][:10]))
    page = page.replace("@@REMAIN@@", str(remaining))
    return page


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024


@app.after_request
def apply_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, noimageindex"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers.pop("Server", None)
    return response


@app.route("/")
def home():
    return EXPIRED_HTML, 404


@app.route("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /\n", 404, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/v/<token>")
def video_page(token):
    if not STATE.link_ok(token):
        return EXPIRED_HTML, 410

    user_agent = request.headers.get("User-Agent", "")
    if ua_blocked(user_agent):
        return DENIED_HTML, 403

    # 只接受浏览器页面跳转，挡掉直接抓 HTML 的脚本。
    accept = request.headers.get("Accept", "")
    fetch_mode = request.headers.get("Sec-Fetch-Mode", "").lower()
    if fetch_mode and fetch_mode != "navigate":
        return DENIED_HTML, 403
    if accept and "text/html" not in accept and accept.strip() not in ("*/*", ""):
        return DENIED_HTML, 403

    session = STATE.new_session(user_agent)
    if session is None:
        return EXPIRED_HTML, 410

    response = make_response(render_page(token, session))
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; media-src 'self'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"
    )
    response.set_cookie(
        "slvs_sid",
        session["sid"],
        max_age=max(60, STATE.remaining()),
        httponly=True,
        samesite="Strict",
        path="/",
    )
    return response


def parse_range(header: str, size: int):
    """返回 (start, end) 或 None（无 Range）或 "invalid"。"""
    if not header:
        return None
    header = header.strip()
    if not header.lower().startswith("bytes="):
        return "invalid"
    spec = header[6:].split(",")[0].strip()
    if "-" not in spec:
        return "invalid"
    first, last = spec.split("-", 1)
    try:
        if first == "":
            suffix = int(last)
            if suffix <= 0:
                return "invalid"
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
    except ValueError:
        return "invalid"
    if start < 0 or start >= size:
        return "invalid"
    end = min(end, size - 1)
    if start > end:
        return "invalid"
    return start, end


def iter_file(path: str, start: int, length: int, deadline: float):
    remaining = length
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            if time.time() >= deadline:
                break
            data = handle.read(min(CHUNK_SIZE, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@app.route("/s/<sid>/<ticket>")
def stream_video(sid, ticket):
    if not STATE.live():
        abort(410)

    user_agent = request.headers.get("User-Agent", "")
    if ua_blocked(user_agent):
        abort(403)

    dest = request.headers.get("Sec-Fetch-Dest", "").lower()
    fetch_aware = any(
        request.headers.get(name) is not None
        for name in ("Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site")
    )

    # 浏览器媒体管道取流时一定带 Sec-Fetch-Dest: video。
    # 播放器里的「下载」按钮走的是下载器 / 脚本，Dest 是 empty、document 之类，
    # 一律挡掉——这是目前唯一能把「看」和「存」分开的信号。
    if fetch_aware and dest != "video":
        abort(403)

    # 会话 Cookie 必须与 URL 中的会话一致，光有链接拿不到媒体。
    if request.cookies.get("slvs_sid") != sid:
        abort(403)

    session = STATE.session_ok(sid, ticket, user_agent)
    if session is None:
        abort(403)

    # 防盗链：媒体请求必须来自分享页所在的主机。
    referer = request.headers.get("Referer", "")
    if referer:
        ref_host = urllib.parse.urlsplit(referer).netloc
        allowed = {STATE.public_host, urllib.parse.urlsplit(STATE.local_url).netloc}
        allowed.discard("")
        if ref_host not in allowed:
            abort(403)
    elif not fetch_aware:
        # 完全不发 Fetch Metadata 的老浏览器，要求至少带上正确来源页。
        abort(403)

    path = STATE.file_path
    try:
        size = os.path.getsize(path)
    except OSError:
        abort(410)
    if size <= 0:
        abort(410)

    deadline = STATE.expires_at
    mime = get_mime_type(STATE.filename())

    if request.method == "HEAD":
        response = Response(b"", status=200, mimetype=mime)
        response.headers["Content-Length"] = str(size)
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Disposition"] = "inline"
        return response

    parsed = parse_range(request.headers.get("Range", ""), size)
    if parsed == "invalid":
        response = Response(b"", status=416)
        response.headers["Content-Range"] = f"bytes */{size}"
        return response

    if parsed is None:
        start, end = 0, size - 1
        status = 200
    else:
        start, end = parsed
        status = 206

    length = end - start + 1

    response = Response(
        iter_file(path, start, length, deadline),
        status=status,
        mimetype=mime,
        direct_passthrough=True,
    )
    response.headers["Content-Length"] = str(length)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Disposition"] = "inline"
    response.headers["Cache-Control"] = "no-store"
    if status == 206:
        response.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


@app.errorhandler(404)
def not_found(_):
    return EXPIRED_HTML, 404


@app.errorhandler(500)
def server_error(_):
    return EXPIRED_HTML, 500


# ============================================================
# 界面
# ============================================================

from tkinter import ttk


# ---- 配色 ----
COLOR_BG = "#0c0f14"
COLOR_CARD = "#151a22"
COLOR_BORDER = "#242c3a"
COLOR_INPUT = "#0f141c"
COLOR_TEXT = "#e9eef7"
COLOR_MUTED = "#8b96aa"
COLOR_TRACK = "#1c2330"
COLOR_ACCENT = "#4f8cff"
COLOR_ACCENT_HI = "#6fa1ff"
COLOR_DANGER = "#ff5f6b"

UI_FONT = "Microsoft YaHei UI"
MONO_FONT = "Cascadia Mono"


def _button(parent, text, command, kind="ghost", width=None):
    if kind == "primary":
        bg, fg, hover = COLOR_ACCENT, "#ffffff", COLOR_ACCENT_HI
    elif kind == "danger":
        bg, fg, hover = "#1a1418", COLOR_DANGER, "#2a1a20"
    else:
        bg, fg, hover = "#1b2230", COLOR_TEXT, "#232c3d"

    btn = tk.Button(
        parent, text=text, command=command, width=width,
        font=(UI_FONT, 10, "bold" if kind == "primary" else "normal"),
        bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
        disabledforeground="#5b6478", relief="flat", bd=0,
        highlightthickness=1,
        highlightbackground=COLOR_BORDER if kind != "primary" else bg,
        highlightcolor=COLOR_BORDER,
        padx=18, pady=9, cursor="hand2",
    )
    btn.base_bg = bg
    btn.hover_bg = hover

    def enter(_):
        if str(btn.cget("state")) != "disabled":
            btn.configure(bg=hover)

    def leave(_):
        if str(btn.cget("state")) != "disabled":
            btn.configure(bg=bg)

    btn.bind("<Enter>", enter)
    btn.bind("<Leave>", leave)
    return btn


def _set_enabled(btn, enabled):
    btn.configure(state="normal" if enabled else "disabled",
                  bg=btn.base_bg if enabled else "#171d27",
                  cursor="hand2" if enabled else "arrow")


def _entry(parent, textvariable=None, state="normal", font=None):
    return tk.Entry(
        parent, textvariable=textvariable, state=state,
        font=font or (UI_FONT, 10),
        bg=COLOR_INPUT, fg=COLOR_TEXT, disabledforeground=COLOR_MUTED,
        readonlybackground=COLOR_INPUT, insertbackground=COLOR_TEXT,
        relief="flat", highlightthickness=1,
        highlightbackground=COLOR_BORDER, highlightcolor=COLOR_ACCENT, bd=0,
    )


class VideoServerGUI:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("960x920")
        self.root.minsize(900, 860)
        self.root.configure(bg=COLOR_BG)

        self.server = None
        self.server_thread = None
        self.cloudflare_process = None
        self.port = 0
        self.public_url = ""
        self.local_url = ""
        self.running = False
        self.total_seconds = 0
        self._tick_job = None
        self._cf_buffer: list[str] = []

        self._init_style()
        self.create_gui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._dark_titlebar()

    def _dark_titlebar(self):
        """Windows 10/11 深色标题栏，和界面配色统一。"""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes

            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE 新旧取值
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    # --------------------------------------------------------
    # 主题
    # --------------------------------------------------------

    def _init_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_INPUT, background=COLOR_CARD,
            foreground=COLOR_TEXT, arrowcolor=COLOR_MUTED,
            bordercolor=COLOR_BORDER, lightcolor=COLOR_CARD, darkcolor=COLOR_CARD,
            selectbackground=COLOR_INPUT, selectforeground=COLOR_TEXT,
            padding=6,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COLOR_INPUT)],
            foreground=[("readonly", COLOR_TEXT)],
            background=[("active", COLOR_CARD)],
            selectbackground=[("readonly", COLOR_INPUT)],
            selectforeground=[("readonly", COLOR_TEXT)],
        )
        style.configure(
            "Bar.Horizontal.TProgressbar",
            troughcolor=COLOR_TRACK, background=COLOR_ACCENT,
            bordercolor=COLOR_CARD, lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT,
            thickness=6,
        )

        self.root.option_add("*TCombobox*Listbox.background", COLOR_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)

        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0, background="#2b3546", darkcolor="#1b2230",
            lightcolor="#1b2230", troughcolor=COLOR_CARD,
            bordercolor=COLOR_CARD, arrowcolor=COLOR_MUTED, arrowsize=12,
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", "#3b4759")],
        )

    # --------------------------------------------------------
    # 布局
    # --------------------------------------------------------

    def create_gui(self):
        tk.Frame(self.root, bg=COLOR_ACCENT, height=3).pack(side="top", fill="x")

        wrap = tk.Frame(self.root, bg=COLOR_BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=(18, 14))

        self._build_header(wrap)
        self._build_file_card(wrap)
        self._build_setting_card(wrap)
        self._build_link_card(wrap)
        self._build_actions(wrap)
        self._build_status(wrap)

        tk.Label(
            wrap, text=f"v{APP_VERSION} · 仅监听 127.0.0.1 · 不写入任何磁盘记录",
            bg=COLOR_BG, fg="#5e6879", font=(UI_FONT, 8),
        ).pack(side="bottom", pady=(10, 0))

        self._build_log(wrap)

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=COLOR_BG)
        header.pack(fill="x", pady=(0, 16))

        left = tk.Frame(header, bg=COLOR_BG)
        left.pack(side="left")
        tk.Label(left, text="Secure Local Video Server", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=(UI_FONT, 19, "bold")).pack(anchor="w")
        tk.Label(left, text="临时视频分享 · 随机 Token · 自动过期 · 仅浏览器可看",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=(UI_FONT, 9)).pack(anchor="w", pady=(4, 0))

        pill = tk.Label(header, text=f"v{APP_VERSION}", bg="#1b2230", fg=COLOR_ACCENT,
                        font=(MONO_FONT, 9, "bold"), padx=12, pady=5)
        pill.pack(side="right", pady=(6, 0))

    def _card(self, parent, title, pady=(0, 12)):
        outer = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                         highlightthickness=1)
        outer.pack(fill="x", pady=pady)
        body = tk.Frame(outer, bg=COLOR_CARD)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 14))
        tk.Label(body, text=title, bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(0, 10))
        return body

    def _build_file_card(self, parent):
        body = self._card(parent, "①  视频文件")

        row = tk.Frame(body, bg=COLOR_CARD)
        row.pack(fill="x")

        self.file_var = tk.StringVar()
        self.file_entry = _entry(row, self.file_var, state="readonly")
        self.file_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 10))

        self.choose_button = _button(row, "选择视频", self.select_video)
        self.choose_button.pack(side="right")

    def _build_setting_card(self, parent):
        body = self._card(parent, "②  分享设置")

        row = tk.Frame(body, bg=COLOR_CARD)
        row.pack(fill="x")

        tk.Label(row, text="有效期", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=(UI_FONT, 9)).pack(side="left", padx=(0, 8))

        self.expire_var = tk.StringVar(value="30 分钟")
        combo = ttk.Combobox(row, textvariable=self.expire_var, state="readonly",
                             values=list(EXPIRE_CHOICES.keys()), width=9,
                             style="Dark.TCombobox", font=(UI_FONT, 9))
        combo.pack(side="left")

        self.autocopy_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row, text="生成后自动复制链接", variable=self.autocopy_var,
            bg=COLOR_CARD, fg=COLOR_MUTED, activebackground=COLOR_CARD,
            activeforeground=COLOR_TEXT, selectcolor=COLOR_INPUT, bd=0,
            highlightthickness=0, font=(UI_FONT, 9), cursor="hand2",
        ).pack(side="left", padx=(18, 0))

        token_row = tk.Frame(body, bg=COLOR_CARD)
        token_row.pack(fill="x", pady=(12, 0))
        tk.Label(token_row, text="Token", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=(UI_FONT, 9)).pack(side="left", padx=(0, 8))
        self.token_var = tk.StringVar(value="生成后显示")
        self.token_entry = _entry(token_row, self.token_var, state="readonly",
                                  font=(MONO_FONT, 9))
        self.token_entry.pack(side="left", fill="x", expand=True, ipady=5)

    def _build_link_card(self, parent):
        body = self._card(parent, "③  分享链接")

        row = tk.Frame(body, bg=COLOR_CARD)
        row.pack(fill="x")

        self.public_url_var = tk.StringVar(value="等待生成…")
        link_entry = _entry(row, self.public_url_var, state="readonly",
                            font=(MONO_FONT, 9))
        link_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 10))

        self.copy_button = _button(row, "复制", self.copy_url)
        self.copy_button.pack(side="right")

        actions = tk.Frame(body, bg=COLOR_CARD)
        actions.pack(fill="x", pady=(12, 0))

        self.open_button = _button(actions, "公网打开", self.open_url)
        self.open_button.pack(side="left")
        self.preview_button = _button(actions, "本机预览", self.open_local)
        self.preview_button.pack(side="left", padx=(10, 0))

        _set_enabled(self.open_button, False)
        _set_enabled(self.preview_button, False)

    def _build_actions(self, parent):
        row = tk.Frame(parent, bg=COLOR_BG)
        row.pack(fill="x", pady=(4, 14))

        self.start_button = _button(row, "🚀  生成分享链接", self.start_server,
                                    kind="primary", width=20)
        self.start_button.pack(side="left", ipady=6)

        self.stop_button = _button(row, "撤销 / 停止", self.stop_server,

                                   kind="danger", width=14)
        self.stop_button.pack(side="left", padx=(10, 0), ipady=6)
        _set_enabled(self.stop_button, False)

    def _build_status(self, parent):
        card = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))

        inner = tk.Frame(card, bg=COLOR_CARD)
        inner.pack(fill="x", padx=16, pady=12)

        line = tk.Frame(inner, bg=COLOR_CARD)
        line.pack(fill="x")

        self.status_dot = tk.Canvas(line, width=10, height=10, bg=COLOR_CARD,
                                    highlightthickness=0)
        self.status_dot.pack(side="left", pady=2)
        self._dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill="#5b6478", outline="")

        self.status_var = tk.StringVar(value="未启动")
        tk.Label(line, textvariable=self.status_var, bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=(UI_FONT, 10)).pack(side="left", padx=(8, 0))

        self.remain_var = tk.StringVar(value="")
        tk.Label(line, textvariable=self.remain_var, bg=COLOR_CARD, fg=COLOR_ACCENT,
                 font=(MONO_FONT, 12, "bold")).pack(side="right")

        self.progress = ttk.Progressbar(inner, style="Bar.Horizontal.TProgressbar",
                                        maximum=100, value=0)
        self.progress.pack(fill="x", pady=(10, 0))

    def _build_log(self, parent):
        outer = tk.Frame(parent, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                         highlightthickness=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=COLOR_CARD)
        inner.pack(fill="both", expand=True, padx=12, pady=(10, 12))

        tk.Label(inner, text="运行日志", bg=COLOR_CARD, fg=COLOR_MUTED,
                 font=(UI_FONT, 9, "bold")).pack(anchor="w", pady=(0, 8))

        box = tk.Frame(inner, bg=COLOR_CARD)
        box.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            box, height=9, font=(MONO_FONT, 9), state="disabled",
            bg="#0b0f15", fg="#b9c4d6", insertbackground="#b9c4d6",
            relief="flat", bd=0, highlightthickness=0, wrap="word",
            selectbackground=COLOR_ACCENT, padx=10, pady=8,
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview,
                               style="Dark.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scroll.set)

    # --------------------------------------------------------
    # 小工具
    # --------------------------------------------------------

    def _status(self, text, color):
        self.status_var.set(text)
        self.status_dot.itemconfigure(self._dot_id, fill=color)

    # --------------------------------------------------------
    # 日志
    # --------------------------------------------------------

    def log(self, message: str):
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"

        def write():
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n")
            lines = int(self.log_text.index("end-1c").split(".")[0])
            if lines > MAX_LOG_LINES:
                self.log_text.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        try:
            self.root.after(0, write)
        except tk.TclError:
            pass

    # --------------------------------------------------------
    # 选择视频
    # --------------------------------------------------------

    def select_video(self):
        path = filedialog.askopenfilename(
            title="选择视频",
            filetypes=[("视频文件", " ".join("*" + ext for ext in VIDEO_EXTS)),
                       ("所有文件", "*.*")],
        )
        if not path:
            return
        if not os.path.isfile(path):
            messagebox.showerror("错误", "文件不存在。")
            return
        size = os.path.getsize(path)
        self.file_var.set(path)
        self.log(f"已选择：{os.path.basename(path)}（{format_size(size)}）")
        if os.path.splitext(path)[1].lower() in (".mkv", ".avi", ".wmv", ".flv", ".mpg", ".mpeg"):
            self.log("提示：该封装格式部分浏览器不能直接播放，建议用 MP4(H.264/AAC)。")

    # --------------------------------------------------------
    # 启动
    # --------------------------------------------------------

    def start_server(self):
        if self.running:
            messagebox.showinfo("提示", "服务器已经在运行。")
            return

        video = self.file_var.get().strip()
        if not video:
            messagebox.showerror("错误", "请先选择视频文件。")
            return
        if not os.path.isfile(video):
            messagebox.showerror("错误", "视频文件不存在。")
            return

        seconds = EXPIRE_CHOICES[self.expire_var.get()]
        self.total_seconds = seconds
        STATE.start(video, seconds)

        try:
            self.server = make_server(HOST, PORT, app, threaded=True)
        except OSError as exc:
            STATE.reset()
            messagebox.showerror("启动失败", f"无法绑定本地端口：{exc}")
            return

        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        self.running = True
        self.public_url = ""
        self.local_url = f"http://{HOST}:{self.port}/v/{STATE.link_token}"
        STATE.set_local_url(self.local_url)

        self.token_var.set(mask(STATE.link_token))
        self.public_url_var.set("正在建立 Cloudflare 隧道…")
        _set_enabled(self.start_button, False)
        _set_enabled(self.stop_button, True)
        _set_enabled(self.open_button, False)
        _set_enabled(self.preview_button, True)
        self._status("本地服务已启动", COLOR_ACCENT)
        self.progress.configure(value=100)

        self.log("=" * 46)
        self.log("启动分享")
        self.log(f"文件：{os.path.basename(video)}（{format_size(STATE.file_size())}）")
        self.log(f"本地端口：{self.port}")
        self.log(f"Token：{mask(STATE.link_token)}")
        self.log(f"有效期：{self.expire_var.get()}")

        self._schedule_tick()
        self.root.after(400, self.start_cloudflare)

    # --------------------------------------------------------
    # Cloudflare
    # --------------------------------------------------------

    def start_cloudflare(self):
        if not self.running:
            return
        if not os.path.isfile(CLOUDFLARED_PATH):
            self.log(f"找不到 cloudflared：{CLOUDFLARED_PATH}")
            self._status("找不到 cloudflared.exe", COLOR_DANGER)
            messagebox.showerror("缺少 cloudflared.exe",
                                 "请把 cloudflared.exe 放到程序目录：\n\n" + BASE_DIR)
            self.stop_server()
            return

        self.log("正在建立 Cloudflare Quick Tunnel…")
        self._status("正在建立公网连接…", COLOR_ACCENT)

        try:
            self.cloudflare_process = subprocess.Popen(
                [CLOUDFLARED_PATH, "tunnel", "--no-autoupdate",
                 "--url", f"http://{HOST}:{self.port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"Cloudflare 启动失败：{exc}")
            messagebox.showerror("启动失败", str(exc))
            self.stop_server()
            return

        threading.Thread(target=self.read_cloudflare, daemon=True).start()
        self.root.after(45000, self._tunnel_timeout)

    def read_cloudflare(self):
        process = self.cloudflare_process
        if not process or not process.stdout:
            return
        try:
            for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                self._cf_buffer.append(line)
                self.log("[cf] " + line[:300])
                match = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
                if match:
                    url = match.group(0) + "/v/" + STATE.link_token
                    self.root.after(0, lambda u=url: self.tunnel_ready(u))
        except Exception as exc:  # noqa: BLE001
            self.log(f"读取 Cloudflare 输出失败：{exc}")

        if self.running:
            self.root.after(0, self._tunnel_died)

    def _tunnel_timeout(self):
        if self.running and not self.public_url:
            self.log("建立隧道超时（45 秒），请检查网络。")
            messagebox.showerror("隧道超时", "无法建立 Cloudflare 隧道，请检查网络后重试。")
            self.stop_server()

    def _tunnel_died(self):
        if not self.running or self.public_url:
            return
        self.log("Cloudflare 进程已退出。")
        self.stop_server()

    def tunnel_ready(self, url: str):
        if not self.running:
            return
        self.public_url = url
        STATE.set_public_url(url)
        self.public_url_var.set(url)
        self._status("公网链接已就绪", "#3ddc97")
        _set_enabled(self.open_button, True)
        self.log(f"公网 URL：{url}")
        if self.autocopy_var.get():
            self._copy_to_clipboard(url)
            self.log("链接已复制到剪贴板。")

    # --------------------------------------------------------
    # 计时
    # --------------------------------------------------------

    def _schedule_tick(self):
        if self._tick_job:
            try:
                self.root.after_cancel(self._tick_job)
            except Exception:
                pass
        self._tick_job = self.root.after(1000, self._tick)

    def _tick(self):
        self._tick_job = None
        if not self.running:
            return
        left = STATE.remaining()
        self.remain_var.set(f"剩余 {format_seconds(left)}")
        if self.total_seconds:
            self.progress.configure(value=max(0.0, left / self.total_seconds * 100))
        if left <= 0:
            self.log("链接已到期，自动停止分享。")
            self.stop_server(auto=True)
            return
        self._tick_job = self.root.after(1000, self._tick)

    # --------------------------------------------------------
    # 复制 / 打开
    # --------------------------------------------------------

    def _copy_to_clipboard(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def copy_url(self):
        if not self.public_url:
            messagebox.showwarning("提示", "还没有生成公网链接。")
            return
        self._copy_to_clipboard(self.public_url)
        self.log("公网链接已复制。")

    def open_url(self):
        if not self.public_url:
            messagebox.showwarning("提示", "还没有生成公网链接。")
            return
        import webbrowser
        webbrowser.open(self.public_url)

    def open_local(self):
        if not self.local_url:
            messagebox.showwarning("提示", "还没有启动分享。")
            return
        import webbrowser
        webbrowser.open(self.local_url)

    # --------------------------------------------------------
    # 停止
    # --------------------------------------------------------

    def stop_server(self, auto: bool = False):
        if self._tick_job:
            try:
                self.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

        STATE.reset()

        process = self.cloudflare_process
        if process:
            try:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            except Exception:
                pass
            self.cloudflare_process = None

        server = self.server
        if server:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            self.server = None

        self.server_thread = None
        self.running = False
        self.public_url = ""
        self.local_url = ""
        self.port = 0
        self.total_seconds = 0
        self._cf_buffer.clear()

        self.public_url_var.set("已停止 / 已撤销" if not auto else "已到到期时间自动停止")
        self.token_var.set("已撤销")
        self._status("已停止", "#5b6478")
        self.remain_var.set("")
        self.progress.configure(value=0)
        _set_enabled(self.start_button, True)
        _set_enabled(self.stop_button, False)
        _set_enabled(self.open_button, False)
        _set_enabled(self.preview_button, False)
        self.log("分享已撤销，隧道已关闭。" if not auto else "分享到期，隧道已关闭。")

    # --------------------------------------------------------
    # 关闭
    # --------------------------------------------------------

    def on_close(self):
        try:
            self.stop_server()
        except Exception:
            pass
        self.root.destroy()


# ============================================================
# 主程序
# ============================================================

def main():
    root = tk.Tk()
    try:
        ico = os.path.join(BASE_DIR, "SecureLocalVideoServer.ico")
        if os.path.isfile(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    VideoServerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
