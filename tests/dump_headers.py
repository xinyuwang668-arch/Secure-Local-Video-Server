"""临时脚本：起一个本地分享页，把 /s/ 请求的 Fetch Metadata 头打出来。

用法：python tests/dump_headers.py <video> [秒数]
然后用浏览器打开打印出来的 page，观察 stdout。
"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server_gui_v2 as slvs  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

video = sys.argv[1] if len(sys.argv) > 1 else ""
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 300
assert os.path.isfile(video), video


def log_headers():
    from flask import request

    if request.path.startswith("/s/") or request.path.startswith("/h/"):
        keys = (
            "User-Agent",
            "Sec-Fetch-Dest",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Site",
            "Sec-Fetch-User",
            "Referer",
            "Range",
            "Origin",
        )
        print(
            "REQ", request.path.split("/")[1],
            json.dumps({k: request.headers.get(k) for k in keys}, ensure_ascii=False),
            flush=True,
        )


slvs.app.before_request(log_headers)
slvs.STATE.start(video, seconds)
srv = make_server("127.0.0.1", 0, slvs.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}"
slvs.STATE.set_local_url(url)
print(json.dumps({
    "port": srv.server_port,
    "page": f"{url}/v/{slvs.STATE.link_token}",
}, ensure_ascii=False), flush=True)
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
