"""SLVS v2.1.0 自动化测试。

运行：
    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_v2 as slvs  # noqa: E402


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CURL_UA = "curl/8.4.0"


def make_video(path, size=300_000):
    with open(path, "wb") as handle:
        handle.write(os.urandom(size))


class SLVSTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.video = os.path.join(self.tmp.name, "sample.mp4")
        make_video(self.video)
        slvs.STATE.start(self.video, 600)
        slvs.STATE.set_local_url(f"http://127.0.0.1:8000/v/{slvs.STATE.link_token}")
        self.client = slvs.app.test_client()

    def tearDown(self):
        slvs.STATE.reset()
        self.tmp.cleanup()

    # ---------------- 链接 ----------------

    def test_wrong_token_rejected(self):
        resp = self.client.get("/v/deadbeef", headers={"User-Agent": BROWSER_UA,
                                                       "Accept": "text/html"})
        self.assertEqual(resp.status_code, 410)

    def test_curl_agent_rejected(self):
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": CURL_UA, "Accept": "text/html"})
        self.assertEqual(resp.status_code, 403)

    def test_non_navigation_rejected(self):
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": BROWSER_UA,
                                        "Accept": "text/html",
                                        "Sec-Fetch-Mode": "cors"})
        self.assertEqual(resp.status_code, 403)

    def test_page_issued_with_cookie(self):
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": BROWSER_UA,
                                        "Accept": "text/html",
                                        "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("/s/", body)
        self.assertIn("slvs_sid", resp.headers.get("Set-Cookie", ""))
        self.assertIn("HttpOnly", resp.headers.get("Set-Cookie", ""))
        self.assertEqual(resp.headers.get("Cache-Control"),
                         "no-store, no-cache, must-revalidate, max-age=0")
        self.assertIn("noindex", resp.headers.get("X-Robots-Tag", ""))

    def test_expired_link(self):
        slvs.STATE.expires_at = time.time() - 1
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
        self.assertEqual(resp.status_code, 410)

    # ---------------- 媒体 ----------------

    def _open_page(self):
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": BROWSER_UA,
                                        "Accept": "text/html",
                                        "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        start = body.index('var SRC = "') + len('var SRC = "')
        end = body.index('"', start)
        url = body[start:end]
        self._beat(url)
        return url

    def _beat(self, url):
        parts = url.strip("/").split("/")
        sid, ticket = parts[1], parts[2]
        resp = self.client.post(f"/h/{sid}/{ticket}",
                                headers={"User-Agent": BROWSER_UA})
        self.assertEqual(resp.status_code, 204)
        return sid

    def _headers(self, **extra):
        headers = {"User-Agent": BROWSER_UA,
                   "Sec-Fetch-Dest": "video",
                   "Sec-Fetch-Mode": "no-cors",
                   "Sec-Fetch-Site": "same-origin",
                   "Referer": slvs.STATE.local_url}
        headers.update(extra)
        return headers

    def test_full_stream(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Length"], str(os.path.getsize(self.video)))
        self.assertEqual(resp.headers["Accept-Ranges"], "bytes")
        data = resp.get_data()
        resp.close()
        self.assertEqual(len(data), os.path.getsize(self.video))

    def test_range_request(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(Range="bytes=10-19"))
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.headers["Content-Range"],
                         f"bytes 10-19/{os.path.getsize(self.video)}")
        data = resp.get_data()
        resp.close()
        self.assertEqual(len(data), 10)

    def test_range_invalid(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(Range="bytes=999999999-"))
        self.assertEqual(resp.status_code, 416)

    def test_stream_without_cookie_rejected(self):
        url = self._open_page()
        other = slvs.app.test_client()
        resp = other.get(url, headers=self._headers())
        self.assertEqual(resp.status_code, 403)

    def test_stream_bad_ticket(self):
        url = self._open_page()
        broken = url.rsplit("/", 1)[0] + "/nope"
        resp = self.client.get(broken, headers=self._headers())
        self.assertEqual(resp.status_code, 403)

    def test_stream_bad_referer(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(Referer="https://evil.example/x"))
        self.assertEqual(resp.status_code, 403)

    def test_stream_without_fetch_headers(self):
        url = self._open_page()
        resp = self.client.get(url, headers={"User-Agent": BROWSER_UA})
        self.assertEqual(resp.status_code, 403)

    def test_stream_wrong_fetch_dest(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(**{"Sec-Fetch-Dest": "script"}))
        self.assertEqual(resp.status_code, 403)

    def test_stream_script_fetch_rejected(self):
        # 页面里的 JS 用 fetch 拉媒体：Dest 是 empty、Mode 是 cors。
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(
            **{"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"}))
        self.assertEqual(resp.status_code, 403)

    def test_stream_without_site_rejected(self):
        url = self._open_page()
        resp = self.client.get(url, headers=self._headers(**{"Sec-Fetch-Site": ""}))
        self.assertEqual(resp.status_code, 403)

    def test_ua_switch_rejected(self):
        url = self._open_page()
        other_ua = BROWSER_UA.replace("Chrome/126", "Firefox/127")
        resp = self.client.get(url, headers=self._headers(**{"User-Agent": other_ua}))
        self.assertEqual(resp.status_code, 403)

    def test_revoked_link(self):
        url = self._open_page()
        slvs.STATE.reset()
        resp = self.client.get(url, headers=self._headers())
        self.assertEqual(resp.status_code, 410)

    def test_home_hidden(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 404)

    def test_robots_disallow(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Disallow: /", resp.get_data(as_text=True))

    def test_stream_without_heartbeat_rejected(self):
        """页面不在（没有心跳）时，媒体地址一个字节都不给。"""
        url = self._open_page()
        for session in slvs.STATE.sessions.values():
            session["beat"] = 0.0
        resp = self.client.get(url, headers=self._headers())
        self.assertEqual(resp.status_code, 403)

    def test_token_not_in_page_html(self):
        """完整链接 Token 不应出现在页面 HTML 里（只出现在地址栏）。"""
        resp = self.client.get(f"/v/{slvs.STATE.link_token}",
                               headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
        self.assertNotIn(slvs.STATE.link_token, resp.get_data(as_text=True))


class SessionLimitTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.video = os.path.join(self.tmp.name, "a.mp4")
        make_video(self.video, 1024)
        slvs.STATE.start(self.video, 600)

    def tearDown(self):
        slvs.STATE.reset()
        self.tmp.cleanup()

    def test_session_cap(self):
        for _ in range(slvs.MAX_SESSIONS + 3):
            slvs.STATE.new_session(BROWSER_UA)
        self.assertLessEqual(len(slvs.STATE.sessions), slvs.MAX_SESSIONS)


class RangeParserTest(unittest.TestCase):

    def test_parse(self):
        self.assertEqual(slvs.parse_range("bytes=0-99", 1000), (0, 99))
        self.assertEqual(slvs.parse_range("bytes=900-", 1000), (900, 999))
        self.assertEqual(slvs.parse_range("bytes=-100", 1000), (900, 999))
        self.assertEqual(slvs.parse_range("", 1000), None)
        self.assertEqual(slvs.parse_range("bytes=abc", 1000), "invalid")
        self.assertEqual(slvs.parse_range("bytes=5000-", 1000), "invalid")
        self.assertEqual(slvs.parse_range("bytes=10-9999", 1000), (10, 999))


if __name__ == "__main__":
    unittest.main(verbosity=2)
