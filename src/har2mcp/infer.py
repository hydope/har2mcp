"""Turn raw samples into endpoint specs: path templates, typed params, auth, tool names."""

from __future__ import annotations

import keyword
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .har import Sample

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HEX = re.compile(r"^[0-9a-f]{12,}$", re.I)
NUM = re.compile(r"^\d+$")
SLUGID = re.compile(r"^(?=.*\d)(?=.*[a-z])[A-Za-z0-9_-]{16,}$")
EMAIL = re.compile(r"^[^@/]+@[^@/]+\.[a-z]{2,}$", re.I)

AUTH_HEADER = re.compile(r"^(authorization|cookie|proxy-authorization|x-.*(token|auth|key|secret|session|csrf|xsrf|signature).*)$", re.I)
AUTH_PARAM = re.compile(r"(^|[-_.])(api[-_]?key|apikey|key|token|access[-_]?token|auth|secret|signature|sig|session|sessionid)$", re.I)
# Browser/transport headers we never replay.
DROP_HEADERS = {
    "host", "content-length", "connection", "accept-encoding", "user-agent", "cache-control", "pragma",
    "te", "upgrade-insecure-requests", "priority", "if-none-match", "if-modified-since", "dnt",
    "accept-language",
}
KEEP_HEADERS = {"accept", "content-type", "origin", "referer", "x-requested-with"}
SEARCH_KEYS = {"q", "query", "search", "term", "text", "keyword", "keywords", "prompt", "input"}
ACTION_WORDS = {
    "search", "query", "login", "logout", "lookup", "find", "send", "submit", "export", "import",
    "upload", "download", "publish", "archive", "like", "follow", "subscribe", "graphql", "batch",
    "autocomplete", "suggest", "complete", "run", "execute", "start", "stop", "cancel",
}
VERSIONISH = re.compile(r"^(api|v\d+(\.\d+)?|\d|rest|json|public|internal|_api|ajax)$", re.I)
MAX_EXPOSED = 12
# Client/SDK bookkeeping params that an agent never needs to set.
CLIENT_NOISE = re.compile(r"(^|[-_])(agent|sdk|client|version|v|_|cb|callback|ts|timestamp|nonce|rnd|cachebust|application[-_]?id|app[-_]?id)$", re.I)


@dataclass
class Param:
    name: str  # python identifier
    wire: str  # name on the wire
    where: str  # "path" | "query" | "body"
    type: str  # python type annotation
    required: bool
    default: Any = None
    examples: list = field(default_factory=list)


@dataclass
class AuthField:
    env: str
    wire: str
    where: str  # "header" | "query"


@dataclass
class Endpoint:
    method: str
    base: str
    template: str  # /users/{user_id}
    tool: str
    params: list[Param]
    fixed_query: dict
    fixed_body: dict | None
    body_kind: str | None
    headers: dict
    auth: list[AuthField]
    count: int
    response_shape: str
    raw_body_text: str | None = None

    @property
    def exposed(self) -> list[Param]:
        return [p for p in self.params]


def is_id_segment(seg: str) -> bool:
    return bool(
        UUID.match(seg)
        or (NUM.match(seg) and len(seg) >= 3)
        or HEX.match(seg) and any(c.isdigit() for c in seg)
        or SLUGID.match(seg)
        or EMAIL.match(seg)
    )


def singular(word: str) -> str:
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def ident(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower() or "param"
    if s[0].isdigit():
        s = "p_" + s
    if keyword.iskeyword(s) or s in {"self", "json", "os", "mcp"}:
        s += "_"
    return s


def py_type(values: list) -> str:
    kinds = set()
    for v in values:
        if isinstance(v, bool):
            kinds.add("bool")
        elif isinstance(v, int):
            kinds.add("int")
        elif isinstance(v, float):
            kinds.add("float")
        elif isinstance(v, list):
            kinds.add("list")
        elif isinstance(v, dict):
            kinds.add("dict")
        elif v is None:
            continue
        else:
            kinds.add("str")
    if kinds == {"int", "float"}:
        return "float"
    if len(kinds) == 1:
        return kinds.pop()
    return "str" if not kinds else "Any"


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s != ""]


