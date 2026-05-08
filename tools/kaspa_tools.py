"""Read-only Kaspa/Kasia HTTP status tools."""

from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib import error, request
from urllib.parse import quote, urlencode, urlparse

from tools.registry import registry, tool_error, tool_result


USER_AGENT = "HermesAgent/KaspaTools"
DEFAULT_KASPA_API_URL = "https://api.kaspa.org"
DEFAULT_KASIA_INDEXER_URL = "https://indexer.kasia.fyi"
DEFAULT_KNS_API_URL = "https://api.knsdomains.org/mainnet"
DEFAULT_KASPA_NODE_RPC_HOST = "127.0.0.1"
DEFAULT_KASPA_NODE_RPC_PORT = 16110


def _normalize_base_url(url: str) -> str:
    """Validate and normalize an HTTP(S) base URL."""
    value = str(url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an http:// or https:// URL")
    return value


def _coerce_timeout_seconds(value: Any = None) -> int:
    """Coerce timeout to an int in the allowed 1-30 second range."""
    if value is None or value == "":
        return 10
    try:
        timeout = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_seconds must be a number") from exc
    if timeout < 1:
        return 1
    if timeout > 30:
        return 30
    return timeout


def _coerce_tcp_port(value: Any = None) -> int:
    """Coerce a TCP port to an int in the allowed 1-65535 range."""
    if value is None or value == "":
        return DEFAULT_KASPA_NODE_RPC_PORT
    try:
        port = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be a number") from exc
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def _decode_json_body(body: bytes) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _get_json(
    base_url: str,
    path: str,
    timeout_seconds: Any = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET a read-only JSON-ish endpoint and return status plus parsed payload."""
    url = _normalize_base_url(base_url)
    timeout = _coerce_timeout_seconds(timeout_seconds)
    endpoint = f"{url}{path}"
    if query:
        endpoint = f"{endpoint}?{urlencode(query)}"
    req = request.Request(endpoint, headers={"User-Agent": USER_AGENT}, method="GET")

    try:
        with request.urlopen(req, timeout=timeout) as response:
            status_code = int(response.getcode())
            body = response.read()
    except error.HTTPError as exc:
        payload = _decode_json_body(exc.read())
        raise RuntimeError(
            json.dumps({
                "message": f"HTTP {exc.code} from {endpoint}",
                "url": url,
                "endpoint": endpoint,
                "status_code": int(exc.code),
                "payload": payload,
            })
        ) from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            json.dumps({
                "message": f"Network error fetching {endpoint}: {reason}",
                "url": url,
                "endpoint": endpoint,
                "status_code": None,
            })
        ) from exc

    return {
        "url": url,
        "endpoint": endpoint,
        "status_code": status_code,
        "payload": _decode_json_body(body),
    }


def _error_from_exception(exc: Exception) -> str:
    try:
        details = json.loads(str(exc))
    except json.JSONDecodeError:
        return tool_error(str(exc), ok=False)
    message = details.pop("message", "Kaspa/Kasia HTTP request failed")
    return tool_error(message, ok=False, **details)


def _health_tool(args: dict, *, env_name: str, default_url: str, path: str, payload_key: str) -> str:
    base_url = args.get("url") or os.getenv(env_name) or default_url
    try:
        result = _get_json(base_url, path, args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    status_code = result["status_code"]
    if not 200 <= status_code < 300:
        return tool_error(
            f"HTTP {status_code} from {result['endpoint']}",
            ok=False,
            url=result["url"],
            endpoint=result["endpoint"],
            status_code=status_code,
            payload=result["payload"],
        )

    return tool_result(
        ok=True,
        url=result["url"],
        endpoint=result["endpoint"],
        status_code=status_code,
        **{payload_key: result["payload"]},
    )


def _required_string(args: dict, name: str) -> str:
    value = str(args.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional_non_negative_int(args: dict, name: str, *, max_value: int | None = None) -> int | None:
    value = args.get(name)
    if value is None or value == "":
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number < 0:
        number = 0
    if max_value is not None and number > max_value:
        number = max_value
    return number


def _optional_string(args: dict, name: str) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _successful_json_result(result: dict[str, Any], payload_key: str) -> str:
    status_code = result["status_code"]
    if not 200 <= status_code < 300:
        return tool_error(
            f"HTTP {status_code} from {result['endpoint']}",
            ok=False,
            url=result["url"],
            endpoint=result["endpoint"],
            status_code=status_code,
            payload=result["payload"],
        )

    return tool_result(
        ok=True,
        url=result["url"],
        endpoint=result["endpoint"],
        status_code=status_code,
        **{payload_key: result["payload"]},
    )


def _kasia_indexer_query_tool(
    args: dict,
    *,
    path: str,
    required_params: tuple[str, ...],
) -> str:
    base_url = args.get("url") or os.getenv("KASIA_INDEXER_URL") or DEFAULT_KASIA_INDEXER_URL
    try:
        query: dict[str, Any] = {name: _required_string(args, name) for name in required_params}
        limit = _optional_non_negative_int(args, "limit", max_value=1000)
        block_time = _optional_non_negative_int(args, "block_time")
        if limit is not None:
            query["limit"] = limit
        if block_time is not None:
            query["block_time"] = block_time
        result = _get_json(base_url, path, args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    status_code = result["status_code"]
    if not 200 <= status_code < 300:
        return tool_error(
            f"HTTP {status_code} from {result['endpoint']}",
            ok=False,
            url=result["url"],
            endpoint=result["endpoint"],
            status_code=status_code,
            payload=result["payload"],
        )

    return tool_result(
        ok=True,
        url=result["url"],
        endpoint=result["endpoint"],
        status_code=status_code,
        items=result["payload"],
    )


def _kaspa_address_tool(args: dict, *, suffix: str, payload_key: str) -> str:
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        address = quote(_required_string(args, "address"), safe="")
        result = _get_json(
            base_url,
            f"/addresses/{address}/{suffix.lstrip('/')}",
            args.get("timeout_seconds"),
        )
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, payload_key)


def _kns_api_tool(args: dict, *, path: str, payload_key: str, query: dict[str, Any] | None = None) -> str:
    base_url = args.get("url") or os.getenv("KNS_API_URL") or DEFAULT_KNS_API_URL
    try:
        result = _get_json(base_url, path, args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, payload_key)


def kaspa_api_health(args: dict, **kwargs) -> str:
    """Check the public/read-only Kaspa API health endpoint."""
    return _health_tool(
        args,
        env_name="KASPA_API_URL",
        default_url=DEFAULT_KASPA_API_URL,
        path="/info/health",
        payload_key="health",
    )


def kasia_indexer_health(args: dict, **kwargs) -> str:
    """Check the public/read-only Kasia indexer metrics endpoint."""
    return _health_tool(
        args,
        env_name="KASIA_INDEXER_URL",
        default_url=DEFAULT_KASIA_INDEXER_URL,
        path="/metrics",
        payload_key="metrics",
    )


def kaspa_node_rpc_tcp_health(args: dict, **kwargs) -> str:
    """Check TCP reachability for a kaspad RPC endpoint without issuing RPC calls."""
    try:
        host = _optional_string(args, "host") or os.getenv("KASPA_NODE_RPC_HOST") or DEFAULT_KASPA_NODE_RPC_HOST
        port = _coerce_tcp_port(args.get("port") or os.getenv("KASPA_NODE_RPC_PORT"))
        timeout = _coerce_timeout_seconds(args.get("timeout_seconds"))
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except Exception as exc:
        return tool_error(
            str(exc),
            ok=False,
            host=locals().get("host", DEFAULT_KASPA_NODE_RPC_HOST),
            port=locals().get("port", DEFAULT_KASPA_NODE_RPC_PORT),
            timeout_seconds=locals().get("timeout", 10),
        )

    return tool_result(
        ok=True,
        host=host,
        port=port,
        protocol_hint="kaspad gRPC/wRPC TCP endpoint; this check verifies reachability only",
        timeout_seconds=timeout,
    )


def kaspa_address_balance(args: dict, **kwargs) -> str:
    """Fetch the read-only balance payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="balance", payload_key="balance")


def kaspa_address_utxo_count(args: dict, **kwargs) -> str:
    """Fetch the read-only UTXO count payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="utxos/count", payload_key="utxo_count")


def kaspa_address_name(args: dict, **kwargs) -> str:
    """Fetch the read-only name payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="name", payload_key="name")


