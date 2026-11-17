"""真实 Cloudflare Quick Tunnel 冒烟测试（需要联网）。"""

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_v2 as slvs  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def main():
    tmp = tempfile.mkdtemp(prefix="slvs-tunnel-")
    video = os.path.join(tmp, "demo.mp4")
    with open(video, "wb") as handle:
        handle.write(os.urandom(2 * 1024 * 1024 + 7))

    slvs.STATE.start(video, 300)

    server = make_server("127.0.0.1", 0, slvs.app, threaded=True)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port
    local = f"http://127.0.0.1:{port}/v/{slvs.STATE.link_token}"
    slvs.STATE.set_local_url(local)

    proc = subprocess.Popen(
        [slvs.CLOUDFLARED_PATH, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    base = None
    deadline = time.time() + 60
    try:
        for line in proc.stdout:
            print("cf>", line.strip()[:160])
            match = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
            if match:
                base = match.group(0)
                break
            if time.time() > deadline:
                break
        if not base:
            print("TUNNEL: FAILED (no url)")
            return 1

        public = base + "/v/" + slvs.STATE.link_token
        slvs.STATE.set_public_url(public)
        print("public:", public)

        # 页面（DNS 刚注册时可能要等几秒）
        last_error = None
        body = ""
        cookie = ""
        for attempt in range(8):
            try:
                req = urllib.request.Request(public,
                                             headers={"User-Agent": UA, "Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    cookie = resp.headers.get("Set-Cookie", "")
                    print("page:", resp.status, "cookie:", "yes" if cookie else "no")
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                print(f"page retry {attempt + 1}: {exc}")
                time.sleep(5)
        else:
            print("TUNNEL: FAILED", last_error)
            return 1

        start = body.index('var SRC = "') + len('var SRC = "')
        media_path = body[start:body.index('"', start)]
        media = base + media_path
        sid_cookie = cookie.split(";")[0]

        # 页面心跳（没有它媒体接口不给流）
        parts = media_path.strip("/").split("/")
        beat = urllib.request.Request(base + f"/h/{parts[1]}/{parts[2]}", data=b"",
                                      headers={"User-Agent": UA, "Cookie": sid_cookie})
        with urllib.request.urlopen(beat, timeout=30) as resp:
            print("heartbeat:", resp.status)

        req = urllib.request.Request(media, headers={
            "User-Agent": UA, "Cookie": sid_cookie,
            "Sec-Fetch-Dest": "video", "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin", "Referer": public,
            "Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            chunk = resp.read()
            print("range:", resp.status, len(chunk), resp.headers.get("Content-Range"))

        # 无 cookie
        req = urllib.request.Request(media, headers={
            "User-Agent": UA, "Sec-Fetch-Dest": "video", "Referer": public})
        try:
            urllib.request.urlopen(req, timeout=20)
            print("no-cookie: UNEXPECTED 200")
            return 1
        except urllib.error.HTTPError as exc:
            print("no-cookie:", exc.code)

        print("TUNNEL: OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