def template_paths(samples: list[Sample]) -> dict[int, tuple[str, list[tuple[str, int]]]]:
    """Return {sample_index: (template, [(param_name, segment_index)])}."""
    shapes: dict[int, list[str | None]] = {}
    for i, s in enumerate(samples):
        segs = _segments(s.path)
        shapes[i] = [None if is_id_segment(seg) else seg for seg in segs]

    # Second pass: merge paths that differ only in one segment where every value is numeric.
    by_key: dict[tuple, list[int]] = {}
    for i, s in enumerate(samples):
        by_key.setdefault((s.method, s.host, len(shapes[i])), []).append(i)
    for idxs in by_key.values():
        if len(idxs) < 2:
            continue
        n = len(shapes[idxs[0]])
        for pos in range(n):
            vals = {shapes[i][pos] for i in idxs}
            if len(vals) < 2 or not all(v is not None and NUM.match(v) for v in vals):
                continue
            # The rest of the shape must match for the merge to make sense.
            rest = {tuple(x for k, x in enumerate(shapes[i]) if k != pos) for i in idxs}
            if len(rest) == 1:
                for i in idxs:
                    shapes[i][pos] = None

    result = {}
    for i, s in enumerate(samples):
        segs = _segments(s.path)
        names: list[tuple[str, int]] = []
        out = []
        used: Counter = Counter()
        for k, seg in enumerate(shapes[i]):
            if seg is None:
                prev = next((shapes[i][j] for j in range(k - 1, -1, -1) if shapes[i][j]), None)
                base = f"{singular(prev)}_id" if prev and not VERSIONISH.match(prev) else "id"
                base = ident(base)
                used[base] += 1
                name = base if used[base] == 1 else f"{base}_{used[base]}"
                names.append((name, k))
                out.append("{" + name + "}")
            else:
                out.append(seg)
        result[i] = ("/" + "/".join(out) + ("/" if s.path.endswith("/") and len(segs) else ""), names)
    return result


def tool_name(method: str, template: str, has_trailing_param: bool) -> str:
    segs = [s for s in _segments(template) if not s.startswith("{") and not VERSIONISH.match(s)]
    words = [ident(s) for s in segs][-2:]
    last = segs[-1].lower() if segs else ""
    if last in ACTION_WORDS or (segs and ident(last) in ACTION_WORDS):
        stem = "_".join(reversed(words)) if len(words) == 2 else (words[0] if words else "call")
        return ident(stem)
    noun = words[-1] if words else "root"
    lead = words[-2] + "_" if len(words) == 2 and method != "GET" else ""
    if method == "GET":
        verb = "get" if has_trailing_param else "list"
        n = singular(noun) if has_trailing_param else noun
        return ident(f"{verb}_{n}")
    verb = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}.get(method, method.lower())
    if method == "POST" and has_trailing_param:
        verb = "post"
    target = singular(noun) if method in ("POST", "PUT", "PATCH", "DELETE") else noun
    return ident(f"{verb}_{lead}{target}") if lead and verb == "post" else ident(f"{verb}_{target}")


def shape(value: Any, depth: int = 0) -> str:
    if depth > 2:
        return "…"
    if isinstance(value, dict):
        keys = list(value.keys())
        parts = []
        for k in keys[:8]:
            v = value[k]
            if isinstance(v, (dict, list)) and depth < 2:
                parts.append(f"{k}: {shape(v, depth + 1)}")
            else:
                parts.append(k)
        more = f", +{len(keys) - 8} more" if len(keys) > 8 else ""
        return "{" + ", ".join(parts) + more + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + shape(value[0], depth + 1) + ", …]"
    return type(value).__name__