def kns_search_assets(args: dict, **kwargs) -> str:
    """Search read-only KNS assets/domains with optional filters."""
    try:
        query: dict[str, Any] = {}
        for arg_name, param_name in (
            ("owner", "owner"),
            ("page", "page"),
            ("asset", "asset"),
            ("sort_order", "sortOrder"),
            ("collection", "collection"),
            ("asset_type", "type"),
        ):
            value = _optional_string(args, arg_name)
            if value is not None:
                query[param_name] = value
        page_size = _optional_non_negative_int(args, "page_size", max_value=100)
        if page_size is not None:
            query["pageSize"] = page_size
    except Exception as exc:
        return _error_from_exception(exc)
    return _kns_api_tool(args, path="/api/v1/assets", payload_key="assets", query=query)


def kns_domain_owner(args: dict, **kwargs) -> str:
    """Fetch the read-only owner payload for a KNS domain."""
    try:
        domain = quote(_required_string(args, "domain"), safe="")
    except Exception as exc:
        return _error_from_exception(exc)
    return _kns_api_tool(args, path=f"/api/v1/{domain}/owner", payload_key="owner")


def kns_primary_name(args: dict, **kwargs) -> str:
    """Fetch the read-only primary KNS name payload for a Kaspa address."""
    try:
        address = quote(_required_string(args, "address"), safe="")
    except Exception as exc:
        return _error_from_exception(exc)
    return _kns_api_tool(args, path=f"/api/v1/primary-name/{address}", payload_key="primary_name")


