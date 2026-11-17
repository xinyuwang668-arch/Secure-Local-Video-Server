"""验证心跳硬闸：心跳一停，取流立刻被掐断。

运行：
    python tests\\check_heartbeat_cut.py
"""

import http.client
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_v2 as slvs  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

SIZE = 40 * 1024 * 1024


def main():
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    video = os.path.join(tmp.name, "big.mp4")
    with open(video, "wb") as handle:
        handle.write(os.urandom(SIZE))

    slvs.STATE.start(video, 600)
    server = slvs.make_server("127.0.0.1", 0, slvs.app, threaded=True)
    port = server.server_port
    local = f"http://127.0.0.1:{port}"
    slvs.STATE.set_local_url(local + "/v/" + slvs.STATE.link_token)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/v/" + slvs.STATE.link_token,
                 headers={"User-Agent": UA, "Accept": "text/html",
                          "Sec-Fetch-Mode": "navigate"})
    resp = conn.getresponse()
    body = resp.read().decode()
    cookie = resp.getheader("Set-Cookie", "").split(";")[0]
    conn.close()

    start = body.index('var SRC = "') + len('var SRC = "')
    media = body[start:body.index('"', start)]
    sid, ticket = media.strip("/").split("/")[1:3]

    def beat():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", f"/h/{sid}/{ticket}",
                  headers={"User-Agent": UA, "Cookie": cookie})
        r = c.getresponse()
        r.read()
        c.close()

    beat()
    print("[ok] 首次心跳")

    got = {"bytes": 0, "stopped": False, "elapsed": 0.0}

    def reader():
        begin = time.time()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request("GET", media, headers={
            "User-Agent": UA, "Cookie": cookie, "Sec-Fetch-Dest": "video",
            "Referer": local + "/v/" + slvs.STATE.link_token})
        r = c.getresponse()
        try:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                got["bytes"] += len(chunk)
        except Exception:  # noqa: BLE001
            pass
        got["stopped"] = True
        got["elapsed"] = time.time() - begin
        c.close()

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()

    # 只心跳 2 秒，然后彻底停掉
    time.sleep(2.0)
    print(f"[..] 停止心跳，已收到 {got['bytes']} 字节")
    worker.join(timeout=20)

    cut_ok = got["stopped"] and got["bytes"] < SIZE
    print(f"[{'PASS' if cut_ok else 'FAIL'}] 心跳停止后取流被掐断："
          f"{got['bytes']} / {SIZE} 字节，用时 {got['elapsed']:.1f}s")

    # 心跳恢复后可以重新开始
    beat()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", media, headers={
        "User-Agent": UA, "Cookie": cookie, "Sec-Fetch-Dest": "video",
        "Referer": local + "/v/" + slvs.STATE.link_token, "Range": "bytes=0-1023"})
    r = c.getresponse()
    r.read()
    print(f"[{'PASS' if r.status == 206 else 'FAIL'}] 心跳恢复后重新可取流 ({r.status})")
    c.close()

    server.shutdown()
    server.server_close()
    tmp.cleanup()
    return 0 if cut_ok and r.status == 206 else 1


if __name__ == "__main__":
    raise SystemExit(main())
