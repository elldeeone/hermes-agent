import json
import socket
import subprocess
from urllib import error

import pytest

from tools import kaspa_tools
from tools.registry import registry
from toolsets import _HERMES_CORE_TOOLS, resolve_toolset


class FakeResponse:
    def __init__(self, status_code=200, body=b"{}"):
        self.status_code = status_code
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status_code

    def read(self):
        return self.body

    def close(self):
        pass


def _json(result):
    return json.loads(result)


def test_registry_entries_and_schemas_exist():
    kaspa_entry = registry.get_entry("kaspa_api_health")
    kasia_entry = registry.get_entry("kasia_indexer_health")

    assert kaspa_entry is not None
    assert kaspa_entry.toolset == "kaspa"
    assert kaspa_entry.schema["parameters"]["properties"]["url"]["type"] == "string"
    assert "timeout_seconds" in kaspa_entry.schema["parameters"]["properties"]

    assert kasia_entry is not None
    assert kasia_entry.toolset == "kaspa"
    assert kasia_entry.schema["parameters"]["properties"]["url"]["type"] == "string"
    assert "timeout_seconds" in kasia_entry.schema["parameters"]["properties"]

    node_info_entry = registry.get_entry("kaspa_node_info")
    assert node_info_entry is not None
    assert node_info_entry.toolset == "kaspa"
    node_info_properties = node_info_entry.schema["parameters"]["properties"]
    assert node_info_properties["host"]["type"] == "string"
    assert node_info_properties["port"]["type"] == "integer"
    assert node_info_properties["url"]["type"] == "string"
    assert node_info_properties["network"]["type"] == "string"
    assert node_info_properties["probe_command"]["type"] == "string"
    assert "timeout_seconds" in node_info_properties


def test_toolset_resolves_kaspa_tools():
    assert resolve_toolset("kaspa") == [
        "kasia_indexer_contextual_messages_by_sender",
        "kasia_indexer_handshakes_by_receiver",
        "kasia_indexer_handshakes_by_sender",
        "kasia_indexer_health",
        "kasia_indexer_payments_by_receiver",
        "kasia_indexer_payments_by_sender",
        "kasia_indexer_self_stash_by_owner",
        "kaspa_address_balance",
        "kaspa_address_name",
        "kaspa_address_transaction_count",
        "kaspa_address_transactions",
        "kaspa_address_utxo_count",
        "kaspa_address_utxos",
        "kaspa_api_health",
        "kaspa_block_lookup",
        "kaspa_blockdag_info",
        "kaspa_blockreward",
        "kaspa_coin_supply",
        "kaspa_fee_estimate",
        "kaspa_halving_info",
        "kaspa_hashrate",
        "kaspa_kaspad_info",
        "kaspa_marketcap",
        "kaspa_network_info",
        "kaspa_node_info",
        "kaspa_node_rpc_tcp_health",
        "kaspa_price",
        "kaspa_transaction_lookup",
        "kaspa_virtual_chain_blue_score",
        "kns_domain_owner",
        "kns_primary_name",
        "kns_search_assets",
    ]


def test_tools_are_not_in_core_tools():
    assert "kaspa_api_health" not in _HERMES_CORE_TOOLS
    assert "kaspa_block_lookup" not in _HERMES_CORE_TOOLS
    assert "kaspa_blockdag_info" not in _HERMES_CORE_TOOLS
    assert "kaspa_blockreward" not in _HERMES_CORE_TOOLS
    assert "kaspa_coin_supply" not in _HERMES_CORE_TOOLS
    assert "kaspa_fee_estimate" not in _HERMES_CORE_TOOLS
    assert "kaspa_hashrate" not in _HERMES_CORE_TOOLS
    assert "kaspa_halving_info" not in _HERMES_CORE_TOOLS
    assert "kaspa_kaspad_info" not in _HERMES_CORE_TOOLS
    assert "kaspa_marketcap" not in _HERMES_CORE_TOOLS
    assert "kaspa_network_info" not in _HERMES_CORE_TOOLS
    assert "kaspa_price" not in _HERMES_CORE_TOOLS
    assert "kaspa_virtual_chain_blue_score" not in _HERMES_CORE_TOOLS
    assert "kasia_indexer_health" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_balance" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_name" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_transaction_count" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_transactions" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_utxo_count" not in _HERMES_CORE_TOOLS
    assert "kaspa_address_utxos" not in _HERMES_CORE_TOOLS
    assert "kaspa_node_rpc_tcp_health" not in _HERMES_CORE_TOOLS
    assert "kaspa_node_info" not in _HERMES_CORE_TOOLS
    assert "kaspa_transaction_lookup" not in _HERMES_CORE_TOOLS
    assert "kns_search_assets" not in _HERMES_CORE_TOOLS
    assert "kns_domain_owner" not in _HERMES_CORE_TOOLS
    assert "kns_primary_name" not in _HERMES_CORE_TOOLS


