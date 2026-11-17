"""检查 trycloudflare 域名在隧道存活期间能否解析（DoH）。"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server_gui_v2 as slvs  # noqa: E402

proc = subprocess.Popen(
    [slvs.CLOUDFLARED_PATH, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:9"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    text=True, encoding="utf-8", errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)

host = None
try:
    for line in proc.stdout:
        match = re.search(r"https://([a-zA-Z0-9.-]+\.trycloudflare\.com)", line)
        if match:
            host = match.group(1)
            break
    print("host:", host)
    for attempt in range(5):
        for resolver in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
            url = resolver + "?" + urllib.parse.urlencode({"name": host, "type": "A"})
            req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                answers = [a.get("data") for a in data.get("Answer", [])]
                print(f"{resolver} status={data.get('Status')} {answers}")
            except Exception as exc:  # noqa: BLE001
                print(f"{resolver} error {exc}")
        time.sleep(3)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
