"""验证：媒体地址只接受浏览器媒体管道（Dest=video + Mode=no-cors + Site=same-origin）。

用法：python tests/check_download_block.py <base> <page>
"""

import http.cookiejar
import re
import sys
import urllib.request

base = sys.argv[1]
page = sys.argv[2]

UA = ("Mozilla/5.0 (Linux; Android 14; 23127PN0CC) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/157.0.0.0 Mobile Safari/537.36")

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

req = urllib.request.Request(page, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
with opener.open(req, timeout=10) as resp:
    body = resp.read().decode("utf-8", "replace")

m = re.search(r'/s/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)', body)
sid, ticket = m.group(1), m.group(2)
media = f"{base}/s/{sid}/{ticket}"
print("media:", media)

beat = urllib.request.Request(f"{base}/h/{sid}/{ticket}", data=b"",
                              headers={"User-Agent": UA})
with opener.open(beat, timeout=10) as r:
    print("heartbeat:", r.status)


def probe(label, extra):
    headers = {"User-Agent": UA, "Accept": "*/*", "Range": "bytes=0-1023"}
    headers.update(extra)
    try:
        with opener.open(urllib.request.Request(media, headers=headers), timeout=10) as r:
            print(f"{label}: {r.status} len={len(r.read())}")
    except urllib.error.HTTPError as exc:
        print(f"{label}: {exc.code}")


PIPE = {"Sec-Fetch-Dest": "video", "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin"}
probe("媒体管道 (video/no-cors/same-origin)", PIPE)
probe("脚本 fetch (empty/cors/same-origin)",
      {"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
       "Sec-Fetch-Site": "same-origin"})
probe("下载器   (empty/no-cors/same-origin)",
      {"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "no-cors",
       "Sec-Fetch-Site": "same-origin"})
probe("IDM 类   (无 Fetch 头)", {})