def test_node_info_defaults_to_wrpc_websocket_port(monkeypatch):
    seen = {}

    def fake_run(command, *, input, text, capture_output, timeout, cwd):
        seen["input"] = json.loads(input)
        return subprocess.CompletedProcess(command, 0, stdout='{"network":"mainnet"}', stderr="")

    monkeypatch.delenv("KASPA_NODE_RPC_HOST", raising=False)
    monkeypatch.delenv("KASPA_NODE_RPC_PORT", raising=False)
    monkeypatch.delenv("KASPA_NODE_WRPC_PORT", raising=False)
    monkeypatch.delenv("KASPA_NODE_RPC_URL", raising=False)
    monkeypatch.setattr(kaspa_tools.subprocess, "run", fake_run)

    result = _json(kaspa_tools.kaspa_node_info({"probe_command": "node probe.mjs"}))

    assert result["ok"] is True
    assert result["host"] == "127.0.0.1"
    assert result["port"] == 17110
    assert result["endpoint"] == "ws://127.0.0.1:17110"
    assert seen["input"]["url"] == "ws://127.0.0.1:17110"


def test_kaspa_network_info_fetches_network(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"networkName":"mainnet","serverVersion":"1.0.0"}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_network_info({
        "url": "https://api.example",
        "timeout_seconds": 3,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/info/network",
        "status_code": 200,
        "network": {"networkName": "mainnet", "serverVersion": "1.0.0"},
    }
    assert seen == {"url": result["endpoint"], "timeout": 3}


def test_kaspa_blockdag_info_fetches_blockdag(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"networkName":"mainnet","blockCount":123}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_blockdag_info({
        "url": "https://api.example/",
        "timeout_seconds": 4,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/info/blockdag",
        "status_code": 200,
        "blockdag": {"networkName": "mainnet", "blockCount": 123},
    }
    assert seen == {"url": result["endpoint"], "timeout": 4}


def test_kaspa_coin_supply_fetches_supply(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"maxSupply":28700000000,"circulatingSupply":24000000000}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_coin_supply({
        "url": "https://api.example",
        "timeout_seconds": 5,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/info/coinsupply",
        "status_code": 200,
        "coin_supply": {"maxSupply": 28700000000, "circulatingSupply": 24000000000},
    }
    assert seen == {"url": result["endpoint"], "timeout": 5}


def test_kaspa_fee_estimate_fetches_fee_estimate(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"priorityBucket":{"feerate":1.0}}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_fee_estimate({
        "url": "https://api.example",
        "timeout_seconds": 6,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/info/fee-estimate",
        "status_code": 200,
        "fee_estimate": {"priorityBucket": {"feerate": 1.0}},
    }
    assert seen == {"url": result["endpoint"], "timeout": 6}


@pytest.mark.parametrize(
    ("tool_name", "path", "payload_key", "body", "payload"),
    [
        ("kaspa_price", "/info/price", "price", b'{"price":0.12}', {"price": 0.12}),
        ("kaspa_marketcap", "/info/marketcap", "marketcap", b'{"marketCap":3000000000}', {"marketCap": 3000000000}),
        ("kaspa_hashrate", "/info/hashrate", "hashrate", b'{"hashrate":123456}', {"hashrate": 123456}),
        ("kaspa_kaspad_info", "/info/kaspad", "kaspad", b'{"serverVersion":"1.2.3"}', {"serverVersion": "1.2.3"}),
        ("kaspa_blockreward", "/info/blockreward", "blockreward", b'{"blockreward":103.5}', {"blockreward": 103.5}),
        ("kaspa_halving_info", "/info/halving", "halving", b'{"nextHalvingTimestamp":123456789}', {"nextHalvingTimestamp": 123456789}),
        ("kaspa_virtual_chain_blue_score", "/info/virtual-chain-blue-score", "blue_score", b'{"blueScore":12345}', {"blueScore": 12345}),
    ],
)
def test_kaspa_readonly_info_scalar_tools_fetch_payloads(monkeypatch, tool_name, path, payload_key, body, payload):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, body)

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(getattr(kaspa_tools, tool_name)({
        "url": "https://api.example/",
        "timeout_seconds": 8,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": f"https://api.example{path}",
        "status_code": 200,
        payload_key: payload,
    }
    assert seen == {"url": result["endpoint"], "timeout": 8}


def test_node_info_invokes_readonly_probe_and_returns_normalized_payload(monkeypatch):
    seen = {}

    def fake_run(command, *, input, text, capture_output, timeout, cwd):
        seen["command"] = command
        seen["input"] = json.loads(input)
        seen["text"] = text
        seen["capture_output"] = capture_output
        seen["timeout"] = timeout
        seen["cwd"] = str(cwd)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "network": "mainnet",
                "is_synced": True,
                "server_version": "rusty-kaspa-1.1.0",
                "virtual_daa_score": 123456,
                "selected_tip_hash": "abc",
            }),
            stderr="",
        )

    monkeypatch.delenv("KASPA_NODE_INFO_PROBE_COMMAND", raising=False)
    monkeypatch.setattr(kaspa_tools.subprocess, "run", fake_run)

    result = _json(kaspa_tools.kaspa_node_info({
        "host": "10.0.3.20",
        "port": 16110,
        "network": "mainnet",
        "timeout_seconds": 3,
        "probe_command": "node ./scripts/kaspa-node-probe/node-info.mjs",
    }))

    assert result == {
        "ok": True,
        "host": "10.0.3.20",
        "port": 16110,
        "network": "mainnet",
        "timeout_seconds": 3,
        "endpoint": "ws://10.0.3.20:16110",
        "probe": "subprocess",
        "node_info": {
            "network": "mainnet",
            "is_synced": True,
            "server_version": "rusty-kaspa-1.1.0",
            "virtual_daa_score": 123456,
            "selected_tip_hash": "abc",
        },
    }
    assert seen["command"] == ["node", "./scripts/kaspa-node-probe/node-info.mjs"]
    assert seen["input"] == {
        "host": "10.0.3.20",
        "port": 16110,
        "network": "mainnet",
        "timeout_seconds": 3,
        "url": "ws://10.0.3.20:16110",
    }
    assert seen["text"] is True
    assert seen["capture_output"] is True
    assert seen["timeout"] == 5


def test_node_info_reports_probe_failures(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="connection refused")

    monkeypatch.setattr(kaspa_tools.subprocess, "run", fake_run)

    result = _json(kaspa_tools.kaspa_node_info({"probe_command": "node probe.mjs"}))

    assert result["ok"] is False
    assert "probe exited with status 2" in result["error"]
    assert result["stderr"] == "connection refused"
    assert result["host"] == "127.0.0.1"
    assert result["port"] == 17110


def test_node_rpc_tcp_health_uses_default_grpc_host_port(monkeypatch):
    seen = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_create_connection(address, timeout):
        seen["address"] = address
        seen["timeout"] = timeout
        return FakeSocket()

    monkeypatch.delenv("KASPA_NODE_RPC_HOST", raising=False)
    monkeypatch.delenv("KASPA_NODE_RPC_PORT", raising=False)
    monkeypatch.setattr(kaspa_tools.socket, "create_connection", fake_create_connection)

    result = _json(kaspa_tools.kaspa_node_rpc_tcp_health({}))

    assert result == {
        "ok": True,
        "host": "127.0.0.1",
        "port": 16110,
        "protocol_hint": "kaspad gRPC/wRPC TCP endpoint; this check verifies reachability only",
        "timeout_seconds": 10,
    }
    assert seen == {"address": ("127.0.0.1", 16110), "timeout": 10}


def test_node_rpc_tcp_health_reports_connection_error(monkeypatch):
    def fake_create_connection(address, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr(kaspa_tools.socket, "create_connection", fake_create_connection)

    result = _json(kaspa_tools.kaspa_node_rpc_tcp_health({
        "host": "10.0.4.30",
        "port": 16110,
        "timeout_seconds": 2,
    }))

    assert result["ok"] is False
    assert result["host"] == "10.0.4.30"
    assert result["port"] == 16110
    assert result["timeout_seconds"] == 2
    assert "timed out" in result["error"]


def test_default_url_behavior_with_env_cleared(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"healthy": true}')

    monkeypatch.delenv("KASPA_API_URL", raising=False)
    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_api_health({}))

    assert result["ok"] is True
    assert result["url"] == "https://api.kaspa.org"
    assert result["endpoint"] == "https://api.kaspa.org/info/health"
    assert result["health"] == {"healthy": True}
    assert seen == {"url": "https://api.kaspa.org/info/health", "timeout": 10}


def test_custom_url_trailing_slash_normalization(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse(200, b'{"status": "ok"}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_health({"url": "https://example.test///"}))

    assert result["ok"] is True
    assert result["url"] == "https://example.test"
    assert result["endpoint"] == "https://example.test/metrics"
    assert result["metrics"] == {"status": "ok"}
    assert seen["url"] == "https://example.test/metrics"


@pytest.mark.parametrize("url", ["", "ftp://example.test", "file:///tmp/x", "example.test"])
def test_normalize_base_url_rejects_invalid_url(url):
    with pytest.raises(ValueError, match="http:// or https://"):
        kaspa_tools._normalize_base_url(url)


@pytest.mark.parametrize("url", ["ftp://example.test", "file:///tmp/x", "example.test"])
def test_invalid_url_rejected(url):
    result = _json(kaspa_tools.kaspa_api_health({"url": url}))
    assert "error" in result
    assert "http:// or https://" in result["error"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 10),
        ("", 10),
        (0, 1),
        (-10, 1),
        (1, 1),
        (12.9, 12),
        ("30", 30),
        (300, 30),
    ],
)
def test_timeout_coerced_and_clamped(raw, expected):
    assert kaspa_tools._coerce_timeout_seconds(raw) == expected


def test_timeout_rejects_non_number():
    with pytest.raises(ValueError, match="timeout_seconds"):
        kaspa_tools._coerce_timeout_seconds("slow")


def test_happy_path_json_response_for_kaspa_api(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://node.example/info/health"
        assert req.headers["User-agent"] == "HermesAgent/KaspaTools"
        assert timeout == 4
        return FakeResponse(200, b'{"server": "up"}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_api_health({
        "url": "https://node.example",
        "timeout_seconds": 4,
    }))

    assert result == {
        "ok": True,
        "url": "https://node.example",
        "endpoint": "https://node.example/info/health",
        "status_code": 200,
        "health": {"server": "up"},
    }


def test_happy_path_json_response_for_kasia_indexer(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://indexer.example/metrics"
        assert timeout == 8
        return FakeResponse(200, b'{"lag": 0}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_health({
        "url": "https://indexer.example",
        "timeout_seconds": 8,
    }))

    assert result == {
        "ok": True,
        "url": "https://indexer.example",
        "endpoint": "https://indexer.example/metrics",
        "status_code": 200,
        "metrics": {"lag": 0},
    }


