"""端到端：起本地 HTTP + quick tunnel，用本机/公共 DoH/第三方 API 三路验证域名是否可解析。"""

import http.server
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server_gui_v2 as slvs  # noqa: E402

MARK = b"SLVS-TUNNEL-OK"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = MARK + b" " + self.path.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D401
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print("local port:", port)

proc = subprocess.Popen(
    [slvs.CLOUDFLARED_PATH, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    text=True, encoding="utf-8", errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)

try:
    host = ""
    for line in proc.stdout:
        match = re.search(r"https://([a-zA-Z0-9.-]+\.trycloudflare\.com)", line)
        if match:
            host = match.group(1)
            break
    print("host:", host)
    time.sleep(8)

    try:
        print("local dns:", socket.getaddrinfo(host, 443)[0][4][0])
    except Exception as exc:  # noqa: BLE001
        print("local dns: FAILED", exc)

    for resolver in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        url = resolver + "?" + urllib.parse.urlencode({"name": host, "type": "A"})
        req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            print(f"doh {resolver.split('/')[2]}: status={data.get('Status')} "
                  f"{[a.get('data') for a in data.get('Answer', [])]}")
        except Exception as exc:  # noqa: BLE001
            print(f"doh {resolver.split('/')[2]}: error {exc}")

    for api in (f"https://api.hackertarget.com/dnslookup/?q={host}",
                f"https://api.hackertarget.com/httpheaders/?q=https://{host}/"):
        try:
            with urllib.request.urlopen(api, timeout=30) as resp:
                print(api.split("/")[3], "->", resp.read()[:400].decode("utf-8", "replace").replace("\n", " | "))
        except Exception as exc:  # noqa: BLE001
            print(api.split("/")[3], "-> error", exc)

    try:
        with urllib.request.urlopen(f"https://{host}/probe", timeout=30) as resp:
            print("fetch:", resp.status, resp.read()[:80])
    except Exception as exc:  # noqa: BLE001
        print("fetch:", "FAILED", exc)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
    httpd.shutdown()
