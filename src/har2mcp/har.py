"""Load a HAR file and keep only the requests that look like API calls."""

from __future__ import annotations

import base64
import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

STATIC_EXT = re.compile(
    r"\.(js|mjs|css|map|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|otf|eot|mp4|webm|mp3|wasm|html?)$",
    re.I,
)

# Hosts that are almost never the API you meant to capture.
NOISE_HOSTS = (
    "google-analytics.com", "googletagmanager.com", "doubleclick.net", "googlesyndication.com",
    "facebook.com", "facebook.net", "connect.facebook.net", "segment.io", "segment.com",
    "sentry.io", "hotjar.com", "mixpanel.com", "amplitude.com", "clarity.ms", "intercom.io",
    "fullstory.com", "newrelic.com", "nr-data.net", "datadoghq.com", "browser-intake-datadoghq.com",
    "cdn.jsdelivr.net", "unpkg.com", "cloudflareinsights.com", "posthog.com", "launchdarkly.com",
    "stripe.network", "recaptcha.net", "gstatic.com", "fonts.googleapis.com",
)
NOISE_HOST_PREFIX = ("telemetry.", "analytics.", "stats.", "metrics.", "events.", "log.", "logs.", "rum.")
NOISE_PATH = re.compile(
    r"/(collect|beacon|track|tracking|telemetry|metrics|log|logs|ping|isalive|health|healthz|heartbeat|rum|events?/batch)(/|$)",
    re.I,
)


@dataclass
class Sample:
    """One captured request/response pair."""

    method: str
    url: str
    scheme: str
    host: str
    path: str
    query: list[tuple[str, str]]
    headers: dict[str, str]
    body_kind: str | None  # "json" | "form" | "text" | None
    body: Any
    status: int
    response_mime: str
    response_json: Any = None
    started: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def base(self) -> str:
        return f"{self.scheme}://{self.host}"


def _decode_text(content: dict) -> str:
    text = content.get("text") or ""
    if content.get("encoding") == "base64" and text:
        try:
            text = base64.b64decode(text).decode("utf-8", "replace")
        except Exception:  # pragma: no cover - corrupt HAR
            return ""
    return text


def _parse_body(post: dict | None) -> tuple[str | None, Any]:
    if not post:
        return None, None
    text = post.get("text")
    mime = (post.get("mimeType") or "").lower()
    if text:
        stripped = text.strip()
        # Many sites send JSON with a form or text/plain mime type, so sniff first.
        if stripped[:1] in "{[":
            try:
                return "json", json.loads(stripped)
            except ValueError:
                pass
        if "x-www-form-urlencoded" in mime:
            return "form", dict(parse_qsl(text, keep_blank_values=True))
        return "text", text
    params = post.get("params")
    if params:
        return "form", {p["name"]: p.get("value", "") for p in params}
    return None, None


def is_noise(host: str, path: str) -> bool:
    h = host.lower()
    if any(h == n or h.endswith("." + n) for n in NOISE_HOSTS):
        return True
    if h.startswith(NOISE_HOST_PREFIX):
        return True
    if STATIC_EXT.search(path):
        return True
    return bool(NOISE_PATH.search(path))


def load_har(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if "log" not in data or "entries" not in data["log"]:
        raise ValueError(f"{path} does not look like a HAR file (missing log.entries)")
    return data


def api_samples(
    har: dict,
    hosts: list[str] | None = None,
    exclude: list[str] | None = None,
    keep_noise: bool = False,
) -> list[Sample]:
    """Return captured requests that look like API calls (JSON in or out, or a write)."""
    out: list[Sample] = []
    for entry in har["log"]["entries"]:
        req, resp = entry.get("request", {}), entry.get("response", {})
        url = req.get("url", "")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            continue
        host, path = parts.hostname or "", parts.path or "/"
        if hosts and not any(fnmatch.fnmatch(host, pat) for pat in hosts):
            continue
        if exclude and any(fnmatch.fnmatch(host, p) or fnmatch.fnmatch(path, p) for p in exclude):
            continue
        if not keep_noise and is_noise(host, path):
            continue
        status = int(resp.get("status") or 0)
        if status == 0 or status >= 400 or 300 <= status < 400:
            continue
        method = req.get("method", "GET").upper()
        if method in ("OPTIONS", "HEAD", "CONNECT", "TRACE"):
            continue
        content = resp.get("content", {}) or {}
        mime = (content.get("mimeType") or "").lower()
        text = _decode_text(content)
        rjson = None
        if "json" in mime or text.strip()[:1] in ("{", "["):
            try:
                rjson = json.loads(text) if text else None
            except ValueError:
                rjson = None
        body_kind, body = _parse_body(req.get("postData"))
        looks_api = rjson is not None or "json" in mime or body_kind == "json"
        if not looks_api and method == "GET":
            continue
        if "html" in mime and method == "GET":
            continue
        headers = {h["name"].lower(): h.get("value", "") for h in req.get("headers", []) if not h["name"].startswith(":")}
        if "cookie" not in headers and req.get("cookies"):
            headers["cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in req["cookies"])
        out.append(
            Sample(
                method=method,
                url=url,
                scheme=parts.scheme,
                host=parts.netloc,
                path=path,
                query=parse_qsl(parts.query, keep_blank_values=True),
                headers=headers,
                body_kind=body_kind,
                body=body,
                status=status,
                response_mime=mime,
                response_json=rjson,
                started=entry.get("startedDateTime", ""),
            )
        )
    return out


def guess_site_name(har: dict, samples: list[Sample]) -> str:
    pages = har["log"].get("pages") or []
    for entry in har["log"]["entries"]:
        url = entry.get("request", {}).get("url", "")
        mime = (entry.get("response", {}).get("content", {}) or {}).get("mimeType", "")
        if "html" in (mime or ""):
            host = urlsplit(url).hostname or ""
            if host:
                return _host_to_name(host)
    if pages and pages[0].get("title", "").startswith("http"):
        return _host_to_name(urlsplit(pages[0]["title"]).hostname or "site")
    if samples:
        return _host_to_name(urlsplit(samples[0].url).hostname or "site")
    return "site"


def _host_to_name(host: str) -> str:
    parts = [p for p in host.lower().split(".") if p not in ("www", "api", "com", "net", "org", "io", "dev", "app", "co")]
    name = "_".join(parts) or host
    return re.sub(r"[^a-z0-9_]", "_", name)