def test_http_status_response_becomes_json_error(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(503, b'{"message": "maintenance"}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_api_health({"url": "https://node.example"}))

    assert result["ok"] is False
    assert result["status_code"] == 503
    assert result["url"] == "https://node.example"
    assert result["endpoint"] == "https://node.example/info/health"
    assert result["payload"] == {"message": "maintenance"}
    assert "error" in result


def test_http_error_exception_becomes_json_error(monkeypatch):
    def fake_urlopen(req, timeout):
        raise error.HTTPError(
            req.full_url,
            500,
            "server error",
            hdrs=None,
            fp=FakeResponse(500, b'{"failed": true}'),
        )

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_health({"url": "https://indexer.example"}))

    assert result["ok"] is False
    assert result["status_code"] == 500
    assert result["url"] == "https://indexer.example"
    assert result["endpoint"] == "https://indexer.example/metrics"
    assert result["payload"] == {"failed": True}
    assert "HTTP 500" in result["error"]


def test_network_error_becomes_json_error(monkeypatch):
    def fake_urlopen(req, timeout):
        raise error.URLError("connection refused")

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_api_health({"url": "https://node.example"}))

    assert result["ok"] is False
    assert result["status_code"] is None
    assert result["url"] == "https://node.example"
    assert result["endpoint"] == "https://node.example/info/health"
    assert "Network error" in result["error"]


