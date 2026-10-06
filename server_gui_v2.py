import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import subprocess
import os
import sys
import re
import socket
import secrets
import string
import time
import webbrowser
import html
import mimetypes

from flask import Flask, Response, abort, send_file


# ============================================================
# 基本配置
# ============================================================

HOST = "127.0.0.1"
PORT = 8000

# 兼容普通 .py 运行和 PyInstaller --onefile 打包后的 EXE
# PyInstaller 打包后会把附带文件解压到 sys._MEIPASS。
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CLOUDFLARED_PATH = os.path.join(BASE_DIR, "cloudflared.exe")


# ============================================================
# Flask
# ============================================================

app = Flask(__name__)

VIDEO_FILE = None
VIDEO_TOKEN = None

LINK_CREATED_TIME = 0
LINK_EXPIRE_SECONDS = 1800

LINK_REVOKED = False


# ============================================================
# Token
# ============================================================

def generate_token(length=32):

    chars = string.ascii_letters + string.digits

    return "".join(
        secrets.choice(chars)
        for _ in range(length)
    )


# ============================================================
# 检查 Token
# ============================================================

def check_token(token):

    global VIDEO_TOKEN
    global LINK_CREATED_TIME
    global LINK_EXPIRE_SECONDS
    global LINK_REVOKED

    if LINK_REVOKED:
        return False

    if not VIDEO_TOKEN:
        return False

    if token != VIDEO_TOKEN:
        return False

    elapsed = time.time() - LINK_CREATED_TIME

    if elapsed >= LINK_EXPIRE_SECONDS:
        return False

    if not VIDEO_FILE:
        return False

    if not os.path.isfile(VIDEO_FILE):
        return False

    return True


# ============================================================
# 剩余时间
# ============================================================

def get_remaining_seconds():

    remaining = (
        LINK_EXPIRE_SECONDS
        - (time.time() - LINK_CREATED_TIME)
    )

    return max(0, int(remaining))


# ============================================================
# MIME
# ============================================================

def get_mime_type(filename):

    ext = os.path.splitext(filename)[1].lower()

    mime_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".ogg": "video/ogg",
        ".ogv": "video/ogg",
        ".mov": "video/quicktime",
        ".m4v": "video/mp4",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".wmv": "video/x-ms-wmv",
        ".flv": "video/x-flv",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg",
    }

    return mime_types.get(
        ext,
        mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )


# ============================================================
# HTML：过期页面
# ============================================================

