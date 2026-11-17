"""本地实机验证：起一个真实分享页，供浏览器打开。

用法：python _live.py <视频路径> [过期秒数]
打印 JSON：{port, token, local_url, expires_in}
"""

import json
import sys
import threading
import time

sys.path.insert(0, r"D:\VideoServer")
import server_gui_v2 as s  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

path = sys.argv[1]
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 3600

s.STATE.start(path, seconds)
srv = make_server(s.HOST, 0, s.app, threaded=True)
port = srv.server_port
s.STATE.set_local_url(f"http://{s.HOST}:{port}")

print(json.dumps({
    "port": port,
    "token": s.STATE.link_token,
    "local_url": f"http://{s.HOST}:{port}",
    "page": f"http://{s.HOST}:{port}/v/{s.STATE.link_token}",
}), flush=True)

threading.Thread(target=srv.serve_forever, daemon=True).start()
while True:
    time.sleep(1)