def test_kasia_indexer_query_encodes_required_and_optional_params(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'[{"id": "m1"}]')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_contextual_messages_by_sender({
        "url": "http://indexer.example",
        "address": "kaspa:qz sender",
        "alias": "00ff",
        "limit": 25,
        "block_time": 123456789,
        "timeout_seconds": 3,
    }))

    assert result == {
        "ok": True,
        "url": "http://indexer.example",
        "endpoint": "http://indexer.example/contextual-messages/by-sender?address=kaspa%3Aqz+sender&alias=00ff&limit=25&block_time=123456789",
        "status_code": 200,
        "items": [{"id": "m1"}],
    }
    assert seen == {"url": result["endpoint"], "timeout": 3}


def test_kasia_indexer_query_rejects_missing_required_param():
    result = _json(kaspa_tools.kasia_indexer_payments_by_sender({"url": "http://indexer.example"}))

    assert result["ok"] is False
    assert "address is required" in result["error"]


def test_kasia_indexer_query_clamps_limit_and_omits_empty_optional_params(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse(200, b'[]')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_handshakes_by_receiver({
        "url": "http://indexer.example",
        "address": "kaspa:qreceiver",
        "limit": 5000,
        "block_time": "",
    }))

    assert result["ok"] is True
    assert seen["url"] == "http://indexer.example/handshakes/by-receiver?address=kaspa%3Aqreceiver&limit=1000"


