"""真实 HTTP 冒烟测试：起本地服务 -> 走真实 socket -> 校验防下载策略。"""

import http.client
import os
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_v2 as slvs  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    tmp = tempfile.mkdtemp(prefix="slvs-smoke-")
    video = os.path.join(tmp, "demo.mp4")
    payload = os.urandom(3 * 1024 * 1024 + 123)
    with open(video, "wb") as handle:
        handle.write(payload)

    slvs.STATE.start(video, 300)

    port = free_port()
    server = make_server("127.0.0.1", port, slvs.app, threaded=True)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{port}/v/{slvs.STATE.link_token}"
    slvs.STATE.set_local_url(local)

    ok = True

    def check(label, condition, extra=""):
        nonlocal ok
        status = "PASS" if condition else "FAIL"
        if not condition:
            ok = False
        print(f"[{status}] {label} {extra}")

    # 1. 正常浏览器打开页面
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/v/{slvs.STATE.link_token}",
                 headers={"User-Agent": UA, "Accept": "text/html",
                          "Sec-Fetch-Mode": "navigate"})
    resp = conn.getresponse()
    body = resp.read().decode("utf-8", "replace")
    cookie = resp.getheader("Set-Cookie", "")
    check("页面 200", resp.status == 200, f"({resp.status})")
    check("页面含媒体地址", 'var SRC = "/s/' in body)
    check("下发 HttpOnly Cookie", "HttpOnly" in cookie)
    conn.close()

    sid_cookie = cookie.split(";")[0]
    start = body.index('var SRC = "') + len('var SRC = "')
    media_path = body[start:body.index('"', start)]

    def heartbeat(cookie_value, path):
        parts = path.strip("/").split("/")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", f"/h/{parts[1]}/{parts[2]}",
                  headers={"User-Agent": UA, "Cookie": cookie_value})
        r = c.getresponse()
        r.read()
        code = r.status
        c.close()
        return code

    # 2. 没有心跳的会话，媒体地址直接 403（硬闸）
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/v/{slvs.STATE.link_token}",
                 headers={"User-Agent": UA, "Accept": "text/html",
                          "Sec-Fetch-Mode": "navigate"})
    resp = conn.getresponse()
    resp.read()
    cold_cookie = resp.getheader("Set-Cookie", "").split(";")[0]
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", media_path, headers={
        "User-Agent": UA, "Cookie": cold_cookie, "Sec-Fetch-Dest": "video",
        "Referer": local})
    resp = conn.getresponse()
    resp.read()
    check("无心跳被拒", resp.status == 403, f"({resp.status})")
    conn.close()

    # 3. 页面心跳后再取流
    code = heartbeat(sid_cookie, media_path)
    check("心跳 204", code == 204, f"({code})")

    # 2. 正常播放：Range 请求
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", media_path, headers={
        "User-Agent": UA, "Cookie": sid_cookie, "Sec-Fetch-Dest": "video",
        "Referer": local, "Range": "bytes=1000-1999"})
    resp = conn.getresponse()
    chunk = resp.read()
    check("Range 206", resp.status == 206, f"({resp.status})")
    check("Range 内容正确", chunk == payload[1000:2000])
    check("Content-Range 正确",
          resp.getheader("Content-Range") == f"bytes 1000-1999/{len(payload)}")
    conn.close()

    # 3. 完整下载（模拟播放器从头读）
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("GET", media_path, headers={
        "User-Agent": UA, "Cookie": sid_cookie, "Sec-Fetch-Dest": "video",
        "Referer": local})
    resp = conn.getresponse()
    data = resp.read()
    check("完整流 200", resp.status == 200)
    check("完整流长度一致", len(data) == len(payload), f"({len(data)})")
    check("非 chunked", resp.getheader("Content-Length") == str(len(payload)))
    conn.close()

    # 4. curl 直接抓页面
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", f"/v/{slvs.STATE.link_token}",
                 headers={"User-Agent": "curl/8.4.0", "Accept": "text/html"})
    resp = conn.getresponse()
    resp.read()
    check("curl UA 被拒", resp.status == 403, f"({resp.status})")
    conn.close()

    # 5. 没有 Cookie 直连媒体
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", media_path, headers={
        "User-Agent": UA, "Sec-Fetch-Dest": "video", "Referer": local})
    resp = conn.getresponse()
    resp.read()
    check("无 Cookie 被拒", resp.status == 403, f"({resp.status})")
    conn.close()

    # 6. 过期后媒体立刻 410
    slvs.STATE.expires_at = time.time() - 1
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", media_path, headers={
        "User-Agent": UA, "Cookie": sid_cookie, "Sec-Fetch-Dest": "video",
        "Referer": local})
    resp = conn.getresponse()
    resp.read()
    check("过期后 410", resp.status == 410, f"({resp.status})")
    conn.close()

    server.shutdown()
    server.server_close()
    print("SMOKE:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
