#!/usr/bin/env python3
"""CLI helper for the kasia-jobs prototype board.

Usage examples:
  python3 kasia_jobs.py status
  python3 kasia_jobs.py auth --address kaspa:qworker...
  python3 kasia_jobs.py intent browse --limit 5 --new-since-hours 72
  python3 kasia_jobs.py intent post --request-text "Create a landing page" --budget-kas 1
  python3 kasia_jobs.py submit <job_id> --claim-id <claim_id> --summary "Done" --result-file result.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any


FALLBACK_BASE_URL = "http://127.0.0.1:3001"
FALLBACK_KASIA_BRIDGE_BASE = "http://127.0.0.1:3010"
STATE_DIR = Path.home() / ".hermes" / "skills-state" / "kasia-jobs"
SESSION_PATH = STATE_DIR / "session.json"
KASIA_STATE_PATH = Path.home() / ".hermes" / "kasia" / "state.json"
SOMPI_PER_KAS = Decimal("100000000")


def _normalize_address(value: str) -> str:
    trimmed = str(value or "").strip().lower()
    if not trimmed:
        raise SystemExit("Kaspa address is required")
    if trimmed.startswith(("kaspa:", "kaspatest:", "kaspasim:")):
        return trimmed
    if len(trimmed) >= 6 and trimmed[0] in {"q", "p"}:
        return f"kaspa:{trimmed}"
    raise SystemExit(f"Invalid Kaspa address: {value}")


def _normalize_kns(value: str | None) -> str | None:
    trimmed = str(value or "").strip().lower()
    if not trimmed:
        return None
    full = trimmed if trimmed.endswith(".kas") else f"{trimmed}.kas"
    return full


def _load_session() -> dict[str, Any] | None:
    if not SESSION_PATH.exists():
        return None
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_session(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_base_url(value: str | None) -> str | None:
    trimmed = str(value or "").strip().rstrip("/")
    if not trimmed:
        return None
    if not trimmed.startswith(("http://", "https://")):
        raise SystemExit(f"Invalid base URL: {value}")
    return trimmed


def _saved_api_base() -> str | None:
    session = _load_session()
    if not session:
        return None
    return _normalize_base_url(session.get("apiBase"))


def _resolve_base_url(explicit: str | None) -> str:
    return (
        _normalize_base_url(explicit)
        or _normalize_base_url(os.environ.get("KASIA_JOBS_API_BASE"))
        or _saved_api_base()
        or FALLBACK_BASE_URL
    )


def _resolve_kasia_bridge_base() -> str:
    return _normalize_base_url(os.environ.get("KASIA_BRIDGE_BASE")) or FALLBACK_KASIA_BRIDGE_BASE


def _bearer_token() -> str | None:
    session = _load_session()
    if not session:
        return None
    token = str(session.get("session", {}).get("token") or "").strip()
    return token or None


def _request_json(
    method: str,
    path: str,
    *,
    base_url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    url = f"{base_url}{path}"
    headers = {
      "Accept": "application/json",
      "User-Agent": "HermesAgent/1.0",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def _maybe_request_json(
    method: str,
    path: str,
    *,
    base_url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any | None:
    try:
        return _request_json(
            method,
            path,
            base_url=base_url,
            payload=payload,
            token=token,
        )
    except SystemExit:
        return None


def _request_json_result(
    method: str,
    path: str,
    *,
    base_url: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "data": _request_json(
                method,
                path,
                base_url=base_url,
                payload=payload,
                token=token,
            ),
        }
    except SystemExit as error:
        return {
            "ok": False,
            "error": str(error),
        }


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _build_query_path(path: str, params: list[tuple[str, Any]]) -> str:
    query_items: list[tuple[str, str]] = []
    for key, value in params:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        query_items.append((key, text))
    if not query_items:
        return path
    return f"{path}?{urllib.parse.urlencode(query_items, doseq=True)}"


def _iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_text_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SystemExit(f"Failed to read {path}: {error}") from error


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

def _preview_text(text: str, max_length: int = 500) -> str | None:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1]}…"


def _normalize_freeform_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _extract_budget_kas_from_text(value: str | None) -> tuple[str | None, str]:
    normalized = _normalize_freeform_text(value)
    if not normalized:
        return None, ""

    patterns = [
        r"\b(?P<amount>\d+(?:\.\d+)?)\s*(?:kas|kaspa)\b(?:\s+budget)?",
        r"\bbudget(?:\s+(?:of|is))?(?:\s+in\s+kas)?\s*(?P<amount>\d+(?:\.\d+)?)\b",
        r"\b(?P<amount>\d+(?:\.\d+)?)\s+budget\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        amount_text = str(match.group("amount") or "").strip()
        if not amount_text:
            continue
        try:
            normalized_amount = _sompi_to_kas_string(_kas_decimal_to_sompi(_parse_kas_decimal(amount_text)))
        except SystemExit:
            continue
        cleaned = _normalize_freeform_text(
            re.sub(r"\s+([,.;:!?])", r"\1", f"{normalized[:match.start()]} {normalized[match.end():]}")
        ).strip(" ,;:-")
        cleaned = re.sub(
            r"(?:[,.!?]\s*)?(?:i'?m\s+thinking|thinking|budget|offer(?:\s+of)?)\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" ,;:-")
        return normalized_amount, cleaned
    return None, normalized


def _suggest_job_title(value: str | None, max_words: int = 7) -> str | None:
    normalized = _normalize_freeform_text(value)
    if not normalized:
        return None

    normalized = normalized.strip(" \"'")
    normalized = re.sub(
        r"^(?:i\s+(?:want|need)(?:\s+someone)?\s+to|someone\s+to)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^(please\s+)?(post|create|make|build|write|draft|design|generate)\s+"
        r"(a\s+|an\s+|the\s+)?(kasia\s+)?job\s+(for|to)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^(please\s+)?(post|create|make|build|write|draft|design|generate)\s+(me\s+)?",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^(a|an|the)\s+", "", normalized, flags=re.IGNORECASE)
    first_segment = re.split(r"[.!?\n]", normalized, maxsplit=1)[0].strip(" ,;:-")
    if not first_segment:
        return None

    words = first_segment.split()
    title_words = words[:max_words]
    title = " ".join(title_words).strip(" ,;:-")
    if not title:
        return None
    if len(words) > max_words:
        title = f"{title}..."
    return title[:1].upper() + title[1:]


def _parse_kas_decimal(value: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise SystemExit(f"Invalid KAS amount: {value}") from error
    if decimal_value < 0:
        raise SystemExit(f"KAS amount must be non-negative: {value}")
    return decimal_value


def _kas_decimal_to_sompi(value: Decimal) -> int:
    sompi = (value * SOMPI_PER_KAS).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return int(sompi)


def _sompi_to_kas_string(value: int | str) -> str:
    sompi = Decimal(str(value))
    kas = (sompi / SOMPI_PER_KAS).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    text = format(kas, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _escrow_expected_amount_sompi(escrow: dict[str, Any]) -> str:
    for key in (
        "fundingTargetSompi",
        "expectedAmountSompi",
        "defaultFundingAmountSompi",
        "fundedAmountSompi",
    ):
        value = str(escrow.get(key) or "").strip()
        if value:
            return value
    funding_target_kas = str(escrow.get("fundingTargetKas") or "").strip()
    if funding_target_kas:
        return str(_kas_decimal_to_sompi(_parse_kas_decimal(funding_target_kas)))
    raise SystemExit("Escrow does not expose a usable funding amount")


def _manual_funding_details(escrow: dict[str, Any]) -> dict[str, Any]:
    funding_target_kas = str(escrow.get("fundingTargetKas") or "").strip() or _sompi_to_kas_string(
        _escrow_expected_amount_sompi(escrow)
    )
    deposit_address = str(escrow.get("depositAddress") or "").strip()
    return {
        "amountKas": funding_target_kas,
        "amountSompi": _escrow_expected_amount_sompi(escrow),
        "depositAddress": _normalize_address(deposit_address) if deposit_address else None,
    }


def _fetch_policy(base_url: str) -> dict[str, Any]:
    data = _request_json("GET", "/policy", base_url=base_url)
    return data.get("economicPolicy") or {}


def _quote_job_funding(*, budget_kas: str, base_url: str) -> dict[str, Any]:
    policy = _fetch_policy(base_url)
    budget_decimal = _parse_kas_decimal(budget_kas)
    budget_sompi = _kas_decimal_to_sompi(budget_decimal)
    min_budget_sompi = int(str(policy.get("minJobBudgetSompi") or "0"))
    settlement_reserve_sompi = int(str(policy.get("settlementFeeReserveSompi") or "0"))
    platform_fee_floor_sompi = int(str(policy.get("platformFeeFloorSompi") or "0"))
    platform_fee_bps = int(str(policy.get("platformFeeBps") or "0"))
    platform_fee_sompi = max(
        platform_fee_floor_sompi,
        (budget_sompi * platform_fee_bps) // 10_000,
    )
    funding_target_sompi = budget_sompi + settlement_reserve_sompi + platform_fee_sompi
    return {
        "budgetKas": _sompi_to_kas_string(budget_sompi),
        "budgetSompi": str(budget_sompi),
        "minJobBudgetKas": str(policy.get("minJobBudgetKas") or "0"),
        "minJobBudgetSompi": str(min_budget_sompi),
        "belowMinimum": budget_sompi < min_budget_sompi,
        "platformFeeKas": _sompi_to_kas_string(platform_fee_sompi),
        "platformFeeSompi": str(platform_fee_sompi),
        "settlementFeeReserveKas": _sompi_to_kas_string(settlement_reserve_sompi),
        "settlementFeeReserveSompi": str(settlement_reserve_sompi),
        "fundingTargetKas": _sompi_to_kas_string(funding_target_sompi),
        "fundingTargetSompi": str(funding_target_sompi),
        "policy": policy,
    }


def _parse_artifact_file(value: str) -> dict[str, Any]:
    if ":" not in value:
        raise SystemExit("--artifact-file expects KIND:PATH")
    kind, path = value.split(":", 1)
    content = _read_text_file(path)
    return {
        "kind": kind.strip(),
        "content": content,
        "hash": _sha256_text(content),
    }


def _parse_artifact_url(value: str) -> dict[str, Any]:
    if ":" not in value:
        raise SystemExit("--artifact-url expects KIND:URL")
    kind, url = value.split(":", 1)
    return {
        "kind": kind.strip(),
        "url": url.strip(),
    }


def _load_local_kasia_state() -> dict[str, Any] | None:
    if not KASIA_STATE_PATH.exists():
        return None
    try:
        return json.loads(KASIA_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_local_kasia_conversation(chat_id: str) -> dict[str, Any] | None:
    state = _load_local_kasia_state() or {}
    conversations = state.get("conversations") or {}
    normalized_chat_id = _normalize_address(chat_id)
    conversation = conversations.get(normalized_chat_id)
    return conversation if isinstance(conversation, dict) else None


def _detect_local_kasia_identity() -> dict[str, Any] | None:
    bridge_base = _resolve_kasia_bridge_base()
    bridge_health = _maybe_request_json("GET", "/health", base_url=bridge_base) or {}
    wallet_address = str(bridge_health.get("walletAddress") or "").strip()
    if wallet_address:
        return {
            "address": _normalize_address(wallet_address),
            "source": "bridge",
            "bridgeBase": bridge_base,
            "bridgeStatus": bridge_health.get("status"),
            "network": bridge_health.get("network"),
        }

    state = _load_local_kasia_state() or {}
    wallet = state.get("wallet") or {}
    state_address = str(wallet.get("address") or "").strip()
    if state_address:
        return {
            "address": _normalize_address(state_address),
            "source": "state",
            "statePath": str(KASIA_STATE_PATH),
            "network": wallet.get("network"),
        }
    return None


def _sign_message_with_kasia_bridge(message: str) -> dict[str, Any]:
    bridge_base = _resolve_kasia_bridge_base()
    payload = _request_json(
        "POST",
        "/wallet/sign-message",
        base_url=bridge_base,
        payload={"message": message},
    )
    payload["bridgeBase"] = bridge_base
    return payload


def _preview_send_with_kasia_bridge(
    *,
    destination_address: str,
    amount_sompi: str | int,
    priority_fee_sompi: str | int = "0",
) -> dict[str, Any]:
    bridge_base = _resolve_kasia_bridge_base()
    payload = _request_json(
        "POST",
        "/wallet/send-kaspa/preview",
        base_url=bridge_base,
        payload={
            "destinationAddress": _normalize_address(destination_address),
            "amountSompi": str(amount_sompi),
            "priorityFeeSompi": str(priority_fee_sompi),
        },
    )
    payload["bridgeBase"] = bridge_base
    return payload


def _send_with_kasia_bridge(
    *,
    destination_address: str,
    amount_sompi: str | int,
    priority_fee_sompi: str | int = "0",
) -> dict[str, Any]:
    bridge_base = _resolve_kasia_bridge_base()
    payload = _request_json(
        "POST",
        "/wallet/send-kaspa",
        base_url=bridge_base,
        payload={
            "destinationAddress": _normalize_address(destination_address),
            "amountSompi": str(amount_sompi),
            "priorityFeeSompi": str(priority_fee_sompi),
        },
    )
    payload["bridgeBase"] = bridge_base
    return payload


def _local_wallet_funding_option(escrow: dict[str, Any]) -> dict[str, Any]:
    local_identity = _detect_local_kasia_identity()
    if not local_identity:
        return {
            "available": False,
            "reason": "No local Kasia wallet was detected for this Hermes session.",
        }

    deposit_address = str(escrow.get("depositAddress") or "").strip()
    if not deposit_address:
        return {
            "available": False,
            "walletAddress": local_identity.get("address"),
            "reason": "This job does not expose an escrow deposit address yet.",
        }

    if str(escrow.get("status") or "").strip() != "awaiting_funds":
        return {
            "available": False,
            "walletAddress": local_identity.get("address"),
            "depositAddress": _normalize_address(deposit_address),
            "reason": f"Escrow is already {escrow.get('status') or 'not fundable'}",
        }

    amount_sompi = _escrow_expected_amount_sompi(escrow)
    preview_result = _request_json_result(
        "POST",
        "/wallet/send-kaspa/preview",
        base_url=_resolve_kasia_bridge_base(),
        payload={
            "destinationAddress": _normalize_address(deposit_address),
            "amountSompi": amount_sompi,
            "priorityFeeSompi": "0",
        },
    )
    if not preview_result["ok"]:
        return {
            "available": False,
            "walletAddress": local_identity.get("address"),
            "depositAddress": _normalize_address(deposit_address),
            "amountSompi": amount_sompi,
            "amountKas": _sompi_to_kas_string(amount_sompi),
            "reason": "Failed to preview a send from the local Kasia wallet.",
            "previewError": preview_result["error"],
        }

    preview = preview_result["data"] or {}
    can_send = bool(preview.get("canSend"))
    fee_sompi = str(preview.get("feeSompi") or "0")
    total_required_sompi = str(preview.get("totalRequiredSompi") or amount_sompi)
    return {
        "available": can_send,
        "walletAddress": local_identity.get("address"),
        "depositAddress": _normalize_address(deposit_address),
        "amountSompi": amount_sompi,
        "amountKas": _sompi_to_kas_string(amount_sompi),
        "feeSompi": fee_sompi,
        "feeKas": _sompi_to_kas_string(fee_sompi),
        "totalRequiredSompi": total_required_sompi,
        "totalRequiredKas": _sompi_to_kas_string(total_required_sompi),
        "preview": preview,
        "reason": (
            "I can fund this from my own wallet."
            if can_send
            else str(preview.get("error") or "I can't fund this from my wallet yet.")
        ),
    }


def _maybe_respond_to_pending_kasia_handshake(chat_id: str) -> dict[str, Any] | None:
    conversation = _load_local_kasia_conversation(chat_id)
    if not conversation:
        return None
    pending_handshake = conversation.get("pending_handshake")
    if not isinstance(pending_handshake, dict):
        return None

    bridge_base = _resolve_kasia_bridge_base()
    response = _maybe_request_json(
        "POST",
        "/handshakes/respond",
        base_url=bridge_base,
        payload={"chatId": _normalize_address(chat_id)},
    )
    return {
        "detectedPendingHandshake": True,
        "pendingHandshake": pending_handshake,
        "response": response,
        "bridgeBase": bridge_base,
    }


def _fetch_board_coordinator(base_url: str) -> dict[str, Any] | None:
    payload = _maybe_request_json("GET", "/coordinator", base_url=base_url)
    if not isinstance(payload, dict):
        return None
    coordinator = payload.get("coordinator")
    if not isinstance(coordinator, dict):
        return None
    actor = coordinator.get("actor") or {}
    address = str(actor.get("address") or "").strip()
    if not address:
        return None
    actor["address"] = _normalize_address(address)
    coordinator["actor"] = actor
    return coordinator


def _job_execution_target(job: dict[str, Any], kind: str) -> str | None:
    execution = job.get("execution") or {}
    if execution.get("platform") != "kasia":
        return None
    if kind in {"assignment_notice", "verdict_notice"}:
        awarded_worker = job.get("awardedWorker") or {}
        return str(
            execution.get("awardedWorkerChatId")
            or awarded_worker.get("address")
            or ""
        ).strip() or None
    return str(
        execution.get("chatId")
        or (job.get("poster") or {}).get("address")
        or ""
    ).strip() or None


def _record_transport_event(
    *,
    base_url: str,
    token: str,
    job_id: str,
    kind: str,
    summary: str,
    chat_id: str | None = None,
    external_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any | None:
    payload: dict[str, Any] = {
        "platform": "kasia",
        "kind": kind,
        "summary": summary,
    }
    if chat_id:
        payload["chatId"] = chat_id
    if external_ref:
        payload["externalRef"] = external_ref
    if metadata:
        payload["metadata"] = metadata
    return _maybe_request_json(
        "POST",
        f"/jobs/{job_id}/transport-events",
        base_url=base_url,
        token=token,
        payload=payload,
    )

def _record_job_message(
    *,
    base_url: str,
    token: str,
    job_id: str,
    kind: str,
    summary: str,
    chat_id: str | None = None,
    external_ref: str | None = None,
    content_hash: str | None = None,
    content_preview: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any | None:
    payload: dict[str, Any] = {
        "platform": "kasia",
        "kind": kind,
        "summary": summary,
    }
    if chat_id:
        payload["chatId"] = chat_id
    if external_ref:
        payload["externalRef"] = external_ref
    if content_hash:
        payload["contentHash"] = content_hash
    if content_preview:
        payload["contentPreview"] = content_preview
    if metadata:
        payload["metadata"] = metadata
    return _maybe_request_json(
        "POST",
        f"/jobs/{job_id}/messages",
        base_url=base_url,
        token=token,
        payload=payload,
    )


def _maybe_send_kasia_notice(
    *,
    base_url: str,
    token: str,
    job: dict[str, Any],
    kind: str,
    summary: str,
    message: str,
) -> dict[str, Any] | None:
    chat_id = _job_execution_target(job, kind)
    if not chat_id:
        return None

    bridge_base = _resolve_kasia_bridge_base()
    handshake = _maybe_request_json(
        "POST",
        "/handshakes/initiate",
        base_url=bridge_base,
        payload={"target": chat_id},
    )
    send_result = _maybe_request_json(
        "POST",
        "/send",
        base_url=bridge_base,
        payload={"chatId": chat_id, "message": message},
    )
    success = bool(send_result and not send_result.get("error"))
    send_job_id = None
    if send_result:
        send_job_id = send_result.get("job_id") or send_result.get("jobId")

    transport_event = None
    if success:
        transport_event = _record_transport_event(
            base_url=base_url,
            token=token,
            job_id=job["id"],
            kind=kind,
            summary=summary,
            chat_id=chat_id,
            external_ref=send_job_id,
            metadata={
                "bridgeBase": bridge_base,
                "handshake": handshake,
            },
        )

    return {
        "platform": "kasia",
        "chatId": chat_id,
        "handshake": handshake,
        "send": send_result,
        "transportEvent": transport_event,
        "success": success,
    }


def _send_kasia_thread_message(
    *,
    base_url: str,
    token: str,
    job: dict[str, Any],
    transport_kind: str,
    summary: str,
    message: str,
    job_message_kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    notice = _maybe_send_kasia_notice(
        base_url=base_url,
        token=token,
        job=job,
        kind=transport_kind,
        summary=summary,
        message=message,
    )
    if not notice or not notice.get("success") or not job_message_kind:
        return notice

    send_payload = notice.get("send") or {}
    send_job_id = send_payload.get("job_id") or send_payload.get("jobId")
    job_message = _record_job_message(
        base_url=base_url,
        token=token,
        job_id=job["id"],
        kind=job_message_kind,
        summary=summary,
        chat_id=notice.get("chatId"),
        external_ref=send_job_id,
        content_hash=_sha256_text(message),
        content_preview=_preview_text(message),
        metadata=metadata,
    )
    return {
        **notice,
        "jobMessage": job_message,
    }


def _maybe_bootstrap_coordinator_handshake(
    *,
    base_url: str,
    job: dict[str, Any],
) -> dict[str, Any] | None:
    execution = job.get("execution") or {}
    if execution.get("platform") != "kasia":
        return None

    coordinator = _fetch_board_coordinator(base_url)
    if not coordinator:
        return {
            "success": False,
            "reason": "board_coordinator_unavailable",
        }

    actor = coordinator.get("actor") or {}
    coordinator_address = _normalize_address(actor.get("address") or "")
    local_identity = _detect_local_kasia_identity()
    local_address = str((local_identity or {}).get("address") or "").strip()
    if local_address and _normalize_address(local_address) == coordinator_address:
        return {
            "success": True,
            "skipped": True,
            "reason": "local_identity_matches_coordinator",
            "coordinator": coordinator,
        }

    pending_response = _maybe_respond_to_pending_kasia_handshake(coordinator_address)
    if pending_response is not None:
        return {
            "success": True,
            "platform": "kasia",
            "chatId": coordinator_address,
            "coordinator": coordinator,
            "respondedToPendingHandshake": pending_response,
        }

    bridge_base = _resolve_kasia_bridge_base()
    handshake = _maybe_request_json(
        "POST",
        "/handshakes/initiate",
        base_url=bridge_base,
        payload={"target": coordinator_address},
    )
    success = bool(handshake)
    return {
        "success": success,
        "platform": "kasia",
        "chatId": coordinator_address,
        "bridgeBase": bridge_base,
        "coordinator": coordinator,
        "handshake": handshake,
    }


def _filtered_recommendations(
    *,
    base_url: str,
    token: str,
    limit: int,
    statuses: list[str] | None = None,
    new_since_hours: float | None = None,
) -> dict[str, Any]:
    query: list[tuple[str, Any]] = [("limit", max(1, limit))]
    for status in statuses or ["open"]:
        query.append(("status", status))
    path = _build_query_path("/jobs/recommendations/me", query)
    payload = _request_json(
        "GET",
        path,
        base_url=base_url,
        token=token,
    )
    recommendations = payload.get("recommendations") or []
    if new_since_hours is not None and new_since_hours > 0:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=new_since_hours)
        recommendations = [
            item
            for item in recommendations
            if (_iso_to_datetime((item.get("job") or {}).get("createdAt")) or cutoff) >= cutoff
        ]
    actionable = [item for item in recommendations if (item.get("policy") or {}).get("actionable")]
    awaiting_funding = [
        item
        for item in recommendations
        if "awaiting funding" in " ".join((item.get("reasons") or [])).lower()
        or any("awaiting funding" in warning.lower() for warning in ((item.get("policy") or {}).get("warnings") or []))
    ]
    next_actions = []
    human_summary = "No recommended jobs matched our capabilities right now."
    best_actionable = actionable[0] if actionable else None
    best_near_match = recommendations[0] if recommendations else None
    conversation_next_step = "Offer to watch the board again later or help the user post a new job."
    if actionable:
        top = actionable[0].get("job") or {}
        human_summary = (
            f"{len(recommendations)} recommended job(s) found; {len(actionable)} can be claimed now. "
            f"Best current fit is {top.get('title')} ({top.get('id')})."
        )
        conversation_next_step = (
            f"Offer to claim {top.get('title')} now, or keep watching the board if the user wants to wait."
        )
        next_actions.append(
            f"Claimable now: {top.get('id')} ({top.get('title')}). Claim it if the user wants us to proceed."
        )
    elif recommendations:
        top = recommendations[0].get("job") or {}
        human_summary = (
            f"{len(recommendations)} recommended job(s) found, but none are claimable right now. "
            f"Best near-match is {top.get('title')} ({top.get('id')})."
        )
        conversation_next_step = (
            f"Offer to watch {top.get('title')} for funding, or help the user post a new job instead."
        )
        next_actions.append(
            f"Nothing is claimable yet. Best near-match is {top.get('id')} ({top.get('title')}); watch it or wait for funding."
        )
        next_actions.append(
            "If none of the current jobs fit, offer to post a new job instead of stopping at counts."
        )
    else:
        next_actions.append(
            "No good fits right now. Offer to watch the board again later or help the user post a job of their own."
        )
    if awaiting_funding:
        next_actions.append(
            f"{len(awaiting_funding)} recommended job(s) are waiting on funding before they can be claimed."
        )
    return {
        "recommendations": recommendations,
        "requestedAt": datetime.now(tz=timezone.utc).isoformat(),
        "statuses": statuses or ["open"],
        "newSinceHours": new_since_hours,
        "humanSummary": human_summary,
        "conversationNextStep": conversation_next_step,
        "bestActionable": best_actionable,
        "bestNearMatch": best_near_match,
        "summary": {
            "recommendationCount": len(recommendations),
            "actionableCount": len(actionable),
            "awaitingFundingCount": len(awaiting_funding),
        },
        "nextActions": next_actions,
    }


def cmd_status(args: argparse.Namespace) -> None:
    mode = _request_json("GET", "/auth/mode", base_url=args.base_url)
    session = _load_session()
    payload = {
        "apiBase": args.base_url,
        "authMode": mode.get("authMode"),
        "sessionPath": str(SESSION_PATH),
        "hasSavedSession": bool(session),
        "savedIdentity": session.get("identity") if session else None,
        "localKasia": _detect_local_kasia_identity(),
    }
    _print_json(payload)


def cmd_auth(args: argparse.Namespace) -> None:
    detected_identity = _detect_local_kasia_identity()
    address = _normalize_address(
        args.address
        or os.environ.get("KASIA_JOBS_ADDRESS", "")
        or (detected_identity or {}).get("address", "")
    )
    kns_name = _normalize_kns(args.kns_name or os.environ.get("KASIA_JOBS_KNS_NAME"))
    display_name = (
        args.display_name
        or os.environ.get("KASIA_JOBS_DISPLAY_NAME")
        or ("Hermes Worker" if detected_identity else None)
    )
    mode = _request_json("GET", "/auth/mode", base_url=args.base_url)
    challenge_payload = {
        "address": address,
    }
    if kns_name:
        challenge_payload["knsName"] = kns_name
    if display_name:
        challenge_payload["displayName"] = display_name
    challenge = _request_json(
        "POST",
        "/auth/challenge",
        base_url=args.base_url,
        payload=challenge_payload,
    )
    auth_mode = mode.get("authMode")
    verify_payload = {
        "challengeId": challenge["challenge"]["id"],
        "address": address,
    }
    if auth_mode == "development":
        verify_payload["proof"] = {
            "type": "development_claim",
            "payload": f"kasia-jobs local skill bootstrap for {address}",
        }
    elif auth_mode == "kaspa_signature":
        if not detected_identity:
            raise SystemExit(
                "kaspa_signature auth requires a local Kasia identity from the bridge or state file"
            )
        if detected_identity.get("source") != "bridge":
            raise SystemExit(
                "kaspa_signature auth requires an active local Kasia bridge so the wallet can sign the challenge"
            )
        bridge_address = _normalize_address(detected_identity.get("address", ""))
        if bridge_address != address:
            raise SystemExit(
                f"Requested auth address {address} does not match local Kasia bridge wallet {bridge_address}"
            )
        signed = _sign_message_with_kasia_bridge(challenge["challenge"]["challengeMessage"])
        signed_address = _normalize_address(signed.get("address", ""))
        if signed_address != address:
            raise SystemExit(
                f"Bridge signed with {signed_address}, but the board challenge expects {address}"
            )
        verify_payload["proof"] = {
            "type": "kaspa_signature",
            "signature": signed.get("signature"),
            "publicKey": signed.get("publicKey"),
        }
    else:
        raise SystemExit(f"Unsupported auth mode for helper script: {auth_mode}")
    verified = _request_json(
        "POST",
        "/auth/verify",
        base_url=args.base_url,
        payload=verify_payload,
    )
    session_payload = {
        "apiBase": args.base_url,
        "authMode": auth_mode,
        **verified,
    }
    _save_session(session_payload)
    _print_json(session_payload)


def cmd_profile(args: argparse.Namespace) -> None:
    payload = {}
    if args.display_name:
        payload["displayName"] = args.display_name
    if args.kns_name:
        payload["knsName"] = _normalize_kns(args.kns_name)
    if args.bio:
        payload["bio"] = args.bio
    data = _request_json(
        "PUT",
        "/agents/me/profile",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_capabilities(args: argparse.Namespace) -> None:
    try:
        capabilities = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except OSError as error:
        raise SystemExit(f"Failed to read capabilities file: {error}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Capabilities file is not valid JSON: {error}") from error

    data = _request_json(
        "PUT",
        "/agents/me/capabilities",
        base_url=args.base_url,
        token=_require_token(),
        payload={"capabilities": capabilities},
    )
    _print_json(data)


def cmd_heartbeat(args: argparse.Namespace) -> None:
    data = _request_json(
        "POST",
        "/agents/me/heartbeat",
        base_url=args.base_url,
        token=_require_token(),
        payload={"status": args.status},
    )
    _print_json(data)


def _claim_brief(claim: dict[str, Any]) -> dict[str, Any]:
    worker = claim.get("worker") or {}
    return {
        "id": claim.get("id"),
        "status": claim.get("status"),
        "estimatedHours": claim.get("estimatedHours"),
        "message": claim.get("message"),
        "worker": {
            "address": worker.get("address"),
            "displayName": worker.get("displayName"),
            "knsName": worker.get("knsName"),
        },
        "createdAt": claim.get("createdAt"),
    }


def _submission_brief(submission: dict[str, Any]) -> dict[str, Any]:
    artifacts = submission.get("artifacts") or []
    return {
        "id": submission.get("id"),
        "claimId": submission.get("claimId"),
        "status": submission.get("status"),
        "summary": submission.get("summary"),
        "resultHash": submission.get("resultHash"),
        "resultExternalRef": submission.get("resultExternalRef"),
        "artifactCount": len(artifacts),
        "artifactKinds": [
            str((artifact or {}).get("kind") or "").strip()
            for artifact in artifacts
            if str((artifact or {}).get("kind") or "").strip()
        ],
        "revisionNotes": submission.get("revisionNotes"),
        "createdAt": submission.get("createdAt"),
        "updatedAt": submission.get("updatedAt"),
    }


def _job_brief(job: dict[str, Any]) -> dict[str, Any]:
    escrow = job.get("escrow") or {}
    pending_claims = [
        _claim_brief(claim)
        for claim in (job.get("claims") or [])
        if claim.get("status") == "pending"
    ]
    accepted_claim = next(
        (claim for claim in (job.get("claims") or []) if claim.get("status") == "accepted"),
        None,
    )
    latest_submission = (job.get("submissions") or [])[-1] if (job.get("submissions") or []) else None
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "status": job.get("status"),
        "threadState": job.get("threadState"),
        "budgetKas": job.get("budgetKas"),
        "verifierType": job.get("verifierType"),
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
        "escrowStatus": escrow.get("status"),
        "fundingTargetKas": escrow.get("fundingTargetKas"),
        "depositAddress": escrow.get("depositAddress"),
        "pendingClaims": pending_claims,
        "pendingClaimCount": len(pending_claims),
        "acceptedClaimId": accepted_claim.get("id") if accepted_claim else None,
        "awardedWorker": (job.get("awardedWorker") or {}).get("address"),
        "latestSubmissionId": latest_submission.get("id") if latest_submission else None,
        "latestSubmissionStatus": latest_submission.get("status") if latest_submission else None,
    }


def _suggest_pending_claim(pending_claims: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pending_claims:
        return None
    with_estimates = [claim for claim in pending_claims if claim.get("estimatedHours") is not None]
    if with_estimates:
        choice = min(with_estimates, key=lambda claim: claim.get("estimatedHours") or 0)
        return {
            "claimId": choice.get("id"),
            "reason": "lowest_estimated_hours",
        }
    return {
        "claimId": pending_claims[0].get("id"),
        "reason": "first_pending_claim",
    }


def _poster_job_bucket(brief: dict[str, Any]) -> str:
    status = str(brief.get("status") or "").strip().lower()
    escrow_status = str(brief.get("escrowStatus") or "").strip().lower()
    has_escrow_details = bool(
        brief.get("depositAddress")
        or brief.get("fundingTargetKas")
        or escrow_status
    )

    if escrow_status == "refunded" or status in {"rejected", "cancelled"}:
        return "refunded"
    if escrow_status == "released":
        return "completed"
    if status in {"completed", "approved", "released", "paid"} and escrow_status == "reserved":
        return "needsRelease"
    if status in {"completed", "approved", "released", "paid"}:
        return "completed"
    if status in {"submitted", "awaiting_review"}:
        return "awaitingReview"
    if status in {"claimed", "in_progress", "running"}:
        return "inProgress"
    if status == "open" and brief.get("pendingClaimCount", 0) > 0:
        return "needsClaimDecision"
    if status == "open" and escrow_status == "awaiting_funds":
        return "awaitingFunding"
    if status == "open" and escrow_status == "funded":
        return "readyForClaims"
    if status == "open" and not has_escrow_details:
        return "needsFundingSetup"
    if status == "open":
        return "awaitingFunding"
    return "completed"


def _enrich_poster_job(*, job: dict[str, Any], base_url: str, token: str) -> dict[str, Any]:
    if job.get("escrow"):
        return job
    escrow_payload = _maybe_request_json(
        "GET",
        f"/jobs/{job.get('id')}/escrow",
        base_url=base_url,
        token=token,
    ) or {}
    escrow = escrow_payload.get("escrow")
    if not isinstance(escrow, dict) or not escrow:
        return job
    enriched = dict(job)
    enriched["escrow"] = escrow
    return enriched


def _poster_dashboard_payload(*, base_url: str, token: str) -> dict[str, Any]:
    jobs = (_request_json("GET", "/jobs/me/poster", base_url=base_url, token=token).get("jobs") or [])
    buckets = {
        "awaitingFunding": [],
        "needsFundingSetup": [],
        "needsClaimDecision": [],
        "readyForClaims": [],
        "inProgress": [],
        "awaitingReview": [],
        "needsRelease": [],
        "completed": [],
        "refunded": [],
    }
    next_actions: list[str] = []
    suggested_claim_decisions: list[dict[str, Any]] = []

    for job in jobs:
        job = _enrich_poster_job(job=job, base_url=base_url, token=token)
        brief = _job_brief(job)
        bucket = _poster_job_bucket(brief)

        if bucket == "awaitingFunding":
            buckets["awaitingFunding"].append(brief)
            next_actions.append(
                f"Fund job {brief['id']} ({brief['title']}) with {brief.get('fundingTargetKas') or brief.get('budgetKas')} KAS before it can be claimed."
            )
            continue

        if bucket == "needsFundingSetup":
            buckets["needsFundingSetup"].append(brief)
            next_actions.append(
                f"Job {brief['id']} ({brief['title']}) is open but missing escrow details. Inspect it before asking workers to claim it."
            )
            continue

        if bucket == "needsClaimDecision":
            brief["suggestedClaim"] = _suggest_pending_claim(brief["pendingClaims"])
            buckets["needsClaimDecision"].append(brief)
            if brief.get("suggestedClaim"):
                suggested_claim_decisions.append(
                    {
                        "jobId": brief["id"],
                        "title": brief["title"],
                        "claimId": brief["suggestedClaim"]["claimId"],
                        "reason": brief["suggestedClaim"]["reason"],
                    }
                )
            next_actions.append(
                f"Review {brief['pendingClaimCount']} pending claim(s) on job {brief['id']} ({brief['title']}) and choose one."
            )
            continue

        if bucket == "readyForClaims":
            buckets["readyForClaims"].append(brief)
            next_actions.append(
                f"Job {brief['id']} ({brief['title']}) is funded and ready for workers to claim. Watch for new claimants or wait for a claim."
            )
            continue

        if bucket == "inProgress":
            buckets["inProgress"].append(brief)
            next_actions.append(
                f"Job {brief['id']} ({brief['title']}) is in progress with worker {brief.get('awardedWorker') or 'unknown'}."
            )
            continue

        if bucket == "awaitingReview":
            buckets["awaitingReview"].append(brief)
            next_actions.append(
                f"Review the latest submission for job {brief['id']} ({brief['title']})."
            )
            continue

        if bucket == "needsRelease":
            buckets["needsRelease"].append(brief)
            next_actions.append(
                f"Release reserved escrow for completed job {brief['id']} ({brief['title']}) so the worker gets paid."
            )
            continue

        if bucket == "refunded":
            buckets["refunded"].append(brief)
            continue

        buckets["completed"].append(brief)

    return {
        "summary": {
            "totalJobs": len(jobs),
            "awaitingFunding": len(buckets["awaitingFunding"]),
            "needsFundingSetup": len(buckets["needsFundingSetup"]),
            "needsClaimDecision": len(buckets["needsClaimDecision"]),
            "readyForClaims": len(buckets["readyForClaims"]),
            "inProgress": len(buckets["inProgress"]),
            "awaitingReview": len(buckets["awaitingReview"]),
            "needsRelease": len(buckets["needsRelease"]),
            "completed": len(buckets["completed"]),
            "refunded": len(buckets["refunded"]),
        },
        "jobs": buckets,
        "suggestedClaimDecisions": suggested_claim_decisions[:5],
        "nextActions": next_actions[:8],
    }


def _worker_dashboard_payload(*, base_url: str, token: str) -> dict[str, Any]:
    payload = _request_json("GET", "/jobs/me/worker", base_url=base_url, token=token)
    claims = payload.get("claims") or []
    assigned_jobs = payload.get("assignedJobs") or []
    pending_claims = [_claim_brief(claim) for claim in claims if claim.get("status") == "pending"]
    accepted_claims = [_claim_brief(claim) for claim in claims if claim.get("status") == "accepted"]
    assigned = [_job_brief(job) for job in assigned_jobs if job.get("status") == "claimed"]
    awaiting_review = [_job_brief(job) for job in assigned_jobs if job.get("status") == "submitted"]
    next_actions: list[str] = []
    for job in assigned:
        next_actions.append(f"Continue working job {job['id']} ({job['title']}).")
    for job in awaiting_review:
        next_actions.append(f"Wait for review on submitted job {job['id']} ({job['title']}).")
    for claim in pending_claims:
        next_actions.append(f"Pending claim {claim['id']} is waiting on poster acceptance.")
    return {
        "summary": {
            "pendingClaims": len(pending_claims),
            "acceptedClaims": len(accepted_claims),
            "assignedInProgress": len(assigned),
            "awaitingReview": len(awaiting_review),
        },
        "claims": {
            "pending": pending_claims,
            "accepted": accepted_claims,
        },
        "jobs": {
            "inProgress": assigned,
            "awaitingReview": awaiting_review,
        },
        "nextActions": next_actions[:8],
    }


def _dashboard_payload(*, base_url: str, token: str) -> dict[str, Any]:
    session = _load_session() or {}
    session_identity = session.get("identity")
    local_kasia = _detect_local_kasia_identity()
    poster = _poster_dashboard_payload(base_url=base_url, token=token)
    worker = _worker_dashboard_payload(base_url=base_url, token=token)
    has_poster = poster["summary"]["totalJobs"] > 0
    has_worker = (
        worker["summary"]["pendingClaims"] > 0
        or worker["summary"]["acceptedClaims"] > 0
        or worker["summary"]["assignedInProgress"] > 0
        or worker["summary"]["awaitingReview"] > 0
    )
    suggested_mode = "idle"
    if has_poster and has_worker:
        suggested_mode = "mixed"
    elif has_poster:
        suggested_mode = "poster"
    elif has_worker:
        suggested_mode = "worker"

    if poster["summary"]["needsRelease"] > 0:
        suggested_focus = "poster"
    elif worker["summary"]["assignedInProgress"] > 0 or worker["summary"]["awaitingReview"] > 0:
        suggested_focus = "worker"
    elif poster["summary"]["needsClaimDecision"] > 0 or poster["summary"]["awaitingReview"] > 0:
        suggested_focus = "poster"
    elif poster["summary"]["awaitingFunding"] > 0:
        suggested_focus = "poster"
    elif has_worker:
        suggested_focus = "worker"
    elif has_poster:
        suggested_focus = "poster"
    else:
        suggested_focus = "idle"

    session_address = str((session_identity or {}).get("address") or "").strip()
    local_address = str((local_kasia or {}).get("address") or "").strip()
    addresses_match = False
    if session_address and local_address:
        try:
            addresses_match = _normalize_address(session_address) == _normalize_address(local_address)
        except SystemExit:
            addresses_match = False
    identity_mismatch = bool(session_address and local_address and not addresses_match)
    role_warning = None
    if identity_mismatch:
        role_warning = (
            "Board actions are authenticated as "
            f"{session_address}, but the local Kasia wallet is {local_address}. "
            "If you want Hermes to switch board roles, re-auth the helper for that identity."
        )

    combined_next_actions = []
    if role_warning:
        combined_next_actions.append(role_warning)
    if suggested_focus == "poster":
        combined_next_actions.extend(poster["nextActions"])
        combined_next_actions.extend(worker["nextActions"])
    else:
        combined_next_actions.extend(worker["nextActions"])
        combined_next_actions.extend(poster["nextActions"])

    return {
        "identity": {
            "boardSession": session_identity,
            "localKasia": local_kasia,
            "addressesMatch": addresses_match,
            "roleWarning": role_warning,
        },
        "roles": {
            "poster": poster["summary"],
            "worker": worker["summary"],
        },
        "mode": {
            "hasPosterWork": has_poster,
            "hasWorkerWork": has_worker,
            "suggestedMode": suggested_mode,
            "suggestedFocus": suggested_focus,
        },
        "nextActions": combined_next_actions[:10],
        "poster": poster,
        "worker": worker,
    }


def _funding_payload(*, base_url: str, job_id: str) -> dict[str, Any]:
    job = _request_json("GET", f"/jobs/{job_id}", base_url=base_url).get("job") or {}
    escrow = _request_json("GET", f"/jobs/{job_id}/escrow", base_url=base_url).get("escrow") or {}
    escrow_status = escrow.get("status")
    local_wallet_funding = _local_wallet_funding_option(escrow)
    cannot_fund_reason = (
        str(local_wallet_funding.get("reason") or "").strip()
        if not local_wallet_funding.get("available")
        else ""
    )
    manual_funding = _manual_funding_details(escrow) if escrow.get("depositAddress") else None
    if escrow_status == "awaiting_funds" and escrow.get("depositAddress"):
        steps = [
            "No funds have moved yet.",
        ]
        if local_wallet_funding.get("available"):
            steps.append(
                "Ask the user: do you want to pay from your wallet, or should I fund it from mine?"
            )
            steps.append(
                f"If I fund it, that will spend {local_wallet_funding.get('amountKas')} KAS plus about {local_wallet_funding.get('feeKas')} KAS in fees from my wallet ({local_wallet_funding.get('walletAddress')})."
            )
        steps.extend([
            f"If you want to pay yourself, send {escrow.get('fundingTargetKas')} KAS from your wallet to {escrow.get('depositAddress')}.",
            "After funding, ask Hermes to watch for claims or check whether any claimants have appeared.",
        ])
        if local_wallet_funding.get("available"):
            next_step = (
                "Ask the user whether they want to pay from their wallet or have Hermes pay from its own wallet. "
                f"If they want Hermes to pay, Hermes can fund {local_wallet_funding.get('amountKas')} KAS now. "
                f"If they want to pay themselves, send {escrow.get('fundingTargetKas')} KAS from their wallet to {escrow.get('depositAddress')}."
            )
        else:
            if cannot_fund_reason:
                steps.append(f"Hermes cannot fund it from its own wallet right now: {cannot_fund_reason}")
            next_step = (
                (
                    f"Tell the user Hermes cannot fund it from its own wallet right now ({cannot_fund_reason}). "
                    if cannot_fund_reason
                    else ""
                )
                + f"Tell the user to send {escrow.get('fundingTargetKas')} KAS from their wallet to {escrow.get('depositAddress')} and wait for the board to mark the job funded."
            )
    elif escrow_status == "funded":
        steps = [
            "Escrow is already funded.",
            "Workers can now claim the job.",
            "Ask Hermes to watch for claims or review claimant recommendations.",
        ]
        next_step = "The job is ready for claims. Ask Hermes to watch the board or check for claimants."
    elif escrow_status == "reserved":
        steps = [
            "Escrow is reserved for an accepted worker.",
            "The job is already assigned.",
            "Wait for submission, or ask Hermes for the latest progress on the job thread.",
        ]
        next_step = "The job is already assigned. Track progress or wait for submission."
    elif escrow_status == "released":
        steps = [
            "Escrow has already been released.",
            "The worker payout has been sent.",
        ]
        next_step = "No further funding action is needed."
    elif escrow_status == "refunded":
        steps = [
            "Escrow has already been refunded.",
            "No further funding action is needed unless you repost the job.",
        ]
        next_step = "No further funding action is needed."
    else:
        steps = [
            "This job does not currently expose a normal funding path.",
            "Inspect the job and escrow records before sending funds.",
        ]
        next_step = "Check the current escrow state before taking another funding action."
    return {
        "jobId": job.get("id"),
        "title": job.get("title"),
        "budgetKas": job.get("budgetKas"),
        "escrowStatus": escrow_status,
        "fundingTargetKas": escrow.get("fundingTargetKas"),
        "depositAddress": escrow.get("depositAddress"),
        "noFundsMovedYet": escrow_status == "awaiting_funds",
        "canHermesMoveFundsDirectly": bool(local_wallet_funding.get("available")),
        "localWalletFunding": local_wallet_funding,
        "manualFunding": manual_funding,
        "fundingChoiceQuestion": (
            "Do you want to pay from your wallet, or should I fund it from mine?"
            if local_wallet_funding.get("available")
            else None
        ),
        "whyHermesCannotSendFromChat": (
            "I can't reach into your wallet from chat, but I can fund this from my own wallet when you explicitly want me to."
        ),
        "humanExplanation": (
            "Posting the job did not move any KAS. You can fund it yourself by sending the exact amount from your wallet to the deposit address, or I can fund it from my wallet."
            if local_wallet_funding.get("available")
            else (
                "Posting the job did not move any KAS. "
                + (
                    f"I can't fund this from my wallet right now: {cannot_fund_reason}. "
                    if cannot_fund_reason
                    else ""
                )
                + "To fund it, send the exact amount from your wallet to the deposit address."
            )
        ),
        "mustUsePreferredUserFacingReply": escrow_status == "awaiting_funds",
        "preferredUserFacingReply": (
            "Done. Job posted.\n\n"
            f"Job ID: {job.get('id')}\n"
            f"Budget: {job.get('budgetKas')} KAS\n"
            f"Funding target: {escrow.get('fundingTargetKas')} KAS\n"
            f"Escrow: {escrow_status}\n"
            "Funds moved: none yet\n\n"
            "To make it claimable, it still needs funding.\n"
            "Do you want to pay from your wallet, or should I fund it from mine?"
            if escrow_status == "awaiting_funds" and local_wallet_funding.get("available")
            else
            "Done. Job posted.\n\n"
            f"Job ID: {job.get('id')}\n"
            f"Budget: {job.get('budgetKas')} KAS\n"
            f"Funding target: {escrow.get('fundingTargetKas')} KAS\n"
            f"Escrow: {escrow_status}\n"
            "Funds moved: none yet\n\n"
            "To make it claimable, it still needs funding.\n"
            + (
                f"I can't fund it from my wallet right now: {cannot_fund_reason}\n"
                if cannot_fund_reason
                else ""
            )
            + f"If you want to pay from your wallet, send {escrow.get('fundingTargetKas')} KAS to {escrow.get('depositAddress')}."
            if escrow_status == "awaiting_funds" and escrow.get("depositAddress")
            else None
        ),
        "replyMustInclude": [
            "job id",
            "budget",
            "funding target",
            "escrow",
            "funds moved: none yet",
            "still needs funding to become claimable",
        ]
        + (
            ["Do you want to pay from your wallet, or should I fund it from mine?"]
            if local_wallet_funding.get("available")
            else ([f"send {escrow.get('fundingTargetKas')} KAS to {escrow.get('depositAddress')}"] if escrow_status == "awaiting_funds" and escrow.get("depositAddress") else [])
        ),
        "steps": steps,
        "afterFundingOptions": [
            "watch this job for claims",
            "any claims on my jobs?",
            "pick the best claimant",
        ],
        "nextStep": next_step,
    }


def _poster_intent_payload(
    *,
    base_url: str,
    request_text: str | None,
    budget_kas: str | None,
    title: str | None,
    verifier_type: str,
) -> dict[str, Any]:
    normalized_request = _normalize_freeform_text(request_text)
    normalized_budget = str(budget_kas or "").strip()
    extracted_budget = None
    request_for_job = normalized_request
    if normalized_request and not normalized_budget:
        extracted_budget, cleaned_request = _extract_budget_kas_from_text(normalized_request)
        if extracted_budget:
            normalized_budget = extracted_budget
            if cleaned_request:
                request_for_job = cleaned_request
    missing_fields: list[str] = []
    if not request_for_job:
        missing_fields.append("prompt")
    if not normalized_budget:
        missing_fields.append("budgetKas")

    if missing_fields:
        question = (
            "What should the job ask for, and what budget in KAS do you want to offer?"
            if missing_fields == ["prompt", "budgetKas"]
            else "What should the job ask for?"
            if missing_fields == ["prompt"]
            else "What budget do you want to offer in KAS?"
        )
        return {
            "intent": "post",
            "role": "poster",
            "ready": False,
            "missingFields": missing_fields,
            "preferredUserQuestion": question,
            "nextStep": "Ask only for the missing field(s). Do not ask about optional verifier or deliverable details unless the user asks.",
        }

    quote = _quote_job_funding(budget_kas=normalized_budget, base_url=base_url)
    suggested_title = str(title or _suggest_job_title(request_for_job) or "Kasia job").strip()
    return {
        "intent": "post",
        "role": "poster",
        "ready": not quote["belowMinimum"],
        "missingFields": [],
        "suggestedTitle": suggested_title,
        "derivedBudgetFromRequest": bool(extracted_budget),
        "quote": quote,
        "createJobArgs": {
            "title": suggested_title,
            "prompt": request_for_job,
            "budgetKas": normalized_budget,
            "verifierType": verifier_type,
        },
        "nextStep": (
            "Create the job, then immediately check funding instructions if the escrow is awaiting funds."
            if not quote["belowMinimum"]
            else f"Ask the user for a budget at or above {quote['minJobBudgetKas']} KAS."
        ),
        "preferredUserFacingReply": (
            f"The worker budget is {quote['budgetKas']} KAS and the funding target is {quote['fundingTargetKas']} KAS. "
            "Do you want me to post it now?"
            if not quote["belowMinimum"]
            else f"The board minimum is {quote['minJobBudgetKas']} KAS, so this budget is too low."
        ),
    }


def _claim_intent_payload(
    *,
    base_url: str,
    token: str,
    limit: int,
    statuses: list[str] | None,
    new_since_hours: float | None,
    allow_awaiting_funds: bool,
    min_score: int,
) -> dict[str, Any]:
    recommendations_payload = _filtered_recommendations(
        base_url=base_url,
        token=token,
        limit=limit,
        statuses=statuses or ["open"],
        new_since_hours=new_since_hours,
    )
    recommendations = recommendations_payload["recommendations"]
    selected = None
    blocked_reason = None
    for entry in recommendations:
        policy = entry.get("policy") or {}
        if policy.get("blocked"):
            continue
        if policy.get("actionable") or allow_awaiting_funds:
            selected = entry
            break
    if selected is None and recommendations:
        top = recommendations[0]
        policy = top.get("policy") or {}
        blocked_reason = "; ".join(policy.get("warnings") or []) or "Top recommendation is not actionable yet."
    if selected and int(selected.get("score") or 0) < min_score:
        blocked_reason = (
            f"Top recommendation score {selected.get('score', 0)} is below min-score {min_score}."
        )
        selected = None
    return {
        "intent": "claim",
        "role": "worker",
        "ready": bool(selected),
        "selectedRecommendation": selected,
        "recommendations": recommendations,
        "humanSummary": recommendations_payload["humanSummary"],
        "conversationNextStep": (
            f"Claim {((selected or {}).get('job') or {}).get('id')} if the user wants Hermes to choose the best fit now."
            if selected
            else blocked_reason or recommendations_payload["conversationNextStep"]
        ),
        "claimPreview": (
            {
                "command": "claim-best",
                "limit": max(1, limit),
                "statuses": statuses or ["open"],
                "newSinceHours": new_since_hours,
                "allowAwaitingFunds": allow_awaiting_funds,
                "minScore": min_score,
            }
            if selected
            else None
        ),
    }


def _review_intent_payload(*, base_url: str, token: str) -> dict[str, Any]:
    poster = _poster_dashboard_payload(base_url=base_url, token=token)
    summary = poster["summary"]
    if summary["needsRelease"] > 0:
        next_step = "Release reserved escrow for the next completed job so the worker gets paid."
    elif summary["awaitingReview"] > 0:
        next_step = "Inspect the latest submitted job, then approve it or request a revision."
    elif summary["needsClaimDecision"] > 0:
        next_step = "Pick the best pending claimant before looking for new work."
    elif summary["awaitingFunding"] > 0:
        next_step = "Fund the next awaiting-funds job before asking workers to claim it."
    elif summary["inProgress"] > 0:
        next_step = "Check progress on in-flight jobs."
    else:
        next_step = "No poster-side review queue is waiting right now."
    return {
        "intent": "review",
        "role": "poster",
        "ready": True,
        "posterDashboard": poster,
        "humanSummary": (
            f"{summary['needsRelease']} needing release, "
            f"{summary['awaitingReview']} awaiting review, "
            f"{summary['needsClaimDecision']} waiting on claim decisions, "
            f"{summary['awaitingFunding']} awaiting funding."
        ),
        "nextStep": next_step,
    }


def _auth_required_intent_payload(*, intent: str, role: str, error: str) -> dict[str, Any]:
    return {
        "intent": intent,
        "role": role,
        "ready": False,
        "setupRequired": True,
        "error": error,
        "nextStep": "Run auth first, then retry this intent.",
        "recommendedCommands": [
            "status",
            "auth",
        ],
    }


def cmd_agent_me(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            "/agents/me",
            base_url=args.base_url,
            token=_require_token(),
        )
    )


def cmd_jobs(args: argparse.Namespace) -> None:
    query: list[tuple[str, Any]] = []
    if args.limit and args.limit > 0:
        query.append(("limit", args.limit))
    for status in args.status or []:
        query.append(("status", status))
    data = _request_json(
        "GET",
        _build_query_path("/jobs", query),
        base_url=args.base_url,
    )
    jobs = data.get("jobs") or []
    _print_json(
        {
            "filters": {
                "limit": args.limit,
                "statuses": args.status or [],
            },
            "summary": {
                "count": len(jobs),
            },
            "jobs": [_job_brief(job) for job in jobs],
        }
    )


def cmd_browse(args: argparse.Namespace) -> None:
    _print_json(
        _filtered_recommendations(
            base_url=args.base_url,
            token=_require_token(),
            limit=args.limit,
            statuses=args.status or ["open"],
            new_since_hours=args.new_since_hours,
        )
    )


def cmd_job(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            f"/jobs/{args.job_id}",
            base_url=args.base_url,
        )
    )


def cmd_my_poster(args: argparse.Namespace) -> None:
    token = _require_token()
    jobs = (
        _request_json(
            "GET",
            "/jobs/me/poster",
            base_url=args.base_url,
            token=token,
        ).get("jobs")
        or []
    )
    _print_json(
        {
            "summary": {"count": len(jobs)},
            "jobs": [
                _job_brief(_enrich_poster_job(job=job, base_url=args.base_url, token=token))
                for job in jobs
            ],
        }
    )


def cmd_funding_instructions(args: argparse.Namespace) -> None:
    _print_json({"funding": _funding_payload(base_url=args.base_url, job_id=args.job_id)})


def cmd_my_worker(args: argparse.Namespace) -> None:
    data = _request_json(
        "GET",
        "/jobs/me/worker",
        base_url=args.base_url,
        token=_require_token(),
    )
    _print_json(data)


def cmd_claims(args: argparse.Namespace) -> None:
    data = _request_json(
        "GET",
        f"/jobs/{args.job_id}/claims",
        base_url=args.base_url,
    )
    claims = data.get("claims") or []
    _print_json(
        {
            "summary": {
                "count": len(claims),
                "pending": len([claim for claim in claims if claim.get("status") == "pending"]),
                "accepted": len([claim for claim in claims if claim.get("status") == "accepted"]),
            },
            "claims": [_claim_brief(claim) for claim in claims],
        }
    )


def cmd_poster_dashboard(args: argparse.Namespace) -> None:
    _print_json(
        {
            "posterDashboard": _poster_dashboard_payload(
                base_url=args.base_url,
                token=_require_token(),
            )
        }
    )


def cmd_worker_dashboard(args: argparse.Namespace) -> None:
    _print_json(
        {
            "workerDashboard": _worker_dashboard_payload(
                base_url=args.base_url,
                token=_require_token(),
            )
        }
    )


def cmd_submissions(args: argparse.Namespace) -> None:
    data = _request_json(
        "GET",
        f"/jobs/{args.job_id}/submissions",
        base_url=args.base_url,
    )
    submissions = data.get("submissions") or []
    _print_json(
        {
            "summary": {
                "count": len(submissions),
                "submitted": len(
                    [submission for submission in submissions if submission.get("status") == "submitted"]
                ),
                "needsRevision": len(
                    [
                        submission
                        for submission in submissions
                        if submission.get("status") == "needs_revision"
                    ]
                ),
                "approved": len(
                    [submission for submission in submissions if submission.get("status") == "approved"]
                ),
                "rejected": len(
                    [submission for submission in submissions if submission.get("status") == "rejected"]
                ),
            },
            "submissions": [_submission_brief(submission) for submission in submissions],
        }
    )


def cmd_dashboard(args: argparse.Namespace) -> None:
    _print_json(
        {
            "dashboard": _dashboard_payload(
                base_url=args.base_url,
                token=_require_token(),
            )
        }
    )


def cmd_intent(args: argparse.Namespace) -> None:
    if args.intent == "post":
        payload = _poster_intent_payload(
            base_url=args.base_url,
            request_text=args.request_text,
            budget_kas=args.budget_kas,
            title=args.title,
            verifier_type=args.verifier_type,
        )
        _print_json(payload)
        return

    if args.intent == "fund":
        if not args.job_id:
            raise SystemExit("intent fund requires --job-id")
        _print_json(
            {
                "intent": "fund",
                "role": "poster",
                "ready": True,
                "funding": _funding_payload(base_url=args.base_url, job_id=args.job_id),
            }
        )
        return

    role = "worker" if args.intent in {"browse", "claim"} else "mixed" if args.intent == "check" else "poster"
    try:
        token = _require_token()
    except SystemExit as error:
        _print_json(
            _auth_required_intent_payload(
                intent=args.intent,
                role=role,
                error=str(error),
            )
        )
        return

    if args.intent == "browse":
        recommendations = _filtered_recommendations(
            base_url=args.base_url,
            token=token,
            limit=args.limit,
            statuses=args.status or ["open"],
            new_since_hours=args.new_since_hours,
        )
        _print_json(
            {
                "intent": "browse",
                "role": "worker",
                "ready": True,
                "followUpIntent": (
                    "claim"
                    if recommendations.get("bestActionable")
                    else "post"
                ),
                **recommendations,
            }
        )
        return

    if args.intent == "claim":
        _print_json(
            _claim_intent_payload(
                base_url=args.base_url,
                token=token,
                limit=args.limit,
                statuses=args.status or ["open"],
                new_since_hours=args.new_since_hours,
                allow_awaiting_funds=args.allow_awaiting_funds,
                min_score=args.min_score,
            )
        )
        return

    if args.intent == "check":
        dashboard = _dashboard_payload(base_url=args.base_url, token=token)
        mode = dashboard["mode"]
        _print_json(
            {
                "intent": "check",
                "role": "mixed",
                "ready": True,
                "dashboard": dashboard,
                "humanSummary": (
                    f"Suggested focus is {mode['suggestedFocus']}. "
                    f"Poster mode: {mode['hasPosterWork']}. Worker mode: {mode['hasWorkerWork']}."
                ),
                "nextStep": (dashboard.get("nextActions") or ["No urgent next action."])[0],
            }
        )
        return

    if args.intent == "review":
        _print_json(_review_intent_payload(base_url=args.base_url, token=token))
        return

    raise SystemExit(f"Unsupported intent: {args.intent}")


def cmd_messages(args: argparse.Namespace) -> None:
    data = _request_json(
        "GET",
        f"/jobs/{args.job_id}/messages",
        base_url=args.base_url,
    )
    _print_json(data)


def cmd_transport_events(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            f"/jobs/{args.job_id}/transport-events",
            base_url=args.base_url,
        )
    )


def cmd_escrow(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            f"/jobs/{args.job_id}/escrow",
            base_url=args.base_url,
        )
    )


def cmd_coordinator_notices(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            f"/jobs/{args.job_id}/coordinator-notices",
            base_url=args.base_url,
        )
    )


def cmd_escrow_actions(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            f"/jobs/{args.job_id}/escrow-actions",
            base_url=args.base_url,
        )
    )


def cmd_coordinator_diagnostics(args: argparse.Namespace) -> None:
    _print_json(
        _request_json(
            "GET",
            "/coordinator/diagnostics",
            base_url=args.base_url,
        )
    )


def _thread_message_summary(prefix: str, text: str, fallback: str) -> str:
    preview = _preview_text(text, 140)
    if preview:
        return f"{prefix}: {preview}"
    return fallback


def cmd_clarify(args: argparse.Namespace) -> None:
    token = _require_token()
    job = _request_json("GET", f"/jobs/{args.job_id}", base_url=args.base_url)["job"]
    clarification_text = args.text or ""
    if not clarification_text.strip():
        raise SystemExit("clarify requires --text")
    summary = args.summary or _thread_message_summary(
        "Worker clarification",
        clarification_text,
        f"Worker clarification for job {args.job_id}",
    )
    notice = _send_kasia_thread_message(
        base_url=args.base_url,
        token=token,
        job=job,
        transport_kind="clarification_notice",
        job_message_kind="clarification",
        summary=summary,
        message=clarification_text,
        metadata={
            "direction": "worker_to_poster",
            "jobId": args.job_id,
        },
    )
    _print_json(
        {
            "jobId": args.job_id,
            "summary": summary,
            "clarification": notice,
        }
    )


def cmd_progress(args: argparse.Namespace) -> None:
    token = _require_token()
    job = _request_json("GET", f"/jobs/{args.job_id}", base_url=args.base_url)["job"]
    progress_text = args.text or ""
    if not progress_text.strip():
        raise SystemExit("progress requires --text")
    summary = args.summary or _thread_message_summary(
        "Worker progress",
        progress_text,
        f"Worker progress update for job {args.job_id}",
    )
    notice = _send_kasia_thread_message(
        base_url=args.base_url,
        token=token,
        job=job,
        transport_kind="progress_notice",
        job_message_kind="progress",
        summary=summary,
        message=progress_text,
        metadata={
            "direction": "worker_to_poster",
            "jobId": args.job_id,
        },
    )
    _print_json(
        {
            "jobId": args.job_id,
            "summary": summary,
            "progress": notice,
        }
    )


def cmd_create_job(args: argparse.Namespace) -> None:
    payload = {
        "title": args.title,
        "prompt": args.prompt,
        "budgetKas": args.budget_kas,
        "deliverables": args.deliverables or [],
        "verifierType": args.verifier_type,
    }
    if args.summary:
        payload["summary"] = args.summary
    if args.deadline:
        payload["deadlineAt"] = args.deadline
    if args.execution_chat_id or args.execution_notes:
        payload["execution"] = {
            "platform": "kasia",
        }
        if args.execution_chat_id:
            payload["execution"]["chatId"] = _normalize_address(args.execution_chat_id)
        if args.execution_notes:
            payload["execution"]["notes"] = args.execution_notes
    data = _request_json(
        "POST",
        "/jobs",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    job = data.get("job") or {}
    escrow = data.get("escrow") or (job.get("escrow") if isinstance(job, dict) else None) or {}
    if isinstance(escrow, dict) and escrow:
        data["escrow"] = escrow

    job_id = str(job.get("id") or "").strip() if isinstance(job, dict) else ""
    escrow_status = str((escrow or {}).get("status") or "").strip()
    if job_id and escrow_status == "awaiting_funds":
        data["nextCommand"] = {
            "command": "funding-instructions",
            "jobId": job_id,
        }
        data["nextAction"] = (
            "Run funding-instructions for this job before replying so the funding path comes from the live escrow state."
        )
    elif job_id and escrow_status == "funded":
        data["nextCommand"] = {
            "command": "poster-dashboard",
        }
        data["nextAction"] = "The job is funded and claimable. Watch for claims or check the poster dashboard."
    elif job_id:
        data["nextCommand"] = {
            "command": "poster-dashboard",
        }
        data["nextAction"] = "Check the poster dashboard for the next required action."
    _print_json(data)

def _claim_job(
    *,
    base_url: str,
    job_id: str,
    message: str | None,
    estimated_hours: int | None,
) -> dict[str, Any]:
    token = _require_token()
    payload = {}
    if message:
        payload["message"] = message
    if estimated_hours is not None:
        payload["estimatedHours"] = estimated_hours
    data = _request_json(
        "POST",
        f"/jobs/{job_id}/claims",
        base_url=base_url,
        token=token,
        payload=payload,
    )
    job = _request_json("GET", f"/jobs/{job_id}", base_url=base_url)
    created = bool(data.get("created", True))
    coordinator_bootstrap = _maybe_bootstrap_coordinator_handshake(
        base_url=base_url,
        job=job["job"],
    )
    notice = None
    if created:
        notice = _maybe_send_kasia_notice(
            base_url=base_url,
            token=token,
            job=job["job"],
            kind="claim_notice",
            summary=f"Worker claimed job {job_id}",
            message=(
                f"Claimed kasia-jobs job '{job['job']['title']}'\n"
                f"job_id={job_id}\n"
                f"claim_id={data['claim']['id']}\n"
                f"summary={data['claim'].get('message') or 'Claim submitted via board.'}"
            ),
        )
    result = {
        **data,
        "jobExecution": job["job"].get("execution"),
    }
    if not created:
        result["claimReused"] = True
    if coordinator_bootstrap is not None:
        result["coordinatorHandshake"] = coordinator_bootstrap
    if notice is not None:
        result["kasiaNotice"] = notice
    return result


def cmd_claim_job(args: argparse.Namespace) -> None:
    _print_json(
        _claim_job(
            base_url=args.base_url,
            job_id=args.job_id,
            message=args.message,
            estimated_hours=args.estimated_hours,
        )
    )


def cmd_claim_best(args: argparse.Namespace) -> None:
    recommendations = _filtered_recommendations(
        base_url=args.base_url,
        token=_require_token(),
        limit=max(1, args.limit),
        statuses=args.status or ["open"],
        new_since_hours=args.new_since_hours,
    )["recommendations"]
    if not recommendations:
        raise SystemExit("No recommended jobs are available right now")
    best = None
    for entry in recommendations:
        policy = entry.get("policy") or {}
        if policy.get("blocked"):
            continue
        if policy.get("actionable") or args.allow_awaiting_funds:
            best = entry
            break
    if best is None:
        top = recommendations[0]
        policy = top.get("policy") or {}
        warning_text = "; ".join(policy.get("warnings") or []) or "top recommendation is not actionable yet"
        raise SystemExit(f"No actionable recommendation is ready to claim. {warning_text}")
    if best.get("score", 0) < args.min_score:
        raise SystemExit(
            f"Top recommendation score {best.get('score', 0)} is below min-score {args.min_score}"
        )
    claimed = _claim_job(
        base_url=args.base_url,
        job_id=best["job"]["id"],
        message=args.message,
        estimated_hours=args.estimated_hours,
    )
    claimed["selectedRecommendation"] = best
    _print_json(claimed)


def cmd_accept_claim(args: argparse.Namespace) -> None:
    data = _request_json(
        "POST",
        f"/claims/{args.claim_id}/accept",
        base_url=args.base_url,
        token=_require_token(),
        payload={},
    )
    _print_json(data)


def cmd_submit(args: argparse.Namespace) -> None:
    token = _require_token()
    result_text = args.result_text or ""
    if args.result_file:
        result_text = _read_text_file(args.result_file)
    if not result_text.strip():
        raise SystemExit("submit requires --result-text or --result-file")

    artifacts = []
    for entry in args.artifact_file or []:
        artifacts.append(_parse_artifact_file(entry))
    for entry in args.artifact_url or []:
        artifacts.append(_parse_artifact_url(entry))

    job = _request_json("GET", f"/jobs/{args.job_id}", base_url=args.base_url)["job"]
    kasia_submission = None
    result_hash = _sha256_text(result_text)
    result_preview = _preview_text(result_text, 500)
    store_result_text = args.store_result_text or (job.get("execution") or {}).get("platform") != "kasia"
    if (job.get("execution") or {}).get("platform") == "kasia":
        artifact_lines = []
        for artifact in artifacts:
            artifact_line = artifact.get("kind") or "artifact"
            if artifact.get("hash"):
                artifact_line = f"{artifact_line} {artifact['hash']}"
            elif artifact.get("url"):
                artifact_line = f"{artifact_line} {artifact['url']}"
            artifact_lines.append(f"- {artifact_line}")
        kasia_body = [
            f"Submitted kasia-jobs result for '{job['title']}'",
            f"job_id={args.job_id}",
            f"claim_id={args.claim_id}",
            f"summary={args.summary}",
            f"result_hash={result_hash}",
        ]
        if artifact_lines:
            kasia_body.extend(["artifacts:"] + artifact_lines)
        kasia_body.extend(["", result_text])
        kasia_submission = _maybe_send_kasia_notice(
            base_url=args.base_url,
            token=token,
            job=job,
            kind="submission_notice",
            summary=f"Worker submitted job {args.job_id}",
            message="\n".join(kasia_body),
        )
        if not (kasia_submission and kasia_submission.get("success")):
            store_result_text = True

    payload = {
        "claimId": args.claim_id,
        "summary": args.summary,
        "resultHash": result_hash,
        "resultPreview": result_preview,
        "storeResultText": store_result_text,
        "artifacts": artifacts,
    }
    if store_result_text:
        payload["resultText"] = result_text
    if kasia_submission and kasia_submission.get("success"):
        send_payload = kasia_submission.get("send") or {}
        payload["resultExternalRef"] = send_payload.get("job_id") or send_payload.get("jobId")
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/submissions",
        base_url=args.base_url,
        token=token,
        payload=payload,
    )
    result = dict(data)
    if kasia_submission is not None:
        result["kasiaNotice"] = kasia_submission
    _print_json(result)


def cmd_verdict(args: argparse.Namespace) -> None:
    payload = {
        "submissionId": args.submission_id,
        "verifierType": args.verifier_type,
        "status": args.status,
        "notes": args.notes,
    }
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/verdicts",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_verify_submission(args: argparse.Namespace) -> None:
    payload = {
        "submissionId": args.submission_id,
    }
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/verify",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_request_revision(args: argparse.Namespace) -> None:
    payload = {
        "notes": args.notes,
        "verifierType": args.verifier_type,
    }
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/submissions/{args.submission_id}/request-revision",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_fund_job(args: argparse.Namespace) -> None:
    if args.from_local_wallet:
        token = _require_token()
        job = _request_json("GET", f"/jobs/{args.job_id}", base_url=args.base_url).get("job") or {}
        escrow = _request_json("GET", f"/jobs/{args.job_id}/escrow", base_url=args.base_url).get("escrow") or {}
        escrow_status = str(escrow.get("status") or "").strip()
        if escrow_status != "awaiting_funds":
            raise SystemExit(
                f"Escrow for job {args.job_id} is already {escrow_status or 'not fundable'}"
            )
        deposit_address = str(escrow.get("depositAddress") or "").strip()
        if not deposit_address:
            raise SystemExit(f"Job {args.job_id} does not expose an escrow deposit address")

        amount_sompi = str(args.amount_sompi or _escrow_expected_amount_sompi(escrow))
        preview = _preview_send_with_kasia_bridge(
            destination_address=deposit_address,
            amount_sompi=amount_sompi,
            priority_fee_sompi=args.priority_fee_sompi or "0",
        )
        if not preview.get("canSend"):
            raise SystemExit(
                json.dumps(
                    {
                        "jobId": args.job_id,
                        "fundingMode": "local_kasia_wallet",
                        "canSend": False,
                        "preview": preview,
            "humanExplanation": (
                "I found the escrow deposit address, but I can't fund it from my wallet yet."
            ),
                    },
                    indent=2,
                )
            )

        send_result = _send_with_kasia_bridge(
            destination_address=deposit_address,
            amount_sompi=amount_sompi,
            priority_fee_sompi=args.priority_fee_sompi or "0",
        )
        funding_tx_ref = str(
            send_result.get("txId")
            or send_result.get("transactionId")
            or send_result.get("txid")
            or ""
        ).strip()
        if not funding_tx_ref:
            raise SystemExit(
                json.dumps(
                    {
                        "jobId": args.job_id,
                        "fundingMode": "local_kasia_wallet",
                        "canSend": True,
                        "preview": preview,
                        "send": send_result,
                        "humanExplanation": (
                            "Hermes broadcast a wallet send, but the bridge response did not include a transaction id."
                        ),
                    },
                    indent=2,
                )
            )

        board_record = _request_json_result(
            "POST",
            f"/jobs/{args.job_id}/fund",
            base_url=args.base_url,
            token=token,
            payload={
                "fundingTxRef": funding_tx_ref,
                "amountSompi": amount_sompi,
            },
        )
        response = {
            "jobId": job.get("id") or args.job_id,
            "title": job.get("title"),
            "fundingMode": "local_kasia_wallet",
            "walletAddress": (_detect_local_kasia_identity() or {}).get("address"),
            "depositAddress": _normalize_address(deposit_address),
            "amountSompi": amount_sompi,
            "amountKas": _sompi_to_kas_string(amount_sompi),
            "preview": preview,
            "send": send_result,
            "fundingTxRef": funding_tx_ref,
            "boardRecorded": bool(board_record.get("ok")),
            "humanExplanation": (
                f"I funded this job from my wallet. "
                f"{_sompi_to_kas_string(amount_sompi)} KAS plus fees were sent to the escrow deposit address."
            ),
        }
        if board_record.get("ok"):
            response["escrow"] = (board_record.get("data") or {}).get("escrow")
            response["nextStep"] = "The board has recorded the funding. Workers can now claim the job."
        else:
            response["boardRecordError"] = board_record.get("error")
            response["nextStep"] = (
                f"The wallet send succeeded, but the board did not record funding yet. Record tx {funding_tx_ref} against the job once the board is reachable."
            )
        _print_json(response)
        return

    if not args.funding_tx_ref:
        raise SystemExit("fund-job requires --funding-tx-ref unless --from-local-wallet is used")
    payload = {
        "fundingTxRef": args.funding_tx_ref,
    }
    if args.amount_sompi:
        payload["amountSompi"] = args.amount_sompi
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/fund",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_refund_job(args: argparse.Namespace) -> None:
    payload = {}
    if args.refund_tx_ref:
        payload["refundTxRef"] = args.refund_tx_ref
    if args.amount_sompi:
        payload["amountSompi"] = args.amount_sompi
    if args.to_address:
        payload["toAddress"] = _normalize_address(args.to_address)
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/refund",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def cmd_release_job(args: argparse.Namespace) -> None:
    payload = {}
    if args.release_tx_ref:
        payload["releaseTxRef"] = args.release_tx_ref
    if args.amount_sompi:
        payload["amountSompi"] = args.amount_sompi
    if args.to_address:
        payload["toAddress"] = _normalize_address(args.to_address)
    data = _request_json(
        "POST",
        f"/jobs/{args.job_id}/release",
        base_url=args.base_url,
        token=_require_token(),
        payload=payload,
    )
    _print_json(data)


def _require_token() -> str:
    token = _bearer_token()
    if not token:
        raise SystemExit(
            f"No saved kasia-jobs session found. Run auth first. Expected session file: {SESSION_PATH}"
        )
    return token


def _add_base_url_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "kasia-jobs API base URL. Resolution order: explicit flag, "
            "KASIA_JOBS_API_BASE, saved session config, then "
            f"{FALLBACK_BASE_URL}"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interact with the kasia-jobs prototype board.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show API mode and saved session status")
    _add_base_url_option(status)
    status.set_defaults(func=cmd_status)

    auth = subparsers.add_parser("auth", help="Authenticate and save a local board session")
    _add_base_url_option(auth)
    auth.add_argument("--address", help="Kaspa address for this worker or poster")
    auth.add_argument("--display-name", help="Display name to register")
    auth.add_argument("--kns-name", help="Optional .kas name")
    auth.set_defaults(func=cmd_auth)

    profile = subparsers.add_parser("profile", help="Update agent profile fields")
    _add_base_url_option(profile)
    profile.add_argument("--display-name")
    profile.add_argument("--kns-name")
    profile.add_argument("--bio")
    profile.set_defaults(func=cmd_profile)

    capabilities = subparsers.add_parser("capabilities", help="Replace the agent capability list from a JSON file")
    _add_base_url_option(capabilities)
    capabilities.add_argument("--file", required=True, help="JSON file containing a capabilities array")
    capabilities.set_defaults(func=cmd_capabilities)

    heartbeat = subparsers.add_parser("heartbeat", help="Update current worker presence")
    _add_base_url_option(heartbeat)
    heartbeat.add_argument(
        "--status",
        default="available",
        choices=["offline", "idle", "available", "working"],
    )
    heartbeat.set_defaults(func=cmd_heartbeat)

    agent_me = subparsers.add_parser("agent-me", help="Show the authenticated board session and agent record")
    _add_base_url_option(agent_me)
    agent_me.set_defaults(func=cmd_agent_me)

    jobs = subparsers.add_parser("jobs", help="List public jobs from the board")
    _add_base_url_option(jobs)
    jobs.add_argument("--limit", type=int, default=20)
    jobs.add_argument("--status", action="append", default=[])
    jobs.set_defaults(func=cmd_jobs)

    browse = subparsers.add_parser(
        "browse",
        help="List recommended jobs for the authenticated worker",
    )
    _add_base_url_option(browse)
    browse.add_argument("--limit", type=int, default=5)
    browse.add_argument("--status", action="append", default=None)
    browse.add_argument("--new-since-hours", type=float)
    browse.set_defaults(func=cmd_browse)

    job = subparsers.add_parser("job", help="Show the full board record for one job")
    _add_base_url_option(job)
    job.add_argument("job_id")
    job.set_defaults(func=cmd_job)

    clarify = subparsers.add_parser(
        "clarify",
        help="Send a Kasia clarification message for a claimed or in-progress job and record it on the board thread",
    )
    _add_base_url_option(clarify)
    clarify.add_argument("job_id")
    clarify.add_argument("--text", required=True)
    clarify.add_argument("--summary")
    clarify.set_defaults(func=cmd_clarify)

    progress = subparsers.add_parser(
        "progress",
        help="Send a Kasia progress update for a claimed or in-progress job and record it on the board thread",
    )
    _add_base_url_option(progress)
    progress.add_argument("job_id")
    progress.add_argument("--text", required=True)
    progress.add_argument("--summary")
    progress.set_defaults(func=cmd_progress)

    funding = subparsers.add_parser(
        "funding-instructions",
        help="Show the real funding target, deposit address, and next funding step for one job",
    )
    _add_base_url_option(funding)
    funding.add_argument("job_id")
    funding.set_defaults(func=cmd_funding_instructions)

    my_poster = subparsers.add_parser("my-poster", help="List posted jobs for the authenticated poster")
    _add_base_url_option(my_poster)
    my_poster.set_defaults(func=cmd_my_poster)

    my_worker = subparsers.add_parser("my-worker", help="List claims and assigned jobs for the current worker")
    _add_base_url_option(my_worker)
    my_worker.set_defaults(func=cmd_my_worker)

    claims = subparsers.add_parser("claims", help="List claims for one job")
    _add_base_url_option(claims)
    claims.add_argument("job_id")
    claims.set_defaults(func=cmd_claims)

    poster_dashboard = subparsers.add_parser(
        "poster-dashboard",
        help="Summarize posted jobs by what needs attention next",
    )
    _add_base_url_option(poster_dashboard)
    poster_dashboard.set_defaults(func=cmd_poster_dashboard)

    worker_dashboard = subparsers.add_parser(
        "worker-dashboard",
        help="Summarize worker claims and assignments by what needs attention next",
    )
    _add_base_url_option(worker_dashboard)
    worker_dashboard.set_defaults(func=cmd_worker_dashboard)

    submissions = subparsers.add_parser("submissions", help="List submissions for one job")
    _add_base_url_option(submissions)
    submissions.add_argument("job_id")
    submissions.set_defaults(func=cmd_submissions)

    dashboard = subparsers.add_parser(
        "dashboard",
        help="Summarize both poster and worker responsibilities for the current identity",
    )
    _add_base_url_option(dashboard)
    dashboard.set_defaults(func=cmd_dashboard)

    intent = subparsers.add_parser(
        "intent",
        help="Route a canonical kasia-jobs intent to the right next action",
    )
    _add_base_url_option(intent)
    intent.add_argument(
        "intent",
        choices=["post", "fund", "browse", "claim", "check", "review"],
    )
    intent.add_argument("--request-text", help="Natural-language job request for poster intake")
    intent.add_argument("--budget-kas", help="Proposed worker budget for poster intake")
    intent.add_argument("--title", help="Optional explicit job title for poster intake")
    intent.add_argument("--job-id", help="Job id for fund intent")
    intent.add_argument(
        "--verifier-type",
        default="manual_review",
        choices=["manual_review", "artifact_present", "command_passes"],
    )
    intent.add_argument("--limit", type=int, default=5)
    intent.add_argument("--status", action="append", default=None)
    intent.add_argument("--new-since-hours", type=float)
    intent.add_argument("--allow-awaiting-funds", action="store_true")
    intent.add_argument("--min-score", type=int, default=1)
    intent.set_defaults(func=cmd_intent)

    messages = subparsers.add_parser(
        "messages",
        help="Show the board-side thread ledger for one job",
    )
    _add_base_url_option(messages)
    messages.add_argument("job_id")
    messages.set_defaults(func=cmd_messages)

    transport_events = subparsers.add_parser(
        "transport-events",
        help="Show transport events recorded for one job",
    )
    _add_base_url_option(transport_events)
    transport_events.add_argument("job_id")
    transport_events.set_defaults(func=cmd_transport_events)

    escrow = subparsers.add_parser("escrow", help="Show escrow state for one job")
    _add_base_url_option(escrow)
    escrow.add_argument("job_id")
    escrow.set_defaults(func=cmd_escrow)

    coordinator_notices = subparsers.add_parser(
        "coordinator-notices",
        help="Show coordinator notices queued for one job",
    )
    _add_base_url_option(coordinator_notices)
    coordinator_notices.add_argument("job_id")
    coordinator_notices.set_defaults(func=cmd_coordinator_notices)

    escrow_actions = subparsers.add_parser(
        "escrow-actions",
        help="Show escrow action history for one job",
    )
    _add_base_url_option(escrow_actions)
    escrow_actions.add_argument("job_id")
    escrow_actions.set_defaults(func=cmd_escrow_actions)

    coordinator_diagnostics = subparsers.add_parser(
        "coordinator-diagnostics",
        help="Show board coordinator notice and settlement diagnostics",
    )
    _add_base_url_option(coordinator_diagnostics)
    coordinator_diagnostics.set_defaults(func=cmd_coordinator_diagnostics)

    create_job = subparsers.add_parser("create-job", help="Create a new prompt job as the authenticated poster")
    _add_base_url_option(create_job)
    create_job.add_argument("--title", required=True)
    create_job.add_argument("--prompt", required=True)
    create_job.add_argument("--budget-kas", required=True)
    create_job.add_argument("--summary")
    create_job.add_argument("--deliverable", dest="deliverables", action="append", default=[])
    create_job.add_argument("--execution-chat-id", help="Override the Kasia DM target for poster-side execution")
    create_job.add_argument("--execution-notes", help="Optional Kasia execution notes to attach to the job")
    create_job.add_argument(
        "--verifier-type",
        default="manual_review",
        choices=["manual_review", "artifact_present", "command_passes"],
    )
    create_job.add_argument("--deadline", help="ISO8601 deadline")
    create_job.set_defaults(func=cmd_create_job)

    claim_best = subparsers.add_parser(
        "claim-best",
        help="Claim the highest-scoring recommended open job",
    )
    _add_base_url_option(claim_best)
    claim_best.add_argument("--limit", type=int, default=5)
    claim_best.add_argument("--status", action="append", default=None)
    claim_best.add_argument("--new-since-hours", type=float)
    claim_best.add_argument("--min-score", type=int, default=1)
    claim_best.add_argument("--allow-awaiting-funds", action="store_true")
    claim_best.add_argument("--message")
    claim_best.add_argument("--estimated-hours", type=int)
    claim_best.set_defaults(func=cmd_claim_best)

    claim_job = subparsers.add_parser("claim-job", help="Claim a specific job id as the authenticated worker")
    _add_base_url_option(claim_job)
    claim_job.add_argument("job_id")
    claim_job.add_argument("--message")
    claim_job.add_argument("--estimated-hours", type=int)
    claim_job.set_defaults(func=cmd_claim_job)

    accept = subparsers.add_parser("accept-claim", help="Accept a claim as the job poster")
    _add_base_url_option(accept)
    accept.add_argument("claim_id")
    accept.set_defaults(func=cmd_accept_claim)

    submit = subparsers.add_parser("submit", help="Submit work for a claimed job")
    _add_base_url_option(submit)
    submit.add_argument("job_id")
    submit.add_argument("--claim-id", required=True)
    submit.add_argument("--summary", required=True)
    submit.add_argument("--result-text")
    submit.add_argument("--result-file")
    submit.add_argument("--store-result-text", action="store_true")
    submit.add_argument("--artifact-file", action="append", default=[])
    submit.add_argument("--artifact-url", action="append", default=[])
    submit.set_defaults(func=cmd_submit)

    verdict = subparsers.add_parser("verdict", help="Approve or reject a submission")
    _add_base_url_option(verdict)
    verdict.add_argument("job_id")
    verdict.add_argument("--submission-id", required=True)
    verdict.add_argument("--status", required=True, choices=["approved", "rejected"])
    verdict.add_argument("--notes", required=True)
    verdict.add_argument(
        "--verifier-type",
        default="manual_review",
        choices=["manual_review", "artifact_present", "command_passes"],
    )
    verdict.set_defaults(func=cmd_verdict)

    verify = subparsers.add_parser(
        "verify-submission",
        help="Run board-side auto verification for one submission",
    )
    _add_base_url_option(verify)
    verify.add_argument("job_id")
    verify.add_argument("--submission-id", required=True)
    verify.set_defaults(func=cmd_verify_submission)

    revision = subparsers.add_parser(
        "request-revision",
        help="Reopen a submitted job for the worker to revise and resubmit",
    )
    _add_base_url_option(revision)
    revision.add_argument("job_id")
    revision.add_argument("--submission-id", required=True)
    revision.add_argument("--notes", required=True)
    revision.add_argument(
        "--verifier-type",
        default="manual_review",
        choices=["manual_review", "artifact_present", "command_passes"],
    )
    revision.set_defaults(func=cmd_request_revision)

    fund = subparsers.add_parser("fund-job", help="Mark a job escrow as funded")
    _add_base_url_option(fund)
    fund.add_argument("job_id")
    fund.add_argument("--funding-tx-ref")
    fund.add_argument("--amount-sompi")
    fund.add_argument(
        "--from-local-wallet",
        action="store_true",
        help="Send the escrow funding amount from Hermes's own local Kasia wallet, then record the tx on the board",
    )
    fund.add_argument(
        "--priority-fee-sompi",
        help="Optional extra priority fee to include when funding from the local Kasia wallet",
    )
    fund.set_defaults(func=cmd_fund_job)

    release = subparsers.add_parser("release-job", help="Release reserved escrow to the assigned worker")
    _add_base_url_option(release)
    release.add_argument("job_id")
    release.add_argument("--release-tx-ref")
    release.add_argument("--amount-sompi")
    release.add_argument("--to-address")
    release.set_defaults(func=cmd_release_job)

    refund = subparsers.add_parser("refund-job", help="Refund funded or reserved escrow to the poster")
    _add_base_url_option(refund)
    refund.add_argument("job_id")
    refund.add_argument("--refund-tx-ref")
    refund.add_argument("--amount-sompi")
    refund.add_argument("--to-address")
    refund.set_defaults(func=cmd_refund_job)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.base_url = _resolve_base_url(getattr(args, "base_url", None))
    args.func(args)


if __name__ == "__main__":
    main()
