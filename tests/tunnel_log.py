"""抓取一次 quick tunnel 的完整日志，观察是否有注册/DNS 报错，并测试不同协议。"""

import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server_gui_v2 as slvs  # noqa: E402

for proto in ("quic", "http2"):
    print("=" * 20, proto)
    proc = subprocess.Popen(
        [slvs.CLOUDFLARED_PATH, "tunnel", "--no-autoupdate", "--protocol", proto,
         "--url", "http://127.0.0.1:9"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    time.sleep(25)
    proc.terminate()
    try:
        out = proc.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0]
    for line in out.splitlines():
        text = line.replace("\x1b", "")
        if any(key in text for key in ("ERR", "WRN", "Registered", "connection", "URL", "trycloudflare", "DNS", "dns")):
            print(text[:220])