def kasia_indexer_handshakes_by_sender(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia handshake records by sender address."""
    return _kasia_indexer_query_tool(
        args,
        path="/handshakes/by-sender",
        required_params=("address",),
    )


def kasia_indexer_handshakes_by_receiver(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia handshake records by receiver address."""
    return _kasia_indexer_query_tool(
        args,
        path="/handshakes/by-receiver",
        required_params=("address",),
    )


def kasia_indexer_payments_by_sender(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia payment records by sender address."""
    return _kasia_indexer_query_tool(
        args,
        path="/payments/by-sender",
        required_params=("address",),
    )


def kasia_indexer_payments_by_receiver(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia payment records by receiver address."""
    return _kasia_indexer_query_tool(
        args,
        path="/payments/by-receiver",
        required_params=("address",),
    )


def kasia_indexer_contextual_messages_by_sender(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia contextual messages by sender address and alias."""
    return _kasia_indexer_query_tool(
        args,
        path="/contextual-messages/by-sender",
        required_params=("address", "alias"),
    )


def kasia_indexer_self_stash_by_owner(args: dict, **kwargs) -> str:
    """Fetch read-only Kasia self-stash records by scope and owner."""
    return _kasia_indexer_query_tool(
        args,
        path="/self-stash/by-owner",
        required_params=("scope", "owner"),
    )


_URL_SCHEMA = {
    "type": "string",
    "description": "Optional http:// or https:// base URL. Defaults to the corresponding environment variable, then the public default.",
}

_TIMEOUT_SCHEMA = {
    "type": "number",
    "description": "Optional timeout in seconds. Defaults to 10 and is clamped to the 1-30 second range.",
}

_HOST_SCHEMA = {
    "type": "string",
    "description": "Optional kaspad RPC host. Defaults to KASPA_NODE_RPC_HOST, then 127.0.0.1.",
}

_PORT_SCHEMA = {
    "type": "integer",
    "description": "Optional kaspad RPC TCP port. Defaults to KASPA_NODE_RPC_PORT, then 16110.",
    "minimum": 1,
    "maximum": 65535,
}

_LIMIT_SCHEMA = {
    "type": "integer",
    "description": "Optional max records to return. Clamped to the 0-1000 range.",
    "minimum": 0,
}

_BLOCK_TIME_SCHEMA = {
    "type": "integer",
    "description": "Optional minimum block_time cursor/filter value.",
    "minimum": 0,
}

_KASPA_ADDRESS_SCHEMA = {
    "type": "string",
    "description": "Kaspa address to query.",
}

_ALIAS_SCHEMA = {
    "type": "string",
    "description": "Kasia alias hex string paired with the sender address.",
}

_SCOPE_SCHEMA = {
    "type": "string",
    "description": "Kasia self-stash scope hex string to query.",
}

_OWNER_SCHEMA = {
    "type": "string",
    "description": "Kasia self-stash owner identifier to query.",
}

_KNS_DOMAIN_SCHEMA = {
    "type": "string",
    "description": "KNS domain, for example example.kas.",
}

_PAGE_SCHEMA = {
    "type": "integer",
    "description": "Optional page number.",
    "minimum": 0,
}

_PAGE_SIZE_SCHEMA = {
    "type": "integer",
    "description": "Optional page size. Clamped to the 0-100 range.",
    "minimum": 0,
    "maximum": 100,
}

_SORT_ORDER_SCHEMA = {
    "type": "string",
    "description": "Optional sort order accepted by the KNS API, for example ASC or DESC.",
}


def _register_kasia_query_tool(
    *,
    name: str,
    handler,
    description: str,
    required_properties: dict[str, dict[str, Any]],
) -> None:
    properties = {
        "url": _URL_SCHEMA,
        **required_properties,
        "limit": _LIMIT_SCHEMA,
        "block_time": _BLOCK_TIME_SCHEMA,
        "timeout_seconds": _TIMEOUT_SCHEMA,
    }
    registry.register(
        name=name,
        toolset="kaspa",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required_properties.keys()),
                "additionalProperties": False,
            },
        },
        handler=handler,
        description=description,
    )


def _register_kaspa_address_tool(*, name: str, handler, description: str) -> None:
    registry.register(
        name=name,
        toolset="kaspa",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": _URL_SCHEMA,
                    "address": _KASPA_ADDRESS_SCHEMA,
                    "timeout_seconds": _TIMEOUT_SCHEMA,
                },
                "required": ["address"],
                "additionalProperties": False,
            },
        },
        handler=handler,
        description=description,
    )


def _register_kns_single_param_tool(
    *,
    name: str,
    handler,
    description: str,
    property_name: str,
    property_schema: dict[str, Any],
) -> None:
    registry.register(
        name=name,
        toolset="kaspa",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": _URL_SCHEMA,
                    property_name: property_schema,
                    "timeout_seconds": _TIMEOUT_SCHEMA,
                },
                "required": [property_name],
                "additionalProperties": False,
            },
        },
        handler=handler,
        description=description,
    )


registry.register(
    name="kaspa_api_health",
    toolset="kaspa",
    schema={
        "name": "kaspa_api_health",
        "description": "Read-only check of the Kaspa API /info/health endpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_api_health,
    description="Read-only Kaspa API health check",
)

registry.register(
    name="kasia_indexer_health",
    toolset="kaspa",
    schema={
        "name": "kasia_indexer_health",
        "description": "Read-only check of the Kasia indexer /metrics endpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kasia_indexer_health,
    description="Read-only Kasia indexer metrics check",
)

registry.register(
    name="kaspa_node_rpc_tcp_health",
    toolset="kaspa",
    schema={
        "name": "kaspa_node_rpc_tcp_health",
        "description": "Read-only TCP reachability check for a kaspad RPC endpoint. Does not issue an RPC request.",
        "parameters": {
            "type": "object",
            "properties": {
                "host": _HOST_SCHEMA,
                "port": _PORT_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_node_rpc_tcp_health,
    description="Read-only kaspad RPC TCP reachability check",
)

_register_kaspa_address_tool(
    name="kaspa_address_balance",
    handler=kaspa_address_balance,
    description="Read-only balance lookup for a Kaspa address.",
)

_register_kaspa_address_tool(
    name="kaspa_address_name",
    handler=kaspa_address_name,
    description="Read-only known-name lookup for a Kaspa address.",
)

_register_kaspa_address_tool(
    name="kaspa_address_utxo_count",
    handler=kaspa_address_utxo_count,
    description="Read-only UTXO count lookup for a Kaspa address.",
)

registry.register(
    name="kns_search_assets",
    toolset="kaspa",
    schema={
        "name": "kns_search_assets",
        "description": "Read-only search of KNS assets/domains with optional asset, owner, pagination, and sort filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "asset": {"type": "string", "description": "Optional asset/domain search filter."},
                "owner": _KASPA_ADDRESS_SCHEMA,
                "page": _PAGE_SCHEMA,
                "page_size": _PAGE_SIZE_SCHEMA,
                "sort_order": _SORT_ORDER_SCHEMA,
                "collection": {"type": "string", "description": "Optional KNS collection filter."},
                "asset_type": {"type": "string", "description": "Optional KNS asset type filter."},
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kns_search_assets,
    description="Read-only KNS asset/domain search",
)

_register_kns_single_param_tool(
    name="kns_domain_owner",
    handler=kns_domain_owner,
    description="Read-only owner lookup for a KNS domain.",
    property_name="domain",
    property_schema=_KNS_DOMAIN_SCHEMA,
)

_register_kns_single_param_tool(
    name="kns_primary_name",
    handler=kns_primary_name,
    description="Read-only primary KNS name lookup for a Kaspa address.",
    property_name="address",
    property_schema=_KASPA_ADDRESS_SCHEMA,
)

_register_kasia_query_tool(
    name="kasia_indexer_handshakes_by_sender",
    handler=kasia_indexer_handshakes_by_sender,
    description="Read-only query of Kasia handshakes by sender address.",
    required_properties={"address": _KASPA_ADDRESS_SCHEMA},
)

_register_kasia_query_tool(
    name="kasia_indexer_handshakes_by_receiver",
    handler=kasia_indexer_handshakes_by_receiver,
    description="Read-only query of Kasia handshakes by receiver address.",
    required_properties={"address": _KASPA_ADDRESS_SCHEMA},
)

_register_kasia_query_tool(
    name="kasia_indexer_payments_by_sender",
    handler=kasia_indexer_payments_by_sender,
    description="Read-only query of Kasia payments by sender address.",
    required_properties={"address": _KASPA_ADDRESS_SCHEMA},
)

_register_kasia_query_tool(
    name="kasia_indexer_payments_by_receiver",
    handler=kasia_indexer_payments_by_receiver,
    description="Read-only query of Kasia payments by receiver address.",
    required_properties={"address": _KASPA_ADDRESS_SCHEMA},
)

_register_kasia_query_tool(
    name="kasia_indexer_contextual_messages_by_sender",
    handler=kasia_indexer_contextual_messages_by_sender,
    description="Read-only query of Kasia contextual messages by sender address and alias.",
    required_properties={"address": _KASPA_ADDRESS_SCHEMA, "alias": _ALIAS_SCHEMA},
)

_register_kasia_query_tool(
    name="kasia_indexer_self_stash_by_owner",
    handler=kasia_indexer_self_stash_by_owner,
    description="Read-only query of Kasia self-stash records by scope and owner.",
    required_properties={"scope": _SCOPE_SCHEMA, "owner": _OWNER_SCHEMA},
)
