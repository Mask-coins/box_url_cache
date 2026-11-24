"""End-to-end tests: real local HTTP and real box_cache in isolated directories."""

from collections import Counter
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import box_cache
import requests

import box_url_cache


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = {}
        cls.hits = Counter()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.hits[self.path] += 1
                status, headers, body = cls.routes.get(self.path, (404, {}, b"missing"))
                if self.path == "/slow":
                    time.sleep(0.15)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                length = len(body) + (10 if self.path == "/broken" else 0)
                self.send_header("Content-Length", str(length))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # A timeout test can close its connection first.

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.routes.clear()
        self.hits.clear()
        work = Path(__file__).resolve().parents[1] / ".test-work"
        work.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        box_cache.configure(self.root / "cache")

    def url(self, path):
        return self.base + path

    def fetch(self, path, project="test", **options):
        options.setdefault("timeout", 2)
        return box_url_cache.get(project, self.url(path), **options)

    def test_json_response_round_trip_and_project_isolation(self):
        body = '{"message":"日本語"}'.encode()
        self.routes["/json"] = (200, {"Content-Type": "application/json; charset=utf-8"}, body)
        first = self.fetch("/json")
        cached = self.fetch("/json")
        for response in (first, cached):
            self.assertIs(type(response), requests.Response)
            self.assertEqual(response.content, body)
            self.assertEqual(response.json(), {"message": "日本語"})
            self.assertIn("日本語", response.text)
            self.assertEqual(response.headers["CONTENT-TYPE"],
                             "application/json; charset=utf-8")
            self.assertEqual(response.url, self.url("/json"))
            self.assertEqual(response.history, [])
        self.assertFalse(first.from_cache)
        self.assertTrue(cached.from_cache)
        self.assertEqual(first.fetched_at, cached.fetched_at)
        self.fetch("/json", project="other")
        self.assertEqual(self.hits["/json"], 2)

    def test_empty_and_gzip_bodies(self):
        for path, headers, wire, expected in (
            ("/empty", {}, b"", b""),
            ("/gzip", {"Content-Encoding": "gzip"}, gzip.compress(b"data"), b"data"),
        ):
            with self.subTest(path=path):
                self.routes[path] = (200, headers, wire)
                self.assertEqual(self.fetch(path).content, expected)
                self.assertEqual(self.fetch(path).content, expected)
                self.assertEqual(self.hits[path], 1)

    def test_error_saved_before_raise_and_read_only_reference(self):
        self.routes["/error"] = (404, {}, b"not found")
        with self.assertRaises(requests.HTTPError) as raised:
            self.fetch("/error")
        self.assertEqual(raised.exception.response.content, b"not found")
        record = box_url_cache.get_cached("test", self.url("/error"), statuses=(404,))
        self.assertEqual(record.status_code, 404)
        self.assertTrue(record.from_cache)
        self.assertIsNone(box_url_cache.get_cached("test", self.url("/error")))
        self.assertEqual(self.hits["/error"], 1)
        # Existing error evidence does not make the library skip a new attempt.
        with self.assertRaises(requests.HTTPError):
            self.fetch("/error")
        self.assertEqual(self.hits["/error"], 2)

    def test_accepted_status_order_and_refresh(self):
        self.routes["/status"] = (404, {}, b"old error")
        self.fetch("/status", accepted_statuses=(404,))
        self.routes["/status"] = (200, {}, b"success")
        self.fetch("/status", refresh=True)
        self.assertEqual(self.fetch("/status", accepted_statuses=(404, 200)).status_code, 404)
        self.assertEqual(self.fetch("/status", accepted_statuses=(200, 404)).status_code, 200)
        self.assertEqual(self.hits["/status"], 2)
        self.routes["/status"] = (500, {}, b"new error")
        with self.assertRaises(requests.HTTPError):
            self.fetch("/status", refresh=True)
        self.assertEqual(self.fetch("/status").content, b"success")

    def test_each_redirect_is_saved_under_its_own_url(self):
        self.routes.update({
            "/a": (301, {"Location": "/b"}, b"a moved"),
            "/b": (302, {"Location": "c"}, b"b moved"),
            "/c": (200, {}, b"final"),
        })
        network = self.fetch("/a")
        cached = self.fetch("/a")
        for response in (network, cached):
            self.assertEqual(response.url, self.url("/c"))
            self.assertEqual([r.status_code for r in response.history], [301, 302])
            self.assertEqual([r.url for r in response.history],
                             [self.url("/a"), self.url("/b")])
            self.assertEqual(response.content, b"final")
        self.assertTrue(all(r.from_cache for r in cached.history))
        self.assertEqual(self.hits, {"/a": 1, "/b": 1, "/c": 1})
        self.assertIsNone(box_cache.get_with_attributes("test_200", self.url("/a")))
        self.assertIsNone(box_cache.get_with_attributes("test_200", self.url("/b")))
        self.assertEqual(box_cache.get("test_301", self.url("/a")), b"a moved")
        self.assertEqual(box_cache.get("test_302", self.url("/b")), b"b moved")
        self.assertEqual(box_cache.get("test_200", self.url("/c")), b"final")
        # Explicit refresh ignores all cached hops.
        self.fetch("/a", refresh=True)
        self.assertEqual(self.hits, {"/a": 2, "/b": 2, "/c": 2})

    def test_cached_redirect_then_network_at_missing_destination(self):
        self.routes["/a"] = (307, {"Location": "/target"}, b"redirect")
        self.fetch("/a", accepted_statuses=(307,))
        self.routes["/target"] = (200, {}, b"new")
        response = self.fetch("/a")
        self.assertTrue(response.history[0].from_cache)
        self.assertFalse(response.from_cache)
        self.assertEqual(self.hits, {"/a": 1, "/target": 1})

    def test_accepted_redirect_is_returned_without_following(self):
        self.routes["/a"] = (301, {"Location": "/target"}, b"redirect")
        for _ in range(2):
            response = self.fetch("/a", accepted_statuses=(200, 301))
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.history, [])
        self.assertEqual(self.hits, {"/a": 1})

    def test_redirect_disabled_limit_and_loop(self):
        self.routes.update({
            "/a": (302, {"Location": "/b"}, b""),
            "/b": (302, {"Location": "/a"}, b""),
        })
        with self.assertRaises(requests.HTTPError):
            self.fetch("/a", allow_redirects=False)
        with self.assertRaises(requests.TooManyRedirects):
            self.fetch("/a", max_redirects=0)
        self.assertEqual(self.hits, {"/a": 1})
        with self.assertRaises(requests.TooManyRedirects) as raised:
            self.fetch("/a")
        self.assertEqual(raised.exception.response.url, self.url("/b"))
        error = box_url_cache.get_error("test", self.url("/b"), "TooManyRedirects")
        self.assertEqual(error["error_type"], "TooManyRedirects")
        self.assertEqual(self.hits, {"/a": 1, "/b": 1})

    def test_redirect_without_location_is_not_followed(self):
        self.routes["/a"] = (302, {}, b"no location")
        with self.assertRaises(requests.HTTPError):
            self.fetch("/a")
        self.assertEqual(box_url_cache.get_cached(
            "test", self.url("/a"), statuses=(302,)).content, b"no location")

    def test_cookies_are_not_forwarded(self):
        self.routes.update({
            "/a": (302, {"Location": "/b", "Set-Cookie": "session=secret"}, b""),
            "/b": (200, {}, b"done"),
        })
        response = self.fetch("/a")
        self.assertNotIn("Cookie", response.request.headers)

    def test_transport_error_record_and_original_exception(self):
        # Reserving (without listening on) a port makes connection refusal deterministic.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{reserved.getsockname()[1]}/"
            with self.assertRaises(requests.ConnectionError) as raised:
                box_url_cache.get("test", url, timeout=0.1)
        # Windows may report refusal as ConnectionError or ConnectTimeout.
        name = type(raised.exception).__name__
        error = box_url_cache.get_error("test", url, name)
        self.assertEqual(error["error_type"], name)
        self.assertIn("message", error)
        self.assertIn("occurred_at", error)
        self.assertIsNone(box_url_cache.get_error("test", url, "SSLError"))
        self.assertIsNone(box_url_cache.get_cached("test", url))

    def test_read_timeout_does_not_save_success(self):
        self.routes["/slow"] = (200, {}, b"late")
        with self.assertRaises(requests.exceptions.ReadTimeout):
            self.fetch("/slow", timeout=0.02)
        self.assertIsNotNone(box_url_cache.get_error("test", self.url("/slow"), "ReadTimeout"))
        self.assertIsNone(box_url_cache.get_cached("test", self.url("/slow")))

    def test_partial_body_is_an_error_and_not_a_success_cache(self):
        self.routes["/broken"] = (200, {}, b"incomplete")
        with self.assertRaises(requests.exceptions.ChunkedEncodingError):
            self.fetch("/broken")
        self.assertIsNone(box_url_cache.get_cached("test", self.url("/broken")))
        self.assertIsNotNone(box_url_cache.get_error(
            "test", self.url("/broken"), "ChunkedEncodingError"))

    def test_failed_destination_keeps_redirect_without_inventing_success(self):
        self.routes["/a"] = (302, {"Location": "/missing"}, b"redirect")
        with self.assertRaises(requests.HTTPError) as raised:
            self.fetch("/a")
        self.assertEqual(raised.exception.response.status_code, 404)
        self.assertEqual(len(raised.exception.response.history), 1)
        self.assertIsNotNone(box_url_cache.get_cached("test", self.url("/a"), statuses=(302,)))
        self.assertIsNone(box_url_cache.get_cached("test", self.url("/a")))
        self.assertIsNotNone(box_url_cache.get_cached(
            "test", self.url("/missing"), statuses=(404,)))

    def test_save_failure_never_returns_success(self):
        self.routes["/ok"] = (200, {}, b"ok")
        with patch("box_url_cache.client.box_cache.put", side_effect=box_cache.CacheError("disk")):
            with self.assertRaises(box_cache.CacheError):
                self.fetch("/ok")
        self.assertIsNone(box_url_cache.get_cached("test", self.url("/ok")))

    def test_http_and_transport_errors_survive_save_failure(self):
        self.routes["/error"] = (500, {}, b"server error")
        with patch("box_url_cache.client.box_cache.put", side_effect=box_cache.CacheError("disk")):
            with self.assertRaises(box_cache.CacheError) as raised:
                self.fetch("/error")
        self.assertIsInstance(raised.exception.__cause__, requests.HTTPError)
        self.assertEqual(raised.exception.__cause__.response.status_code, 500)
        with patch("requests.Session.get", side_effect=requests.ConnectionError("offline")):
            with patch("box_url_cache.client.box_cache.put", side_effect=box_cache.CacheError("disk")):
                with self.assertRaises(box_cache.CacheError) as raised:
                    self.fetch("/offline")
        self.assertIsInstance(raised.exception.__cause__, requests.ConnectionError)

    def test_read_failure_is_not_a_miss_and_bad_schema_is_not_repaired(self):
        with patch("box_url_cache.client.box_cache.get_with_attributes",
                   side_effect=box_cache.CacheError("config")):
            with self.assertRaises(box_cache.CacheError):
                self.fetch("/ok")
        self.assertFalse(self.hits)
        box_cache.put("test_200", self.url("/old"), b"old data")
        with self.assertRaises(ValueError):
            self.fetch("/old")
        self.assertFalse(self.hits)

    def test_invalid_arguments_do_not_send_requests(self):
        for statuses in ([], (), (True,), (99,), (600,)):
            with self.subTest(statuses=statuses), self.assertRaises((TypeError, ValueError)):
                self.fetch("/ok", accepted_statuses=statuses)
        for url in ("file:///tmp/x", "not a URL", "https://user:pass@example.com/"):
            with self.subTest(url=url), self.assertRaises(requests.exceptions.InvalidURL):
                box_url_cache.get("test", url)
        with self.assertRaises(ValueError):
            self.fetch("/ok", max_redirects=-1)
        self.assertFalse(self.hits)

    def test_no_timeout_by_default(self):
        response = requests.Response()
        response.status_code = 200
        response._content = b""
        response.url = self.url("/ok")
        with patch("requests.Session.get", return_value=response) as send:
            box_url_cache.get("test", self.url("/ok"))
        self.assertIsNone(send.call_args.kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
