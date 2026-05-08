"""Read-only Kaspa/Kasia HTTP status tools."""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
from pathlib import Path
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
DEFAULT_KASPA_NODE_WRPC_PORT = 17110
DEFAULT_KASPA_NODE_NETWORK = "mainnet"
DEFAULT_KASPA_NODE_INFO_PROBE_COMMAND = "node scripts/kaspa-node-probe/node-info.mjs"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _required_non_negative_int(args: dict, name: str, *, max_value: int | None = None) -> int:
    number = _optional_non_negative_int(args, name, max_value=max_value)
    if number is None:
        raise ValueError(f"{name} is required")
    return number


def _optional_string(args: dict, name: str) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(args: dict, name: str) -> bool | None:
    value = args.get(name)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


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


def kaspa_network_info(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa network metadata from the REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        result = _get_json(base_url, "/info/network", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "network")


def kaspa_blockdag_info(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa BlockDAG metadata from the REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        result = _get_json(base_url, "/info/blockdag", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "blockdag")


def kaspa_coin_supply(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa coin supply metadata from the REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        result = _get_json(base_url, "/info/coinsupply", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "coin_supply")


def kaspa_fee_estimate(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa fee estimate metadata from the REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        result = _get_json(base_url, "/info/fee-estimate", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "fee_estimate")


def _kaspa_info_tool(args: dict, *, path: str, payload_key: str) -> str:
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        result = _get_json(base_url, path, args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, payload_key)


def kaspa_price(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa USD price metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/price", payload_key="price")


def kaspa_marketcap(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa market-cap metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/marketcap", payload_key="marketcap")


def kaspa_hashrate(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa hashrate metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/hashrate", payload_key="hashrate")


def kaspa_max_hashrate(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa max hashrate metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/hashrate/max", payload_key="max_hashrate")


def kaspa_hashrate_history(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa hashrate history from the REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        day_or_month = _optional_string(args, "day_or_month")
        resolution = _optional_string(args, "resolution")
        query = {"resolution": resolution} if resolution else None
        path = "/info/hashrate/history"
        if day_or_month:
            path = f"{path}/{quote(day_or_month, safe='')}"
        result = _get_json(base_url, path, args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "hashrate_history")


def kaspa_circulating_coin_supply(args: dict, **kwargs) -> str:
    """Fetch read-only circulating Kaspa supply metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/coinsupply/circulating", payload_key="circulating_coin_supply")


def kaspa_total_coin_supply(args: dict, **kwargs) -> str:
    """Fetch read-only total Kaspa supply metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/coinsupply/total", payload_key="total_coin_supply")


def kaspa_kaspad_info(args: dict, **kwargs) -> str:
    """Fetch read-only connected kaspad metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/kaspad", payload_key="kaspad")


def kaspa_blockreward(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa block reward metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/blockreward", payload_key="blockreward")


def kaspa_halving_info(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa halving metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/halving", payload_key="halving")


def kaspa_virtual_chain_blue_score(args: dict, **kwargs) -> str:
    """Fetch read-only Kaspa virtual-chain blue-score metadata from the REST API."""
    return _kaspa_info_tool(args, path="/info/virtual-chain-blue-score", payload_key="blue_score")


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


def kaspa_node_info(args: dict, **kwargs) -> str:
    """Fetch read-only kaspad node info through an isolated local probe command."""
    try:
        host = _optional_string(args, "host") or os.getenv("KASPA_NODE_RPC_HOST") or DEFAULT_KASPA_NODE_RPC_HOST
        port = _coerce_tcp_port(
            args.get("port")
            or os.getenv("KASPA_NODE_WRPC_PORT")
            or os.getenv("KASPA_NODE_RPC_PORT")
            or DEFAULT_KASPA_NODE_WRPC_PORT
        )
        endpoint = _optional_string(args, "url") or os.getenv("KASPA_NODE_RPC_URL") or f"ws://{host}:{port}"
        network = _optional_string(args, "network") or os.getenv("KASPA_NODE_NETWORK") or DEFAULT_KASPA_NODE_NETWORK
        timeout = _coerce_timeout_seconds(args.get("timeout_seconds"))
        command_text = (
            _optional_string(args, "probe_command")
            or os.getenv("KASPA_NODE_INFO_PROBE_COMMAND")
            or DEFAULT_KASPA_NODE_INFO_PROBE_COMMAND
        )
        command = shlex.split(command_text)
        if not command:
            raise ValueError("probe_command is required")
        probe_input = {
            "host": host,
            "port": port,
            "network": network,
            "timeout_seconds": timeout,
            "url": endpoint,
        }
        completed = subprocess.run(
            command,
            input=json.dumps(probe_input),
            text=True,
            capture_output=True,
            timeout=timeout + 2,
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        return tool_error(
            f"Kaspa node info probe timed out after {timeout + 2} seconds",
            ok=False,
            host=locals().get("host", DEFAULT_KASPA_NODE_RPC_HOST),
            port=locals().get("port", DEFAULT_KASPA_NODE_WRPC_PORT),
            endpoint=locals().get("endpoint"),
            network=locals().get("network", DEFAULT_KASPA_NODE_NETWORK),
            timeout_seconds=locals().get("timeout", 10),
            stdout=(exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else None,
            stderr=(exc.stderr or "")[:2000] if isinstance(exc.stderr, str) else None,
        )
    except Exception as exc:
        return tool_error(
            str(exc),
            ok=False,
            host=locals().get("host", DEFAULT_KASPA_NODE_RPC_HOST),
            port=locals().get("port", DEFAULT_KASPA_NODE_WRPC_PORT),
            endpoint=locals().get("endpoint"),
            network=locals().get("network", DEFAULT_KASPA_NODE_NETWORK),
            timeout_seconds=locals().get("timeout", 10),
        )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return tool_error(
            f"Kaspa node info probe exited with status {completed.returncode}",
            ok=False,
            host=host,
            port=port,
            endpoint=endpoint,
            network=network,
            timeout_seconds=timeout,
            stdout=stdout[:2000],
            stderr=stderr[:2000],
        )
    try:
        node_info = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return tool_error(
            f"Kaspa node info probe returned invalid JSON: {exc}",
            ok=False,
            host=host,
            port=port,
            endpoint=endpoint,
            network=network,
            timeout_seconds=timeout,
            stdout=stdout[:2000],
            stderr=stderr[:2000],
        )

    return tool_result(
        ok=True,
        host=host,
        port=port,
        endpoint=endpoint,
        network=network,
        timeout_seconds=timeout,
        probe="subprocess",
        node_info=node_info,
    )



def kaspa_transaction_lookup(args: dict, **kwargs) -> str:
    """Fetch a read-only transaction payload by transaction id from the Kaspa REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        transaction_id = quote(_required_string(args, "transaction_id"), safe="")
        result = _get_json(base_url, f"/transactions/{transaction_id}", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "transaction")


def kaspa_block_lookup(args: dict, **kwargs) -> str:
    """Fetch a read-only block payload by block hash/id from the Kaspa REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        block_id = quote(_required_string(args, "block_id"), safe="")
        result = _get_json(base_url, f"/blocks/{block_id}", args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "block")


def kaspa_blocks(args: dict, **kwargs) -> str:
    """Fetch read-only blocks from the Kaspa REST API by low hash."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        query: dict[str, Any] = {"lowHash": _required_string(args, "low_hash")}
        include_blocks = _optional_bool(args, "include_blocks")
        include_transactions = _optional_bool(args, "include_transactions")
        if include_blocks is not None:
            query["includeBlocks"] = str(include_blocks).lower()
        if include_transactions is not None:
            query["includeTransactions"] = str(include_transactions).lower()
        result = _get_json(base_url, "/blocks", args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "blocks")


def kaspa_blocks_from_bluescore(args: dict, **kwargs) -> str:
    """Fetch read-only blocks from the Kaspa REST API by blue-score range."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        query: dict[str, Any] = {}
        blue_score = _optional_non_negative_int(args, "blue_score")
        blue_score_gte = _optional_non_negative_int(args, "blue_score_gte")
        blue_score_lt = _optional_non_negative_int(args, "blue_score_lt")
        include_transactions = _optional_bool(args, "include_transactions")
        if blue_score is not None:
            query["blueScore"] = blue_score
        if blue_score_gte is not None:
            query["blueScoreGte"] = blue_score_gte
        if blue_score_lt is not None:
            query["blueScoreLt"] = blue_score_lt
        if include_transactions is not None:
            query["includeTransactions"] = str(include_transactions).lower()
        result = _get_json(base_url, "/blocks-from-bluescore", args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "blocks")


def kaspa_transaction_count(args: dict, **kwargs) -> str:
    """Fetch read-only accepted transaction count metadata from the Kaspa REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        day_or_month = _optional_string(args, "day_or_month")
        path = "/transactions/count/"
        if day_or_month:
            path = f"{path}{quote(day_or_month, safe='')}"
        result = _get_json(base_url, path, args.get("timeout_seconds"))
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "transaction_count")


def kaspa_virtual_chain(args: dict, **kwargs) -> str:
    """Fetch read-only virtual-chain transactions by blue score from the Kaspa REST API."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        limit = _optional_non_negative_int(args, "limit", max_value=100)
        if limit is None:
            limit = 10
        else:
            limit = 100 if limit > 10 else 10
        blue_score_gte = _required_non_negative_int(args, "blue_score_gte")
        blue_score_gte = blue_score_gte - (blue_score_gte % limit)
        query: dict[str, Any] = {"blueScoreGte": blue_score_gte, "limit": limit}
        resolve_inputs = _optional_bool(args, "resolve_inputs")
        include_coinbase = _optional_bool(args, "include_coinbase")
        if resolve_inputs is not None:
            query["resolveInputs"] = str(resolve_inputs).lower()
        if include_coinbase is not None:
            query["includeCoinbase"] = str(include_coinbase).lower()
        result = _get_json(base_url, "/virtual-chain", args.get("timeout_seconds"), query=query)
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "virtual_chain")


def kaspa_address_balance(args: dict, **kwargs) -> str:
    """Fetch the read-only balance payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="balance", payload_key="balance")


def kaspa_address_utxo_count(args: dict, **kwargs) -> str:
    """Fetch the read-only UTXO count payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="utxos/count", payload_key="utxo_count")


def kaspa_address_utxos(args: dict, **kwargs) -> str:
    """Fetch the read-only open UTXO payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="utxos", payload_key="utxos")


def kaspa_address_name(args: dict, **kwargs) -> str:
    """Fetch the read-only name payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="name", payload_key="name")


def kaspa_address_transaction_count(args: dict, **kwargs) -> str:
    """Fetch the read-only transaction count payload for a Kaspa address."""
    return _kaspa_address_tool(args, suffix="transactions-count", payload_key="transaction_count")


def kaspa_address_transactions(args: dict, **kwargs) -> str:
    """Fetch a read-only limited transaction page for a Kaspa address."""
    base_url = args.get("url") or os.getenv("KASPA_API_URL") or DEFAULT_KASPA_API_URL
    try:
        address = quote(_required_string(args, "address"), safe="")
        query: dict[str, Any] = {}
        limit = _optional_non_negative_int(args, "limit", max_value=500)
        before = _optional_non_negative_int(args, "before")
        after = _optional_non_negative_int(args, "after")
        if limit is not None:
            query["limit"] = max(1, limit)
        if before is not None:
            query["before"] = before
        if after is not None:
            query["after"] = after
        result = _get_json(
            base_url,
            f"/addresses/{address}/full-transactions-page",
            args.get("timeout_seconds"),
            query=query,
        )
    except Exception as exc:
        return _error_from_exception(exc)

    return _successful_json_result(result, "transactions")


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

_NETWORK_SCHEMA = {
    "type": "string",
    "description": "Optional Kaspa network id for node probes. Defaults to KASPA_NODE_NETWORK, then mainnet.",
}

_PROBE_COMMAND_SCHEMA = {
    "type": "string",
    "description": "Optional local read-only probe command. Defaults to KASPA_NODE_INFO_PROBE_COMMAND, then the bundled Node probe. The bundled probe expects a wRPC WebSocket endpoint, default port 17110.",
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

_ADDRESS_TX_LIMIT_SCHEMA = {
    "type": "integer",
    "description": "Optional max address transactions to return. Clamped to the 1-500 range.",
    "minimum": 1,
    "maximum": 500,
}

_EPOCH_MILLIS_CURSOR_SCHEMA = {
    "type": "integer",
    "description": "Optional epoch-millis pagination cursor.",
    "minimum": 0,
}

_HASHRATE_HISTORY_RESOLUTION_SCHEMA = {
    "type": "string",
    "description": "Optional hashrate-history resolution accepted by the Kaspa REST API, for example 15m, 1h, 3h, 1d, or 7d.",
}

_DAY_OR_MONTH_SCHEMA = {
    "type": "string",
    "description": "Optional UTC day or month cursor in YYYY-MM-DD or YYYY-MM format.",
}

_KASPA_ADDRESS_SCHEMA = {
    "type": "string",
    "description": "Kaspa address to query.",
}

_TRANSACTION_ID_SCHEMA = {
    "type": "string",
    "description": "Kaspa transaction id to query.",
}

_BLOCK_ID_SCHEMA = {
    "type": "string",
    "description": "Kaspa block hash/id to query.",
}

_LOW_HASH_SCHEMA = {
    "type": "string",
    "description": "Kaspa low block hash cursor used by the REST /blocks endpoint.",
}

_BLUE_SCORE_SCHEMA = {
    "type": "integer",
    "description": "Optional Kaspa blue-score cursor or bound.",
    "minimum": 0,
}

_INCLUDE_BLOCKS_SCHEMA = {
    "type": "boolean",
    "description": "Optional flag to include full block payloads where supported by the Kaspa REST API.",
}

_INCLUDE_TRANSACTIONS_SCHEMA = {
    "type": "boolean",
    "description": "Optional flag to include transaction payloads where supported by the Kaspa REST API.",
}

_VIRTUAL_CHAIN_LIMIT_SCHEMA = {
    "type": "integer",
    "description": "Optional virtual-chain result limit. Clamped to the REST API's safe enum values: 10 or 100.",
    "enum": [10, 100],
}

_RESOLVE_INPUTS_SCHEMA = {
    "type": "boolean",
    "description": "Optional flag to resolve transaction inputs in virtual-chain reads.",
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
    name="kaspa_network_info",
    toolset="kaspa",
    schema={
        "name": "kaspa_network_info",
        "description": "Read-only Kaspa REST /info/network metadata lookup.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_network_info,
    description="Read-only Kaspa network metadata lookup",
)

registry.register(
    name="kaspa_blockdag_info",
    toolset="kaspa",
    schema={
        "name": "kaspa_blockdag_info",
        "description": "Read-only Kaspa REST /info/blockdag metadata lookup.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_blockdag_info,
    description="Read-only Kaspa BlockDAG metadata lookup",
)

registry.register(
    name="kaspa_coin_supply",
    toolset="kaspa",
    schema={
        "name": "kaspa_coin_supply",
        "description": "Read-only Kaspa REST /info/coinsupply lookup.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_coin_supply,
    description="Read-only Kaspa coin supply lookup",
)

registry.register(
    name="kaspa_fee_estimate",
    toolset="kaspa",
    schema={
        "name": "kaspa_fee_estimate",
        "description": "Read-only Kaspa REST /info/fee-estimate lookup.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_fee_estimate,
    description="Read-only Kaspa fee estimate lookup",
)


def _register_kaspa_info_tool(*, name: str, handler, endpoint: str, description: str) -> None:
    registry.register(
        name=name,
        toolset="kaspa",
        schema={
            "name": name,
            "description": f"Read-only Kaspa REST {endpoint} lookup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": _URL_SCHEMA,
                    "timeout_seconds": _TIMEOUT_SCHEMA,
                },
                "additionalProperties": False,
            },
        },
        handler=handler,
        description=description,
    )


_register_kaspa_info_tool(
    name="kaspa_price",
    handler=kaspa_price,
    endpoint="/info/price",
    description="Read-only Kaspa price lookup",
)

_register_kaspa_info_tool(
    name="kaspa_marketcap",
    handler=kaspa_marketcap,
    endpoint="/info/marketcap",
    description="Read-only Kaspa market-cap lookup",
)

_register_kaspa_info_tool(
    name="kaspa_hashrate",
    handler=kaspa_hashrate,
    endpoint="/info/hashrate",
    description="Read-only Kaspa hashrate lookup",
)

_register_kaspa_info_tool(
    name="kaspa_max_hashrate",
    handler=kaspa_max_hashrate,
    endpoint="/info/hashrate/max",
    description="Read-only Kaspa max hashrate lookup",
)

_register_kaspa_info_tool(
    name="kaspa_circulating_coin_supply",
    handler=kaspa_circulating_coin_supply,
    endpoint="/info/coinsupply/circulating",
    description="Read-only Kaspa circulating coin supply lookup",
)

_register_kaspa_info_tool(
    name="kaspa_total_coin_supply",
    handler=kaspa_total_coin_supply,
    endpoint="/info/coinsupply/total",
    description="Read-only Kaspa total coin supply lookup",
)

registry.register(
    name="kaspa_hashrate_history",
    toolset="kaspa",
    schema={
        "name": "kaspa_hashrate_history",
        "description": "Read-only Kaspa REST /info/hashrate/history lookup, optionally for a specific UTC day or month.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "day_or_month": _DAY_OR_MONTH_SCHEMA,
                "resolution": _HASHRATE_HISTORY_RESOLUTION_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_hashrate_history,
    description="Read-only Kaspa hashrate history lookup",
)

_register_kaspa_info_tool(
    name="kaspa_kaspad_info",
    handler=kaspa_kaspad_info,
    endpoint="/info/kaspad",
    description="Read-only connected kaspad info lookup",
)

_register_kaspa_info_tool(
    name="kaspa_blockreward",
    handler=kaspa_blockreward,
    endpoint="/info/blockreward",
    description="Read-only Kaspa block reward lookup",
)

_register_kaspa_info_tool(
    name="kaspa_halving_info",
    handler=kaspa_halving_info,
    endpoint="/info/halving",
    description="Read-only Kaspa halving lookup",
)

_register_kaspa_info_tool(
    name="kaspa_virtual_chain_blue_score",
    handler=kaspa_virtual_chain_blue_score,
    endpoint="/info/virtual-chain-blue-score",
    description="Read-only Kaspa virtual-chain blue score lookup",
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

registry.register(
    name="kaspa_node_info",
    toolset="kaspa",
    schema={
        "name": "kaspa_node_info",
        "description": "Read-only kaspad node info via an isolated local probe/facade command. Does not require a wallet or signing key.",
        "parameters": {
            "type": "object",
            "properties": {
                "host": _HOST_SCHEMA,
                "port": _PORT_SCHEMA,
                "url": {
                    "type": "string",
                    "description": "Optional concrete RPC endpoint URL for the probe, for example ws://127.0.0.1:17110. Defaults to KASPA_NODE_RPC_URL, then ws://<host>:<port>. The bundled probe expects wRPC WebSocket, not the gRPC-only 16110 socket.",
                },
                "network": _NETWORK_SCHEMA,
                "probe_command": _PROBE_COMMAND_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_node_info,
    description="Read-only kaspad node info probe",
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
    name="kaspa_address_transaction_count",
    handler=kaspa_address_transaction_count,
    description="Read-only transaction count lookup for a Kaspa address.",
)

registry.register(
    name="kaspa_address_transactions",
    toolset="kaspa",
    schema={
        "name": "kaspa_address_transactions",
        "description": "Read-only limited transaction page lookup for a Kaspa address.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "address": _KASPA_ADDRESS_SCHEMA,
                "limit": _ADDRESS_TX_LIMIT_SCHEMA,
                "before": _EPOCH_MILLIS_CURSOR_SCHEMA,
                "after": _EPOCH_MILLIS_CURSOR_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "required": ["address"],
            "additionalProperties": False,
        },
    },
    handler=kaspa_address_transactions,
    description="Read-only Kaspa address transaction page lookup",
)

_register_kaspa_address_tool(
    name="kaspa_address_utxo_count",
    handler=kaspa_address_utxo_count,
    description="Read-only UTXO count lookup for a Kaspa address.",
)

_register_kaspa_address_tool(
    name="kaspa_address_utxos",
    handler=kaspa_address_utxos,
    description="Read-only open UTXO lookup for a Kaspa address.",
)

registry.register(
    name="kaspa_block_lookup",
    toolset="kaspa",
    schema={
        "name": "kaspa_block_lookup",
        "description": "Read-only block lookup by block hash/id using the Kaspa REST API.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "block_id": _BLOCK_ID_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "required": ["block_id"],
            "additionalProperties": False,
        },
    },
    handler=kaspa_block_lookup,
    description="Read-only Kaspa block lookup",
)

registry.register(
    name="kaspa_blocks",
    toolset="kaspa",
    schema={
        "name": "kaspa_blocks",
        "description": "Read-only block page lookup using the Kaspa REST /blocks endpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "low_hash": _LOW_HASH_SCHEMA,
                "include_blocks": _INCLUDE_BLOCKS_SCHEMA,
                "include_transactions": _INCLUDE_TRANSACTIONS_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "required": ["low_hash"],
            "additionalProperties": False,
        },
    },
    handler=kaspa_blocks,
    description="Read-only Kaspa block page lookup",
)

registry.register(
    name="kaspa_blocks_from_bluescore",
    toolset="kaspa",
    schema={
        "name": "kaspa_blocks_from_bluescore",
        "description": "Read-only block lookup using the Kaspa REST /blocks-from-bluescore endpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "blue_score": _BLUE_SCORE_SCHEMA,
                "blue_score_gte": _BLUE_SCORE_SCHEMA,
                "blue_score_lt": _BLUE_SCORE_SCHEMA,
                "include_transactions": _INCLUDE_TRANSACTIONS_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_blocks_from_bluescore,
    description="Read-only Kaspa blocks-from-bluescore lookup",
)

registry.register(
    name="kaspa_transaction_lookup",
    toolset="kaspa",
    schema={
        "name": "kaspa_transaction_lookup",
        "description": "Read-only transaction lookup by transaction id using the Kaspa REST API.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "transaction_id": _TRANSACTION_ID_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "required": ["transaction_id"],
            "additionalProperties": False,
        },
    },
    handler=kaspa_transaction_lookup,
    description="Read-only Kaspa transaction lookup",
)

registry.register(
    name="kaspa_transaction_count",
    toolset="kaspa",
    schema={
        "name": "kaspa_transaction_count",
        "description": "Read-only accepted transaction count lookup, optionally for a UTC day or month.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "day_or_month": _DAY_OR_MONTH_SCHEMA,
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
    handler=kaspa_transaction_count,
    description="Read-only Kaspa accepted transaction count lookup",
)

registry.register(
    name="kaspa_virtual_chain",
    toolset="kaspa",
    schema={
        "name": "kaspa_virtual_chain",
        "description": "Read-only virtual-chain transaction lookup by blue-score cursor using the Kaspa REST API.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": _URL_SCHEMA,
                "blue_score_gte": _BLUE_SCORE_SCHEMA,
                "limit": _VIRTUAL_CHAIN_LIMIT_SCHEMA,
                "resolve_inputs": _RESOLVE_INPUTS_SCHEMA,
                "include_coinbase": {"type": "boolean", "description": "Optional flag to include coinbase transactions."},
                "timeout_seconds": _TIMEOUT_SCHEMA,
            },
            "required": ["blue_score_gte"],
            "additionalProperties": False,
        },
    },
    handler=kaspa_virtual_chain,
    description="Read-only Kaspa virtual-chain transaction lookup",
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
