"""Generate a server from a HAR, then talk to it over real MCP stdio against a live local API."""

import json

import anyio

from har2mcp.cli import main
from har2mcp.client import call_tool, list_tools

from conftest import TOKEN


def test_generated_server_has_no_secrets(har_file, tmp_path):
    out = tmp_path / "srv.py"
    assert main(["gen", str(har_file), "-o", str(out), "--name", "demo"]) == 0
    code = out.read_text()
    assert TOKEN not in code and "test-token-123" not in code
    assert "DEMO_AUTHORIZATION" in code
    assert (tmp_path / "demo.env.example").read_text() == "DEMO_AUTHORIZATION=\n"
    assert not (tmp_path / "demo.env").exists()


def test_end_to_end_over_mcp(har_file, tmp_path):
    out = tmp_path / "srv.py"
    assert main(["gen", str(har_file), "-o", str(out), "--name", "demo", "--save-secrets"]) == 0
    env = (tmp_path / "demo.env").read_text()
    assert f"DEMO_AUTHORIZATION={TOKEN}" in env

    tools = anyio.run(list_tools, out)
    names = {t["name"] for t in tools}
    assert {"get_user", "list_users", "search", "delete_user"} <= names

    got = anyio.run(call_tool, out, "get_user", {"user_id": 777})
    assert got["status"] == 200 and got["data"] == {"id": 777, "name": "user777"}

    got = anyio.run(call_tool, out, "list_users", {"page": 3})
    assert got["data"] == {"page": 3, "limit": 20}

    got = anyio.run(call_tool, out, "search", {"q": "agents"})
    assert got["data"] == {"echo": {"q": "agents", "size": 10}}


def test_missing_auth_gives_hint(har_file, tmp_path):
    out = tmp_path / "srv.py"
    main(["gen", str(har_file), "-o", str(out), "--name", "demo"])
    got = anyio.run(call_tool, out, "get_user", {"user_id": 1})
    assert got["status"] == 401 and "hint" in got


def test_inspect_and_config(har_file, tmp_path, capsys):
    assert main(["inspect", str(har_file), "--name", "demo"]) == 0
    text = capsys.readouterr().out
    assert "get_user" in text and "DEMO_AUTHORIZATION" in text
    srv = tmp_path / "demo_mcp_server.py"
    main(["gen", str(har_file), "-o", str(srv), "--name", "demo"])
    capsys.readouterr()
    assert main(["config", str(srv)]) == 0
    cfg = capsys.readouterr().out
    assert "claude mcp add demo" in cfg and '"mcpServers"' in cfg and "[mcp_servers.demo]" in cfg


def test_shortcut_and_errors(tmp_path, capsys):
    bad = tmp_path / "x.har"
    bad.write_text(json.dumps({"nope": 1}))
    assert main([str(bad)]) == 2