def test_kasia_indexer_self_stash_by_owner_uses_scope_and_owner(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse(200, b'{"stash": []}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kasia_indexer_self_stash_by_owner({
        "url": "http://indexer.example",
        "scope": "00",
        "owner": "kaspa:qowner",
    }))

    assert result["ok"] is True
    assert result["items"] == {"stash": []}
    assert seen["url"] == "http://indexer.example/self-stash/by-owner?scope=00&owner=kaspa%3Aqowner"


def test_kaspa_block_lookup_fetches_block(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"hash":"abc123","blueScore":42}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_block_lookup({
        "url": "https://api.example",
        "block_id": "abc123",
        "timeout_seconds": 4,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/blocks/abc123",
        "status_code": 200,
        "block": {"hash": "abc123", "blueScore": 42},
    }
    assert seen == {"url": result["endpoint"], "timeout": 4}


def test_kaspa_block_lookup_rejects_missing_block_id():
    result = _json(kaspa_tools.kaspa_block_lookup({"url": "https://api.example"}))

    assert result["ok"] is False
    assert "block_id is required" in result["error"]


def test_kaspa_transaction_lookup_fetches_transaction(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"transaction_id":"abc123","block_hash":["def456"]}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_transaction_lookup({
        "url": "https://api.example",
        "transaction_id": "abc123",
        "timeout_seconds": 4,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/transactions/abc123",
        "status_code": 200,
        "transaction": {"transaction_id": "abc123", "block_hash": ["def456"]},
    }
    assert seen == {"url": result["endpoint"], "timeout": 4}


def test_kaspa_transaction_lookup_rejects_missing_transaction_id():
    result = _json(kaspa_tools.kaspa_transaction_lookup({"url": "https://api.example"}))

    assert result["ok"] is False
    assert "transaction_id is required" in result["error"]


def test_kaspa_address_balance_fetches_balance(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"address":"kaspa:qabc","balance":12345}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_balance({
        "url": "https://api.example",
        "address": "kaspa:qabc",
        "timeout_seconds": 6,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/addresses/kaspa%3Aqabc/balance",
        "status_code": 200,
        "balance": {"address": "kaspa:qabc", "balance": 12345},
    }
    assert seen == {"url": result["endpoint"], "timeout": 6}


def test_kaspa_address_utxo_count_fetches_count(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://api.example/addresses/kaspa%3Aqabc/utxos/count"
        return FakeResponse(200, b'{"count":7}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_utxo_count({
        "url": "https://api.example",
        "address": "kaspa:qabc",
    }))

    assert result["ok"] is True
    assert result["utxo_count"] == {"count": 7}


def test_kaspa_address_utxos_fetches_open_outputs(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://api.example/addresses/kaspa%3Aqabc/utxos"
        return FakeResponse(200, b'[{"outpoint":{"transactionId":"tx1","index":0},"utxoEntry":{"amount":"1000"}}]')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_utxos({
        "url": "https://api.example",
        "address": "kaspa:qabc",
    }))

    assert result["ok"] is True
    assert result["utxos"] == [{"outpoint": {"transactionId": "tx1", "index": 0}, "utxoEntry": {"amount": "1000"}}]


def test_kaspa_address_name_returns_name_payload(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://api.example/addresses/kaspa%3Aqabc/name"
        return FakeResponse(200, b'{"name":"Example"}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_name({
        "url": "https://api.example",
        "address": "kaspa:qabc",
    }))

    assert result["ok"] is True
    assert result["name"] == {"name": "Example"}


def test_kaspa_address_transaction_count_fetches_count(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://api.example/addresses/kaspa%3Aqabc/transactions-count"
        return FakeResponse(200, b'{"transactionsCount":9}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_transaction_count({
        "url": "https://api.example",
        "address": "kaspa:qabc",
    }))

    assert result["ok"] is True
    assert result["transaction_count"] == {"transactionsCount": 9}