def expired_page():

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>链接已失效</title>

        <style>
            body {
                background: #111;
                color: #fff;
                font-family: Arial, sans-serif;
                text-align: center;
                padding-top: 100px;
            }

            .box {
                max-width: 500px;
                margin: auto;
                padding: 40px;
                background: #1d1d1d;
                border-radius: 15px;
            }

            h1 {
                font-size: 30px;
            }

            p {
                color: #aaa;
            }
        </style>
    </head>

    <body>

        <div class="box">

            <h1>🔒 链接已失效</h1>

            <p>
                这个视频分享链接已经过期或被撤销。
            </p>

        </div>

    </body>
    </html>
    """


# ============================================================
# 首页
# ============================================================

@app.route("/")
def home():

    return """
    <!DOCTYPE html>
    <html>

    <head>
        <meta charset="UTF-8">
        <title>Video Server</title>
    </head>

    <body>

        <h2>Secure Video Server</h2>

        <p>
            请使用完整的视频分享链接访问。
        </p>

    </body>

    </html>
    """


# ============================================================
# 视频网页
# ============================================================

@app.route("/v/<token>")
def video_page(token):

    if not check_token(token):

        return expired_page(), 410


    filename = os.path.basename(VIDEO_FILE)

    safe_filename = html.escape(
        filename
    )

    stream_url = "/stream/" + token

    remaining = get_remaining_seconds()

    minutes = remaining // 60

    seconds = remaining % 60


    return f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <meta
            name="robots"
            content="noindex,nofollow,noarchive"
        >

        <title>{safe_filename}</title>


        <style>

            * {{
                box-sizing: border-box;
            }}

            body {{

                margin: 0;

                padding: 20px;

                background: #101010;

                color: white;

                font-family:
                    Arial,
                    "Microsoft YaHei",
                    sans-serif;

                text-align: center;

            }}


            .container {{

                max-width: 1400px;

                margin: auto;

            }}


            h2 {{

                margin: 10px 0 5px 0;

                font-size: 22px;

                word-break: break-all;

            }}


            .info {{

                color: #aaa;

                font-size: 14px;

                margin-bottom: 15px;

            }}


            video {{

                width: 100%;

                max-height: 80vh;

                background: black;

                border-radius: 10px;

            }}


            .warning {{

                margin-top: 15px;

                color: #888;

                font-size: 13px;

            }}

        </style>

    </head>


    <body
        oncontextmenu="return false;"
    >

        <div class="container">

            <h2>{safe_filename}</h2>

            <div class="info">

                分享链接剩余：

                <span id="timer">
                    {minutes:02d}:{seconds:02d}
                </span>

            </div>


            <video
                id="player"
                controls
                controlsList="nodownload noplaybackrate"
                disablePictureInPicture
                preload="metadata"
                oncontextmenu="return false;"
            >

                <source
                    src="{stream_url}"
                    type="{get_mime_type(filename)}"
                >

                你的浏览器不支持 HTML5 视频。

            </video>


            <div class="warning">

                临时分享链接 · 到期后自动失效

            </div>

        </div>


        <script>

            let remaining = {remaining};


            function updateTimer() {{

                if (remaining <= 0) {{

                    document.getElementById(
                        "timer"
                    ).innerText = "已过期";

                    const player =
                        document.getElementById(
                            "player"
                        );

                    player.pause();

                    player.removeAttribute(
                        "src"
                    );

                    return;

                }}


                const minutes =
                    Math.floor(remaining / 60);

                const seconds =
                    remaining % 60;


                document.getElementById(
                    "timer"
                ).innerText =

                    String(minutes).padStart(2, "0")
                    + ":"
                    +
                    String(seconds).padStart(2, "0");


                remaining--;

            }}


            setInterval(
                updateTimer,
                1000
            );


            // 尽量阻止常见的保存快捷键。
            // 注意：这不是绝对防下载。
            document.addEventListener(
                "keydown",
                function(event) {{

                    if (
                        (event.ctrlKey || event.metaKey)
                        &&
                        (
                            event.key === "s"
                            ||
                            event.key === "S"
                        )
                    ) {{

                        event.preventDefault();

                    }}

                }}
            );

        </script>

    </body>

    </html>
    """


# ============================================================
# 视频流
# ============================================================

@app.route("/stream/<token>")
def stream_video(token):

    if not check_token(token):

        abort(410)


    filename = os.path.basename(
        VIDEO_FILE
    )

    mime = get_mime_type(
        filename
    )


    response = send_file(

        VIDEO_FILE,

        mimetype=mime,

        conditional=True,

        etag=True,

        last_modified=os.path.getmtime(
            VIDEO_FILE
        )

    )


    # 尽量让浏览器在线播放，而不是主动下载。

    response.headers[
        "Content-Disposition"
    ] = "inline; filename*=UTF-8''" + (
        filename.encode(
            "utf-8"
        ).decode(
            "latin-1",
            errors="ignore"
        )
    )


    # 防止搜索引擎索引。

    response.headers[
        "X-Robots-Tag"
    ] = "noindex, nofollow, noarchive"


    # 不缓存。

    response.headers[
        "Cache-Control"
    ] = "no-store, no-cache, must-revalidate"


    response.headers[
        "Pragma"
    ] = "no-cache"


    return response


# ============================================================
# Flask 服务器
# ============================================================

def run_flask():

    app.run(

        host=HOST,

        port=PORT,

        threaded=True,

        debug=False,

        use_reloader=False

    )


# ============================================================
# GUI
# ============================================================