def env_name(server: str, wire: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", f"{server}_{wire}".upper()).strip("_")


def build_endpoints(samples: list[Sample], server: str) -> list[Endpoint]:
    templated = template_paths(samples)
    groups: "OrderedDict[tuple, list[int]]" = OrderedDict()
    for i, s in enumerate(samples):
        groups.setdefault((s.method, s.base, templated[i][0]), []).append(i)

    endpoints: list[Endpoint] = []
    taken: Counter = Counter()
    for (method, base, template), idxs in groups.items():
        group = [samples[i] for i in idxs]
        path_names = templated[idxs[0]][1]
        params: list[Param] = []
        for name, pos in path_names:
            vals = [_segments(samples[i].path)[pos] for i in idxs]
            typ = "int" if all(NUM.match(v) for v in vals) else "str"
            params.append(Param(name, name, "path", typ, True, examples=_uniq(vals)))

        auth: list[AuthField] = []
        auth_seen: set = set()

        def add_auth(wire: str, where: str) -> None:
            if (wire, where) not in auth_seen:
                auth_seen.add((wire, where))
                auth.append(AuthField(env_name(server, wire), wire, where))

        # Query params
        fixed_query: dict = {}
        qvals: "OrderedDict[str, list]" = OrderedDict()
        for s in group:
            seen = set()
            for k, v in s.query:
                if k in seen:
                    continue
                seen.add(k)
                qvals.setdefault(k, []).append(v)
        for k, vals in qvals.items():
            if AUTH_PARAM.search(k):
                add_auth(k, "query")
                continue
            if CLIENT_NOISE.search(k) and len(set(vals)) == 1:
                fixed_query[k] = _coerce(vals[0])
                continue
            params.append(_param_from_values(k, "query", [_coerce(v) for v in vals], len(group)))

        # Body
        body_kind = next((s.body_kind for s in group if s.body_kind), None)
        fixed_body = None
        raw_body = None
        if body_kind in ("json", "form"):
            dict_bodies = [s.body for s in group if isinstance(s.body, dict)]
            if dict_bodies:
                bvals: "OrderedDict[str, list]" = OrderedDict()
                for b in dict_bodies:
                    for k, v in b.items():
                        bvals.setdefault(k, []).append(v if body_kind == "json" else _coerce(v))
                for k, vals in bvals.items():
                    if AUTH_PARAM.search(k) or k.lower() in ("password", "passwd", "csrf", "csrfmiddlewaretoken", "_token"):
                        # Never bake a secret from the body into code: make it a required param instead.
                        params.append(Param(ident(k), k, "body", "str", True, examples=[]))
                        continue
                    params.append(_param_from_values(k, "body", vals, len(dict_bodies)))
            else:  # top-level JSON array or scalar
                raw_body = None
                fixed_body = group[0].body
        elif body_kind == "text":
            raw_body = group[0].body

        # Headers
        headers: dict = {}
        for s in group:
            for k, v in s.headers.items():
                if k.startswith("sec-") or k in DROP_HEADERS:
                    continue
                if AUTH_HEADER.match(k):
                    add_auth(k, "header")
                    continue
                if k in KEEP_HEADERS or k.startswith("x-"):
                    headers.setdefault(k, v)

        params = _dedupe_names(_order(params))
        # Collapse long tails of optional constants into fixed defaults, so tool signatures stay readable.
        exposed, hidden = [], []
        for p in params:
            if p.required or len(exposed) < MAX_EXPOSED:
                exposed.append(p)
            else:
                hidden.append(p)
        for p in hidden:
            if p.where == "query":
                fixed_query[p.wire] = p.default
            elif p.where == "body":
                fixed_body = fixed_body or {}
                fixed_body[p.wire] = p.default

        has_trailing = bool(path_names) and path_names[-1][1] == len(_segments(template)) - 1
        name = tool_name(method, template, has_trailing)
        taken[name] += 1
        if taken[name] > 1:
            name = f"{name}_{taken[name]}"
        rsample = next((s.response_json for s in group if s.response_json is not None), None)
        endpoints.append(
            Endpoint(
                method=method,
                base=base,
                template=template,
                tool=name,
                params=exposed,
                fixed_query=fixed_query,
                fixed_body=fixed_body,
                body_kind=body_kind,
                headers=headers,
                auth=auth,
                count=len(group),
                response_shape=shape(rsample) if rsample is not None else "non-JSON response",
                raw_body_text=raw_body,
            )
        )
    return endpoints


def _uniq(vals: list) -> list:
    out = []
    for v in vals:
        if v not in out:
            out.append(v)
    return out[:3]


def _coerce(v: str) -> Any:
    if NUM.match(v) and (len(v) == 1 or not v.startswith("0")) and len(v) < 16:
        return int(v)
    if v in ("true", "false"):
        return v == "true"
    return v


def _param_from_values(wire: str, where: str, vals: list, n_samples: int) -> Param:
    distinct = _uniq([repr(v) for v in vals])
    varies = len(set(repr(v) for v in vals)) > 1
    search_like = wire.lower() in SEARCH_KEYS
    typ = py_type(vals)
    required = (varies or search_like) and len(vals) == n_samples
    default = None if required else vals[0]
    if typ in ("list", "dict") and not required:
        default = vals[0]
    p = Param(ident(wire), wire, where, typ, required, default, examples=[eval_safe(d) for d in distinct])
    return p


def eval_safe(r: str) -> Any:
    import ast

    try:
        return ast.literal_eval(r)
    except Exception:
        return r


def _order(params: list[Param]) -> list[Param]:
    def key(p: Param):
        tier = 0 if p.where == "path" else 1 if p.required else 2
        return (tier, 0 if p.wire.lower() in SEARCH_KEYS else 1, 0 if p.where == "body" else 1)

    return sorted(params, key=key)


def _dedupe_names(params: list[Param]) -> list[Param]:
    seen: Counter = Counter()
    for p in params:
        seen[p.name] += 1
        if seen[p.name] > 1:
            p.name = f"{p.name}_{p.where}"
    return params
