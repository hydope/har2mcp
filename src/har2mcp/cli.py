"""Command line interface: `har2mcp session.har` and friends."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from . import __version__
from .codegen import auth_env_values, render_server
from .har import api_samples, guess_site_name, load_har
from .infer import build_endpoints, ident

COMMANDS = {"gen", "inspect", "call", "config", "record"}
RED, GREEN, DIM, BOLD, CYAN, YELLOW, RESET = "\033[31m", "\033[32m", "\033[2m", "\033[1m", "\033[36m", "\033[33m", "\033[0m"


def _c(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty() and not os.environ.get("FORCE_COLOR"):
        return text
    return f"{code}{text}{RESET}"


def _analyze(args):
    har = load_har(args.har)
    samples = api_samples(har, hosts=args.host or None, exclude=args.exclude or None, keep_noise=args.keep_noise)
    site = ident(args.name) if args.name else guess_site_name(har, samples)
    endpoints = build_endpoints(samples, site)
    return har, samples, site, endpoints


def cmd_inspect(args) -> int:
    _, samples, site, endpoints = _analyze(args)
    print(_c(BOLD, f"{site}: {len(samples)} API request(s) -> {len(endpoints)} tool(s)"))
    for ep in endpoints:
        req = [p.name for p in ep.params if p.required]
        opt = [p.name for p in ep.params if not p.required]
        print(f"  {_c(GREEN, ep.tool):<40} {ep.method:<6} {ep.base}{ep.template}  {_c(DIM, f'x{ep.count}')}")
        if req:
            print(f"      required: {', '.join(req)}")
        if opt:
            print(_c(DIM, f"      optional: {', '.join(opt)}"))
        if ep.auth:
            print(_c(YELLOW, "      auth: " + ", ".join(f"{a.wire} ({a.where}) -> ${a.env}" for a in ep.auth)))
    if not endpoints:
        print(_c(RED, "No API-looking requests found. Try --keep-noise, or capture with DevTools > Network > 'Save all as HAR with content'."))
        return 1
    return 0


def cmd_gen(args) -> int:
    har, samples, site, endpoints = _analyze(args)
    if not endpoints:
        print(_c(RED, "No API-looking requests found in the HAR; nothing to generate."), file=sys.stderr)
        return 1
    out = Path(args.output or f"{site}_mcp_server.py")
    code = render_server(endpoints, site, Path(args.har).name, out.name)
    compile(code, str(out), "exec")  # fail loudly rather than write a broken server
    out.write_text(code)
    out.chmod(0o755)
    env_path = out.with_name(f"{site}.env")
    example = out.with_name(f"{site}.env.example")
    envs = auth_env_values(endpoints, samples)
    names = sorted({a.env for ep in endpoints for a in ep.auth})
    if names:
        example.write_text("".join(f"{n}=\n" for n in names))
    if args.save_secrets and envs:
        env_path.write_text("# Captured from your HAR by har2mcp. Do NOT commit this file.\n" + "".join(f"{k}={v}\n" for k, v in envs.items()))
        env_path.chmod(0o600)
    print(_c(BOLD, f"✓ {out}") + f"  ({len(endpoints)} tools from {len(samples)} captured requests)")
    for ep in endpoints:
        print(f"   {_c(GREEN, ep.tool)}  {_c(DIM, ep.method + ' ' + ep.template)}")
    if names:
        where = env_path.name if args.save_secrets and envs else f"{example.name} (fill in, rename to {env_path.name})"
        print(_c(YELLOW, f"   auth: {', '.join(names)} -> {where}"))
    print(_c(DIM, f"   try it:  har2mcp call {out} {endpoints[0].tool}"))
    print(_c(DIM, f"   add it:  har2mcp config {out}"))
    return 0


def _server_cmd(server: Path) -> tuple[str, list[str]]:
    return sys.executable, [str(server.resolve())]


def cmd_config(args) -> int:
    server = Path(args.server)
    name = args.name or server.stem.replace("_mcp_server", "")
    exe, argv = _server_cmd(server)
    blocks = {
        "claude": f"claude mcp add {name} -- {shlex.quote(exe)} {' '.join(shlex.quote(a) for a in argv)}",
        "cursor": json.dumps({"mcpServers": {name: {"command": exe, "args": argv}}}, indent=2),
        "codex": f"[mcp_servers.{name}]\ncommand = {json.dumps(exe)}\nargs = {json.dumps(argv)}",
    }
    labels = {"claude": "Claude Code (run in your shell)", "cursor": "Cursor (~/.cursor/mcp.json)", "codex": "Codex (~/.codex/config.toml)"}
    for key in ([args.client] if args.client != "all" else ["claude", "cursor", "codex"]):
        print(_c(BOLD, f"# {labels[key]}"))
        print(blocks[key])
        print()
    return 0


def _parse_kv(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"argument {pair!r} must look like key=value")
        k, v = pair.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def cmd_call(args) -> int:
    import anyio

    from .client import call_tool, list_tools

    server = Path(args.server)
    if not args.tool:
        tools = anyio.run(list_tools, server)
        for t in tools:
            print(f"{_c(GREEN, t['name'])}  {_c(DIM, (t.get('description') or '').splitlines()[0])}")
        return 0
    arguments = _parse_kv(args.args)
    if args.json:
        arguments.update(json.loads(args.json))
    print(_c(DIM, f"→ {args.tool}({', '.join(f'{k}={v!r}' for k, v in arguments.items())})"), file=sys.stderr)
    result = anyio.run(call_tool, server, args.tool, arguments)
    if args.jq:
        result = _pluck(result, args.jq)
    print(json.dumps(result, indent=2, ensure_ascii=False)[: args.max_chars])
    return 0


def _pluck(obj, path: str):
    """Tiny dotted-path selector, e.g. data.hits[*].title"""
    cur = [obj]
    for part in path.split("."):
        nxt = []
        star = part.endswith("[*]")
        key = part[:-3] if star else part
        for c in cur:
            v = c.get(key) if isinstance(c, dict) else None
            if v is None:
                continue
            if star and isinstance(v, list):
                nxt.extend(v)
            else:
                nxt.append(v)
        cur = nxt
    return cur


def cmd_record(args) -> int:
    from .record import record

    return record(args.url, args.output, headless=args.headless, wait=args.wait)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="har2mcp",
        description="Turn a browser HAR capture into a working MCP server.",
        epilog="Shortcut: `har2mcp session.har` == `har2mcp gen session.har`.",
    )
    p.add_argument("--version", action="version", version=f"har2mcp {__version__}")
    sub = p.add_subparsers(dest="command")

    def common(sp):
        sp.add_argument("har", help="path to a .har file (DevTools > Network > Save all as HAR with content)")
        sp.add_argument("--name", help="server name (default: derived from the site)")
        sp.add_argument("--host", action="append", help="only keep these hosts (glob, repeatable), e.g. 'api.*'")
        sp.add_argument("--exclude", action="append", help="drop hosts or paths matching this glob (repeatable)")
        sp.add_argument("--keep-noise", action="store_true", help="keep analytics/telemetry/static requests")

    g = sub.add_parser("gen", help="generate an MCP server from a HAR (default)")
    common(g)
    g.add_argument("-o", "--output", help="output .py file (default: <site>_mcp_server.py)")
    g.add_argument("--save-secrets", action="store_true",
                   help="write captured auth values to <site>.env next to the server (chmod 600, never commit it)")
    g.set_defaults(func=cmd_gen)

    i = sub.add_parser("inspect", help="list the tools a HAR would produce, without writing anything")
    common(i)
    i.set_defaults(func=cmd_inspect)

    c = sub.add_parser("call", help="call a tool on a generated server (a tiny MCP client for testing)")
    c.add_argument("server")
    c.add_argument("tool", nargs="?")
    c.add_argument("args", nargs="*", help="key=value arguments (values parsed as JSON when possible)")
    c.add_argument("--json", help="arguments as a JSON object")
    c.add_argument("--jq", help="dotted path to print, e.g. data.hits[*].title")
    c.add_argument("--max-chars", type=int, default=4000)
    c.set_defaults(func=cmd_call)

    k = sub.add_parser("config", help="print Claude Code / Cursor / Codex config for a generated server")
    k.add_argument("server")
    k.add_argument("--name")
    k.add_argument("--client", choices=["claude", "cursor", "codex", "all"], default="all")
    k.set_defaults(func=cmd_config)

    r = sub.add_parser("record", help="open a browser, click around, save a HAR (needs `pip install har2mcp[record]`)")
    r.add_argument("url")
    r.add_argument("-o", "--output", default="session.har")
    r.add_argument("--headless", action="store_true", help="no window; just load the page and wait")
    r.add_argument("--wait", type=float, default=None, help="seconds to record before saving (default: until you press Enter)")
    r.set_defaults(func=cmd_record)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "gen")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as err:
        print(_c(RED, f"error: {err}"), file=sys.stderr)
        return 2