def test_kaspa_address_transactions_fetches_limited_page(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'[{"transaction_id":"tx1"}]')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kaspa_address_transactions({
        "url": "https://api.example",
        "address": "kaspa:qabc",
        "limit": 999,
        "before": 123456,
        "after": 42,
        "timeout_seconds": 7,
    }))

    assert result == {
        "ok": True,
        "url": "https://api.example",
        "endpoint": "https://api.example/addresses/kaspa%3Aqabc/full-transactions-page?limit=500&before=123456&after=42",
        "status_code": 200,
        "transactions": [{"transaction_id": "tx1"}],
    }
    assert seen == {"url": result["endpoint"], "timeout": 7}


def test_kaspa_address_tools_reject_missing_address():
    result = _json(kaspa_tools.kaspa_address_balance({"url": "https://api.example"}))

    assert result["ok"] is False
    assert "address is required" in result["error"]


def test_kns_search_assets_encodes_filters(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse(200, b'{"success":true,"data":{"assets":[]}}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kns_search_assets({
        "url": "https://kns.example/mainnet",
        "asset": "insta.kas",
        "owner": "kaspa:qowner",
        "page": 2,
        "page_size": 50,
        "sort_order": "ASC",
        "timeout_seconds": 4,
    }))

    assert result == {
        "ok": True,
        "url": "https://kns.example/mainnet",
        "endpoint": "https://kns.example/mainnet/api/v1/assets?owner=kaspa%3Aqowner&page=2&asset=insta.kas&sortOrder=ASC&pageSize=50",
        "status_code": 200,
        "assets": {"success": True, "data": {"assets": []}},
    }
    assert seen == {"url": result["endpoint"], "timeout": 4}


def test_kns_domain_owner_quotes_domain(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://kns.example/mainnet/api/v1/hello.kas/owner"
        return FakeResponse(200, b'{"success":true,"data":{"owner":"kaspa:qowner"}}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kns_domain_owner({
        "url": "https://kns.example/mainnet",
        "domain": "hello.kas",
    }))

    assert result["ok"] is True
    assert result["owner"] == {"success": True, "data": {"owner": "kaspa:qowner"}}


def test_kns_primary_name_quotes_address(monkeypatch):
    def fake_urlopen(req, timeout):
        assert req.full_url == "https://kns.example/mainnet/api/v1/primary-name/kaspa%3Aqowner"
        return FakeResponse(200, b'{"success":true,"data":{"domain":{"fullName":"hello.kas"}}}')

    monkeypatch.setattr(kaspa_tools.request, "urlopen", fake_urlopen)

    result = _json(kaspa_tools.kns_primary_name({
        "url": "https://kns.example/mainnet",
        "address": "kaspa:qowner",
    }))

    assert result["ok"] is True
    assert result["primary_name"] == {"success": True, "data": {"domain": {"fullName": "hello.kas"}}}


def test_kns_domain_owner_rejects_missing_domain():
    result = _json(kaspa_tools.kns_domain_owner({"url": "https://kns.example/mainnet"}))

    assert result["ok"] is False
    assert "domain is required" in result["error"]
