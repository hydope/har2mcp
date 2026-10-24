import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

TOKEN = "Bearer test-token-123"


def entry(method, url, status=200, mime="application/json", resp=None, headers=None, post=None):
    req = {
        "method": method,
        "url": url,
        "headers": [{"name": k, "value": v} for k, v in (headers or {}).items()],
        "cookies": [],
    }
    if post is not None:
        req["postData"] = {"mimeType": "application/json", "text": json.dumps(post)}
    return {
        "startedDateTime": "2026-10-23T12:00:00Z",
        "request": req,
        "response": {"status": status, "content": {"mimeType": mime, "text": json.dumps(resp) if resp is not None else ""}},
    }


def make_har(base):
    auth = {"Authorization": TOKEN, "Accept": "application/json", "User-Agent": "Mozilla/5.0", "sec-ch-ua": "x"}
    return {
        "log": {
            "version": "1.2",
            "pages": [],
            "entries": [
                entry("GET", f"{base}/", mime="text/html", resp=None),
                entry("GET", f"{base}/static/app.js", mime="application/javascript"),
                entry("POST", "https://www.google-analytics.com/g/collect?v=2", status=204, mime="text/plain"),
                entry("GET", f"{base}/api/v1/users/101", resp={"id": 101, "name": "Ada"}, headers=auth),
                entry("GET", f"{base}/api/v1/users/202", resp={"id": 202, "name": "Linus"}, headers=auth),
                entry("GET", f"{base}/api/v1/users?page=1&limit=20", resp={"users": [{"id": 101}]}, headers=auth),
                entry("GET", f"{base}/api/v1/users?page=2&limit=20", resp={"users": [{"id": 202}]}, headers=auth),
                entry("POST", f"{base}/api/v1/search", resp={"hits": [{"title": "mcp"}]}, headers=auth,
                      post={"q": "mcp", "size": 10}),
                entry("POST", f"{base}/api/v1/search", resp={"hits": []}, headers=auth, post={"q": "har", "size": 10}),
                entry("DELETE", f"{base}/api/v1/users/101", resp={"ok": True}, headers=auth),
            ],
        }
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if self.headers.get("authorization") != TOKEN:
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self._authed():
            return
        from urllib.parse import parse_qs, urlsplit

        parts = urlsplit(self.path)
        if parts.path.startswith("/api/v1/users/"):
            uid = int(parts.path.rsplit("/", 1)[1])
            return self._send(200, {"id": uid, "name": f"user{uid}"})
        if parts.path == "/api/v1/users":
            q = parse_qs(parts.query)
            return self._send(200, {"page": int(q.get("page", ["1"])[0]), "limit": int(q.get("limit", ["0"])[0])})
        self._send(404, {"error": "nope"})

    def do_POST(self):
        if not self._authed():
            return
        n = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        self._send(200, {"echo": body})

    def do_DELETE(self):
        if not self._authed():
            return
        self._send(200, {"deleted": self.path})


@pytest.fixture()
def api_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def har_file(tmp_path, api_server):
    p = tmp_path / "session.har"
    p.write_text(json.dumps(make_har(api_server)))
    return p
