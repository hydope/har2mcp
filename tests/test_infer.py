from har2mcp.har import api_samples, is_noise
from har2mcp.infer import build_endpoints, is_id_segment, tool_name

from conftest import make_har


def eps():
    samples = api_samples(make_har("http://127.0.0.1:9"))
    return samples, {e.tool: e for e in build_endpoints(samples, "demo")}


def test_noise_is_filtered():
    samples, _ = eps()
    assert all("google-analytics" not in s.url and not s.path.endswith(".js") for s in samples)
    assert len(samples) == 7
    assert is_noise("telemetry.example.com", "/x")
    assert is_noise("example.com", "/api/collect")
    assert not is_noise("api.example.com", "/v1/users")


def test_id_segments():
    assert is_id_segment("12345")
    assert is_id_segment("3f2b8f0e-1c2d-4e5f-9a8b-7c6d5e4f3a2b")
    assert is_id_segment("a1b2c3d4e5f6a7b8")
    assert not is_id_segment("1")  # /1/indexes style versions stay literal
    assert not is_id_segment("users")


def test_path_templating_and_names():
    _, by = eps()
    assert set(by) == {"get_user", "list_users", "search", "delete_user"}
    assert by["get_user"].template == "/api/v1/users/{user_id}"
    assert by["get_user"].params[0].type == "int"
    assert by["get_user"].count == 2


def test_varying_params_required_constants_default():
    _, by = eps()
    lu = {p.wire: p for p in by["list_users"].params}
    assert lu["page"].required and lu["page"].type == "int"
    assert lu["limit"].required is False and lu["limit"].default == 20
    s = {p.wire: p for p in by["search"].params}
    assert s["q"].required and s["q"].type == "str"
    assert not s["size"].required and s["size"].default == 10


def test_auth_detected_not_hardcoded():
    _, by = eps()
    a = by["get_user"].auth
    assert [(x.wire, x.where, x.env) for x in a] == [("authorization", "header", "DEMO_AUTHORIZATION")]
    assert "authorization" not in by["get_user"].headers
    assert "user-agent" not in by["get_user"].headers


def test_tool_name_rules():
    assert tool_name("GET", "/api/v2/orders", False) == "list_orders"
    assert tool_name("GET", "/api/v2/orders/{order_id}", True) == "get_order"
    assert tool_name("POST", "/api/v2/orders", False) == "create_order"
    assert tool_name("PATCH", "/api/v2/orders/{order_id}", True) == "update_order"
    assert tool_name("POST", "/1/indexes/Item_dev/query", False) == "query_item_dev"
