#!/usr/bin/env python3
"""CLI helper for Hermes's built-in Kasia integration."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any


FALLBACK_BRIDGE_BASE = "http://127.0.0.1:3010"
KASIA_STATE_PATH = Path.home() / ".hermes" / "kasia" / "state.json"
SOMPI_PER_KAS = Decimal("100000000")


def _normalize_address(value: str) -> str:
    trimmed = str(value or "").strip().lower()
    if not trimmed:
        raise SystemExit("Kaspa address is required")
    if trimmed.startswith(("kaspa:", "kaspatest:", "kaspasim:", "broadcast:")):
        return trimmed
    if trimmed.startswith("#"):
        return trimmed
    if len(trimmed) >= 6 and trimmed[0] in {"q", "p"}:
        return f"kaspa:{trimmed}"
    return trimmed


def _normalize_base_url(value: str | None) -> str | None:
    trimmed = str(value or "").strip().rstrip("/")
    if not trimmed:
        return None
    if not trimmed.startswith(("http://", "https://")):
        raise SystemExit(f"Invalid base URL: {value}")
    return trimmed


def _resolve_bridge_base(explicit: str | None) -> str:
    return _normalize_base_url(explicit) or _normalize_base_url(os.environ.get("KASIA_BRIDGE_BASE")) or FALLBACK_BRIDGE_BASE


def _request_json(method: str, path: str, *, base_url: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{base_url}{path}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "HermesAgent/1.0",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"error": body or f"HTTP {error.code}"}
        raise SystemExit(json.dumps(parsed, indent=2))
    except urllib.error.URLError as error:
        raise SystemExit(f"Connection error: {error.reason}") from error


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _load_state() -> dict[str, Any] | None:
    if not KASIA_STATE_PATH.exists():
        return None
    try:
        return json.loads(KASIA_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sompi_to_kas_string(value: int | str | None) -> str:
    sompi = Decimal(str(value or "0"))
    kas = (sompi / SOMPI_PER_KAS).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    text = format(kas, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _kas_to_sompi_string(value: str) -> str:
    try:
        kas = Decimal(str(value).strip())
    except Exception as error:  # pragma: no cover - Decimal exception type is noisy
        raise SystemExit(f"Invalid KAS amount: {value}") from error
    if kas <= 0:
        raise SystemExit("Amount must be positive")
    sompi = (kas * SOMPI_PER_KAS).quantize(Decimal("1"), rounding=ROUND_DOWN)
    if sompi <= 0:
        raise SystemExit("Amount must be positive")
    return str(int(sompi))


def _ms_to_iso(value: Any) -> str | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def _wallet_inspection(bridge_base: str, tx_id: str | None = None) -> dict[str, Any]:
    path = "/wallet"
    if str(tx_id or "").strip():
        encoded = urllib.parse.quote(str(tx_id).strip(), safe="")
        path = f"/wallet?txId={encoded}"
    return _request_json("GET", path, base_url=bridge_base)


def _resolve_amount_sompi(args: argparse.Namespace) -> str:
    amount_kas = getattr(args, "amount_kas", None)
    amount_sompi = getattr(args, "amount_sompi", None)
    if amount_kas is not None:
        return _kas_to_sompi_string(amount_kas)
    normalized_sompi = str(amount_sompi or "").strip()
    if not normalized_sompi:
        raise SystemExit("Amount is required")
    try:
        sompi = int(normalized_sompi)
    except ValueError as error:
        raise SystemExit(f"Invalid sompi amount: {amount_sompi}") from error
    if sompi <= 0:
        raise SystemExit("Amount must be positive")
    return str(sompi)


def _wallet_payload(wallet_response: dict[str, Any]) -> dict[str, Any]:
    wallet = wallet_response.get("wallet") or {}
    snapshot = wallet_response.get("balanceSnapshot") or {}
    return {
        "address": _normalize_address(wallet.get("address") or "") if wallet.get("address") else None,
        "network": str(wallet.get("network") or "").strip() or None,
        "fundingState": str(wallet.get("fundingState") or "").strip() or None,
        "onChainBalanceSompi": str(snapshot.get("onChainBalanceSompi") or "0"),
        "onChainBalanceKas": _sompi_to_kas_string(snapshot.get("onChainBalanceSompi")),
        "availableMatureBalanceSompi": str(snapshot.get("availableMatureBalanceSompi") or "0"),
        "availableMatureBalanceKas": _sompi_to_kas_string(snapshot.get("availableMatureBalanceSompi")),
        "availablePendingBalanceSompi": str(snapshot.get("availablePendingBalanceSompi") or "0"),
        "availablePendingBalanceKas": _sompi_to_kas_string(snapshot.get("availablePendingBalanceSompi")),
        "trackedPendingBalanceSompi": str(snapshot.get("trackedPendingBalanceSompi") or "0"),
        "trackedPendingBalanceKas": _sompi_to_kas_string(snapshot.get("trackedPendingBalanceSompi")),
        "recommendedMinBalanceSompi": str(wallet_response.get("recommendedMinBalanceSompi") or "0"),
        "recommendedMinBalanceKas": _sompi_to_kas_string(wallet_response.get("recommendedMinBalanceSompi")),
        "minimumMessageAmountSompi": str(wallet_response.get("minimumMessageAmountSompi") or "0"),
        "minimumMessageAmountKas": _sompi_to_kas_string(wallet_response.get("minimumMessageAmountSompi")),
        "matureUtxoCount": int(snapshot.get("matureUtxoCount") or 0),
        "pendingUtxoCount": int(snapshot.get("pendingUtxoCount") or 0),
        "trackedPendingUtxoCount": int(snapshot.get("trackedPendingUtxoCount") or 0),
        "walletBalanceUpdatedAt": _ms_to_iso(snapshot.get("updatedAtMs")),
    }


def _conversation_payload(chat_id: str) -> dict[str, Any]:
    state = _load_state() or {}
    conversations = state.get("conversations") or {}
    record = conversations.get(_normalize_address(chat_id))
    if not isinstance(record, dict):
        raise SystemExit(f"No local Kasia conversation state found for {chat_id}")
    return {
        "chatId": _normalize_address(chat_id),
        "conversation": record,
    }


def cmd_status(args: argparse.Namespace) -> None:
    wallet_response = _wallet_inspection(args.bridge_base)
    state = _load_state() or {}
    conversations = state.get("conversations") or {}
    channels = ((state.get("broadcasts") or {}).get("channels") or {})
    payload = {
        "bridgeBase": args.bridge_base,
        "bridgeStatus": str(wallet_response.get("bridgeStatus") or "").strip() or None,
        "wallet": _wallet_payload(wallet_response),
        "activeIndexerUrl": str(wallet_response.get("activeIndexerUrl") or "").strip() or None,
        "activeNodeUrl": str(wallet_response.get("activeNodeUrl") or "").strip() or None,
        "feePolicy": str(wallet_response.get("feePolicy") or "").strip() or None,
        "feeRateSompiPerGram": wallet_response.get("feeRateSompiPerGram"),
        "localStatePath": str(KASIA_STATE_PATH),
        "conversationCount": len(conversations),
        "broadcastChannelCount": len(channels),
        "walletInspection": wallet_response,
    }
    _print_json(payload)


def cmd_address(args: argparse.Namespace) -> None:
    wallet_response = _wallet_inspection(args.bridge_base)
    wallet = _wallet_payload(wallet_response)
    _print_json(
        {
            "address": wallet.get("address"),
            "network": wallet.get("network"),
            "fundingState": wallet.get("fundingState"),
        }
    )


def cmd_wallet(args: argparse.Namespace) -> None:
    wallet_response = _wallet_inspection(args.bridge_base)
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "wallet": _wallet_payload(wallet_response),
            "txQuery": wallet_response.get("txQuery"),
            "walletInspection": wallet_response,
        }
    )


def cmd_tx_check(args: argparse.Namespace) -> None:
    wallet_response = _wallet_inspection(args.bridge_base, tx_id=args.tx_id)
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "txQuery": wallet_response.get("txQuery"),
            "wallet": _wallet_payload(wallet_response),
        }
    )


def cmd_resolve(args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(args.target, safe="")
    resolved = _request_json("GET", f"/resolve-target/{encoded}", base_url=args.bridge_base)
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "target": args.target,
            "resolved": resolved,
        }
    )


def cmd_chat(args: argparse.Namespace) -> None:
    chat_id = _normalize_address(args.chat_id)
    encoded = urllib.parse.quote(chat_id, safe="")
    chat = _request_json("GET", f"/chat/{encoded}", base_url=args.bridge_base)
    payload = {
        "bridgeBase": args.bridge_base,
        "chat": chat,
    }
    state = _load_state() or {}
    record = ((state.get("conversations") or {}).get(chat_id) or None)
    if isinstance(record, dict):
        payload["conversation"] = record
    _print_json(payload)


def cmd_conversation(args: argparse.Namespace) -> None:
    _print_json(_conversation_payload(args.chat_id))


def cmd_handshake_initiate(args: argparse.Namespace) -> None:
    payload = {
        "chatId": args.chat_id,
        "retry": bool(args.retry),
    }
    if args.display_name:
        payload["displayName"] = args.display_name
    response = _request_json("POST", "/handshakes/initiate", base_url=args.bridge_base, payload=payload)
    _print_json(response)


def cmd_handshake_respond(args: argparse.Namespace) -> None:
    response = _request_json(
        "POST",
        "/handshakes/respond",
        base_url=args.bridge_base,
        payload={"chatId": args.chat_id},
    )
    _print_json(response)


def cmd_send(args: argparse.Namespace) -> None:
    if not str(args.message or "").strip():
        raise SystemExit("send requires --message")
    payload = {
        "chatId": args.chat_id,
        "message": args.message,
    }
    if args.wait_ms is not None:
        payload["waitMs"] = int(args.wait_ms)
    response = _request_json("POST", "/send", base_url=args.bridge_base, payload=payload)
    _print_json(response)


def cmd_send_status(args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(args.job_id, safe="")
    response = _request_json("GET", f"/send/{encoded}", base_url=args.bridge_base)
    _print_json(response)


def cmd_sign_message(args: argparse.Namespace) -> None:
    response = _request_json(
        "POST",
        "/wallet/sign-message",
        base_url=args.bridge_base,
        payload={"message": args.message},
    )
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "message": args.message,
            "signature": response,
        }
    )


def _wallet_send_payload(response: dict[str, Any]) -> dict[str, Any]:
    payload = dict(response)
    amount_sompi = payload.get("amountSompi")
    if amount_sompi is not None:
        payload["amountKas"] = _sompi_to_kas_string(amount_sompi)
    fee_sompi = payload.get("feeSompi")
    if fee_sompi is not None:
        payload["feeKas"] = _sompi_to_kas_string(fee_sompi)
    total_sompi = payload.get("totalRequiredSompi")
    if total_sompi is not None:
        payload["totalRequiredKas"] = _sompi_to_kas_string(total_sompi)
    return payload


def cmd_send_kaspa_preview(args: argparse.Namespace) -> None:
    response = _request_json(
        "POST",
        "/wallet/send-kaspa/preview",
        base_url=args.bridge_base,
        payload={
            "destinationAddress": _normalize_address(args.destination_address),
            "amountSompi": _resolve_amount_sompi(args),
            "feePolicy": str(args.fee_policy or "auto"),
        },
    )
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "preview": _wallet_send_payload(response),
        }
    )


def cmd_send_kaspa(args: argparse.Namespace) -> None:
    response = _request_json(
        "POST",
        "/wallet/send-kaspa",
        base_url=args.bridge_base,
        payload={
            "destinationAddress": _normalize_address(args.destination_address),
            "amountSompi": _resolve_amount_sompi(args),
            "feePolicy": str(args.fee_policy or "auto"),
        },
    )
    _print_json(
        {
            "bridgeBase": args.bridge_base,
            "send": _wallet_send_payload(response),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and operate Hermes's built-in Kasia bridge")
    parser.add_argument("--bridge-base", help="Override the local Kasia bridge base URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show bridge health, wallet funding state, and active endpoints")
    status.set_defaults(func=cmd_status)

    address = subparsers.add_parser("address", help="Show Hermes's Kaspa address used for Kasia")
    address.set_defaults(func=cmd_address)

    wallet = subparsers.add_parser("wallet", help="Show wallet balances and funding details")
    wallet.set_defaults(func=cmd_wallet)

    tx_check = subparsers.add_parser("tx-check", help="Check whether a txid is visible to Hermes's Kaspa wallet")
    tx_check.add_argument("tx_id")
    tx_check.set_defaults(func=cmd_tx_check)

    resolve = subparsers.add_parser("resolve", help="Resolve a Kasia DM or broadcast target")
    resolve.add_argument("target")
    resolve.set_defaults(func=cmd_resolve)

    chat = subparsers.add_parser("chat", help="Show bridge-facing chat info for one Kasia target")
    chat.add_argument("chat_id")
    chat.set_defaults(func=cmd_chat)

    conversation = subparsers.add_parser("conversation", help="Show local Kasia conversation state for one peer")
    conversation.add_argument("chat_id")
    conversation.set_defaults(func=cmd_conversation)

    handshake_initiate = subparsers.add_parser("handshake-initiate", help="Initiate a Kasia handshake")
    handshake_initiate.add_argument("chat_id")
    handshake_initiate.add_argument("--display-name")
    handshake_initiate.add_argument("--retry", action="store_true")
    handshake_initiate.set_defaults(func=cmd_handshake_initiate)

    handshake_respond = subparsers.add_parser("handshake-respond", help="Respond to a pending Kasia handshake")
    handshake_respond.add_argument("chat_id")
    handshake_respond.set_defaults(func=cmd_handshake_respond)

    send = subparsers.add_parser("send", help="Send a generic Kasia direct message")
    send.add_argument("chat_id")
    send.add_argument("--message", required=True)
    send.add_argument("--wait-ms", type=int)
    send.set_defaults(func=cmd_send)

    send_status = subparsers.add_parser("send-status", help="Check a prior Kasia send job by job id")
    send_status.add_argument("job_id")
    send_status.set_defaults(func=cmd_send_status)

    sign_message = subparsers.add_parser("sign-message", help="Sign a message with Hermes's Kaspa identity used for Kasia")
    sign_message.add_argument("--message", required=True)
    sign_message.set_defaults(func=cmd_sign_message)

    send_kaspa_preview = subparsers.add_parser(
        "send-kaspa-preview",
        help="Preview a direct KAS send from Hermes's Kaspa wallet",
    )
    send_kaspa_preview.add_argument("destination_address")
    amount_group = send_kaspa_preview.add_mutually_exclusive_group(required=True)
    amount_group.add_argument("--amount-kas")
    amount_group.add_argument("--amount-sompi")
    send_kaspa_preview.add_argument(
        "--fee-policy",
        choices=["auto", "low", "normal", "priority"],
        default="auto",
    )
    send_kaspa_preview.set_defaults(func=cmd_send_kaspa_preview)

    send_kaspa = subparsers.add_parser(
        "send-kaspa",
        help="Send KAS directly from Hermes's Kaspa wallet",
    )
    send_kaspa.add_argument("destination_address")
    amount_group = send_kaspa.add_mutually_exclusive_group(required=True)
    amount_group.add_argument("--amount-kas")
    amount_group.add_argument("--amount-sompi")
    send_kaspa.add_argument(
        "--fee-policy",
        choices=["auto", "low", "normal", "priority"],
        default="auto",
    )
    send_kaspa.set_defaults(func=cmd_send_kaspa)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.bridge_base = _resolve_bridge_base(getattr(args, "bridge_base", None))
    args.func(args)


if __name__ == "__main__":
    main()