class VideoServerGUI:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Secure Local Video URL Server v2.0"
        )

        self.root.geometry(
            "820x720"
        )

        self.root.resizable(
            False,
            False
        )


        self.flask_thread = None

        self.cloudflare_process = None

        self.server_running = False

        self.tunnel_running = False

        self.public_url = ""

        self.expire_seconds = 1800


        self.create_gui()


        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )


    # ========================================================
    # GUI
    # ========================================================

    def create_gui(self):

        title = tk.Label(

            self.root,

            text="🔐 Secure Local Video Server",

            font=(
                "Segoe UI",
                20,
                "bold"
            )

        )

        title.pack(
            pady=(20, 3)
        )


        subtitle = tk.Label(

            self.root,

            text=
            "临时视频分享 · 随机 Token · 自动过期 · Cloudflare Tunnel",

            font=(
                "Segoe UI",
                10
            )

        )

        subtitle.pack(
            pady=(0, 20)
        )


        # ====================================================
        # 视频
        # ====================================================

        file_frame = tk.LabelFrame(

            self.root,

            text="① 视频文件",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=10,

            pady=10

        )

        file_frame.pack(

            fill="x",

            padx=25,

            pady=5

        )


        self.file_var = tk.StringVar()


        self.file_entry = tk.Entry(

            file_frame,

            textvariable=self.file_var,

            font=(
                "Segoe UI",
                10
            )

        )

        self.file_entry.pack(

            side="left",

            fill="x",

            expand=True,

            padx=(0, 10)

        )


        tk.Button(

            file_frame,

            text="选择视频",

            width=12,

            command=self.select_video

        ).pack(
            side="right"
        )


        # ====================================================
        # 有效时间
        # ====================================================

        setting_frame = tk.LabelFrame(

            self.root,

            text="② 分享安全设置",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=10,

            pady=10

        )

        setting_frame.pack(

            fill="x",

            padx=25,

            pady=10

        )


        tk.Label(

            setting_frame,

            text="链接有效期：",

            font=(
                "Segoe UI",
                10
            )

        ).grid(

            row=0,

            column=0,

            sticky="w"

        )


        self.expire_var = tk.StringVar(

            value="30 分钟"

        )


        expire_menu = tk.OptionMenu(

            setting_frame,

            self.expire_var,

            "5 分钟",

            "10 分钟",

            "30 分钟",

            "1 小时",

            "3 小时",

            "6 小时",

            "12 小时",

            "24 小时"

        )

        expire_menu.config(
            width=12
        )

        expire_menu.grid(

            row=0,

            column=1,

            sticky="w",

            padx=10

        )


        tk.Label(

            setting_frame,

            text="随机 Token：",

            font=(
                "Segoe UI",
                10
            )

        ).grid(

            row=1,

            column=0,

            sticky="w",

            pady=(10, 0)

        )


        self.token_var = tk.StringVar(

            value="生成后显示"

        )


        token_entry = tk.Entry(

            setting_frame,

            textvariable=self.token_var,

            width=45,

            state="readonly"

        )

        token_entry.grid(

            row=1,

            column=1,

            columnspan=2,

            sticky="w",

            padx=10,

            pady=(10, 0)

        )


        # ====================================================
        # 公网 URL
        # ====================================================

        url_frame = tk.LabelFrame(

            self.root,

            text="③ 公网 URL",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=10,

            pady=10

        )

        url_frame.pack(

            fill="x",

            padx=25,

            pady=5

        )


        self.public_url_var = tk.StringVar(

            value="等待生成..."

        )


        url_entry = tk.Entry(

            url_frame,

            textvariable=self.public_url_var,

            font=(
                "Segoe UI",
                10
            ),

            state="readonly"

        )

        url_entry.pack(

            side="left",

            fill="x",

            expand=True,

            padx=(0, 10)

        )


        tk.Button(

            url_frame,

            text="📋 复制",

            width=10,

            command=self.copy_url

        ).pack(
            side="right"
        )


        # ====================================================
        # 按钮
        # ====================================================

        button_frame = tk.Frame(

            self.root

        )

        button_frame.pack(

            pady=20

        )


        self.start_button = tk.Button(

            button_frame,

            text="🚀 生成安全 URL",

            width=20,

            height=2,

            font=(
                "Segoe UI",
                11,
                "bold"
            ),

            command=self.start_server

        )

        self.start_button.grid(

            row=0,

            column=0,

            padx=8

        )


        self.stop_button = tk.Button(

            button_frame,

            text="⛔ 撤销 / 停止",

            width=20,

            height=2,

            font=(
                "Segoe UI",
                11
            ),

            command=self.stop_server,

            state="disabled"

        )

        self.stop_button.grid(

            row=0,

            column=1,

            padx=8

        )


        self.open_button = tk.Button(

            button_frame,

            text="🌐 打开视频",

            width=20,

            height=2,

            font=(
                "Segoe UI",
                11
            ),

            command=self.open_url

        )

        self.open_button.grid(

            row=0,

            column=2,

            padx=8

        )


        # ====================================================
        # 状态
        # ====================================================

        status_frame = tk.Frame(

            self.root

        )

        status_frame.pack(

            fill="x",

            padx=30

        )


        tk.Label(

            status_frame,

            text="状态：",

            font=(
                "Segoe UI",
                10,
                "bold"
            )

        ).pack(

            side="left"

        )


        self.status_var = tk.StringVar(

            value="● 未启动"

        )


        tk.Label(

            status_frame,

            textvariable=self.status_var,

            font=(
                "Segoe UI",
                10
            )

        ).pack(

            side="left"

        )


        # ====================================================
        # 日志
        # ====================================================

        log_frame = tk.LabelFrame(

            self.root,

            text="运行日志",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=5,

            pady=5

        )

        log_frame.pack(

            fill="both",

            expand=True,

            padx=25,

            pady=(10, 20)

        )


        self.log_text = tk.Text(

            log_frame,

            height=9,

            font=(
                "Consolas",
                9
            ),

            state="disabled"

        )

        self.log_text.pack(

            fill="both",

            expand=True

        )


    # ========================================================
    # 日志
    # ========================================================

    def log(self, message):

        def write():

            self.log_text.config(
                state="normal"
            )

            self.log_text.insert(
                "end",
                message + "\n"
            )

            self.log_text.see(
                "end"
            )

            self.log_text.config(
                state="disabled"
            )


        self.root.after(
            0,
            write
        )


    # ========================================================
    # 选择视频
    # ========================================================

    def select_video(self):

        file_path = filedialog.askopenfilename(

            title="选择视频",

            filetypes=[

                (
                    "视频文件",

                    "*.mp4 "
                    "*.webm "
                    "*.mov "
                    "*.mkv "
                    "*.avi "
                    "*.wmv "
                    "*.flv "
                    "*.m4v "
                    "*.mpeg "
                    "*.mpg"

                ),

                (
                    "所有文件",
                    "*.*"
                )

            ]

        )


        if file_path:

            self.file_var.set(
                file_path
            )

            self.log(
                "选择视频："
                + file_path
            )


    # ========================================================
    # 获取有效期
    # ========================================================

    def get_expire_seconds(self):

        values = {

            "5 分钟": 5 * 60,

            "10 分钟": 10 * 60,

            "30 分钟": 30 * 60,

            "1 小时": 60 * 60,

            "3 小时": 3 * 60 * 60,

            "6 小时": 6 * 60 * 60,

            "12 小时": 12 * 60 * 60,

            "24 小时": 24 * 60 * 60,

        }

        return values[
            self.expire_var.get()
        ]


    # ========================================================
    # 启动 Flask
    # ========================================================

    def start_flask(self):

        self.flask_thread = threading.Thread(

            target=run_flask,

            daemon=True

        )

        self.flask_thread.start()


    # ========================================================
    # 启动服务器
    # ========================================================

    def start_server(self):

        global VIDEO_FILE
        global VIDEO_TOKEN
        global LINK_CREATED_TIME
        global LINK_EXPIRE_SECONDS
        global LINK_REVOKED


        if self.server_running:

            messagebox.showinfo(

                "提示",

                "服务器已经在运行。"

            )

            return


        video = self.file_var.get().strip()


        if not video:

            messagebox.showerror(

                "错误",

                "请先选择视频文件。"

            )

            return


        if not os.path.isfile(video):

            messagebox.showerror(

                "错误",

                "视频文件不存在。"

            )

            return


        # 设置视频

        VIDEO_FILE = os.path.abspath(
            video
        )


        # 新 Token

        VIDEO_TOKEN = generate_token(
            32
        )


        # 有效时间

        LINK_EXPIRE_SECONDS = (
            self.get_expire_seconds()
        )


        LINK_CREATED_TIME = time.time()

        LINK_REVOKED = False


        self.expire_seconds = (
            LINK_EXPIRE_SECONDS
        )


        self.token_var.set(
            VIDEO_TOKEN
        )


        self.public_url_var.set(
            "正在启动 Cloudflare..."
        )


        self.log(
            "================================"
        )

        self.log(
            "启动安全视频服务器"
        )

        self.log(
            "视频："
            + VIDEO_FILE
        )

        self.log(
            "Token："
            + VIDEO_TOKEN
        )

        self.log(
            "有效期："
            + self.expire_var.get()
        )


        self.start_button.config(
            state="disabled"
        )

        self.stop_button.config(
            state="normal"
        )


        self.server_running = True


        self.status_var.set(
            "● 正在启动本地服务器..."
        )


        self.start_flask()


        # 给 Flask 一点启动时间

        self.root.after(

            1200,

            self.start_cloudflare

        )


    # ========================================================
    # 启动 Cloudflare
    # ========================================================

    def start_cloudflare(self):

        if not self.server_running:

            return


        if not os.path.isfile(
            CLOUDFLARED_PATH
        ):

            self.log(
                "找不到："
                + CLOUDFLARED_PATH
            )


            self.status_var.set(
                "● 找不到 cloudflared.exe"
            )


            messagebox.showerror(

                "缺少 cloudflared.exe",

                "请把 cloudflared.exe 放到：\n\n"

                + BASE_DIR

                + "\n\n"

                "然后重新启动软件。"

            )


            self.stop_server()

            return


        self.log(
            "正在启动 Cloudflare Quick Tunnel..."
        )


        self.status_var.set(
            "● 正在建立公网连接..."
        )


        try:

            self.cloudflare_process = (
                subprocess.Popen(

                    [

                        CLOUDFLARED_PATH,

                        "tunnel",

                        "--url",

                        f"http://{HOST}:{PORT}"

                    ],

                    stdout=subprocess.PIPE,

                    stderr=subprocess.STDOUT,

                    stdin=subprocess.DEVNULL,

                    text=True,

                    encoding="utf-8",

                    errors="replace",

                    bufsize=1,

                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0
                    )

                )
            )


        except Exception as e:

            self.log(
                "Cloudflare 启动失败："
                + str(e)
            )


            messagebox.showerror(

                "启动失败",

                str(e)

            )


            self.stop_server()

            return


        self.tunnel_running = True


        threading.Thread(

            target=self.read_cloudflare,

            daemon=True

        ).start()


    # ========================================================
    # 读取 Cloudflare
    # ========================================================

    def read_cloudflare(self):

        process = self.cloudflare_process


        if not process:

            return


        try:

            for line in process.stdout:

                line = line.strip()


                if not line:

                    continue


                self.log(
                    "[Cloudflare] "
                    + line
                )

                match = re.search(
                    r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",
                
                    line

                )

                if match:

                    base_url = (
                        match.group(0)
                    )


                    public_url = (

                        base_url

                        + "/v/"

                        + VIDEO_TOKEN

                    )


                    self.root.after(

                        0,

                        lambda url=public_url:
                        self.tunnel_ready(url)

                    )


        except Exception as e:

            self.log(
                "Cloudflare 输出读取失败："
                + str(e)
            )


    # ========================================================
    # Tunnel 成功
    # ========================================================

    def tunnel_ready(self, url):

        if not self.server_running:

            return


        self.public_url = url


        self.public_url_var.set(
            url
        )


        self.status_var.set(
            "● 安全公网 URL 已生成"
        )


        self.log(
            "================================"
        )

        self.log(
            "公网 URL："
            + url
        )

        self.log(
            "链接已自动复制。"
        )

        self.log(
            "================================"
        )


        # 自动复制

        self.root.clipboard_clear()

        self.root.clipboard_append(
            url
        )

        self.root.update()


    # ========================================================
    # 复制
    # ========================================================

    def copy_url(self):

        if not self.public_url:

            messagebox.showwarning(

                "提示",

                "还没有生成公网 URL。"

            )

            return


        self.root.clipboard_clear()

        self.root.clipboard_append(
            self.public_url
        )

        self.root.update()


        self.log(
            "公网 URL 已复制。"
        )


    # ========================================================
    # 打开
    # ========================================================

    def open_url(self):

        if not self.public_url:

            messagebox.showwarning(

                "提示",

                "还没有生成公网 URL。"

            )

            return


        webbrowser.open(
            self.public_url
        )


    # ========================================================
    # 停止 / 撤销
    # ========================================================

    def stop_server(self):

        global LINK_REVOKED


        LINK_REVOKED = True


        # 停止 Cloudflare

        if self.cloudflare_process:

            try:

                self.cloudflare_process.terminate()

                time.sleep(
                    0.5
                )


                if (
                    self.cloudflare_process.poll()
                    is None
                ):

                    self.cloudflare_process.kill()


            except Exception:
                pass


            self.cloudflare_process = None


        self.tunnel_running = False


        self.server_running = False


        self.public_url = ""


        self.public_url_var.set(
            "已撤销 / 已停止"
        )


        self.token_var.set(
            "已撤销"
        )


        self.status_var.set(
            "● 已停止"
        )


        self.start_button.config(
            state="normal"
        )


        self.stop_button.config(
            state="disabled"
        )


        self.log(
            "分享链接已撤销。"
        )


        self.log(
            "Cloudflare Tunnel 已停止。"
        )


    # ========================================================
    # 关闭
    # ========================================================

    def on_close(self):

        try:

            self.stop_server()

        except Exception:
            pass


        self.root.destroy()


# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()

    gui = VideoServerGUI(
        root
    )

    root.mainloop()
