from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "messaging"
    / "kasia"
    / "scripts"
    / "kasia.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("kasia_skill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parser_exposes_kasia_operator_surface():
    mod = load_module()
    parser = mod.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    commands = set(subparsers.choices)

    assert "status" in commands
    assert "address" in commands
    assert "wallet" in commands
    assert "tx-check" in commands
    assert "resolve" in commands
    assert "chat" in commands
    assert "conversation" in commands
    assert "handshake-initiate" in commands
    assert "handshake-respond" in commands
    assert "send" in commands
    assert "send-status" in commands
    assert "sign-message" in commands
    assert "send-kaspa-preview" in commands
    assert "send-kaspa" in commands


def test_wallet_payload_formats_balances():
    mod = load_module()

    payload = mod._wallet_payload(
        {
            "wallet": {
                "address": "kaspa:qwallet123",
                "network": "mainnet",
                "fundingState": "low",
            },
            "balanceSnapshot": {
                "onChainBalanceSompi": "97123696",
                "availableMatureBalanceSompi": "97123696",
                "availablePendingBalanceSompi": "0",
                "trackedPendingBalanceSompi": "0",
                "matureUtxoCount": 2,
                "pendingUtxoCount": 0,
                "trackedPendingUtxoCount": 0,
                "updatedAtMs": 1_710_000_000_000,
            },
            "recommendedMinBalanceSompi": "40000000",
            "minimumMessageAmountSompi": "1000000",
        }
    )

    assert payload["address"] == "kaspa:qwallet123"
    assert payload["fundingState"] == "low"
    assert payload["onChainBalanceKas"] == "0.97123696"
    assert payload["availableMatureBalanceKas"] == "0.97123696"
    assert payload["recommendedMinBalanceKas"] == "0.4"
    assert payload["minimumMessageAmountKas"] == "0.01"
    assert payload["walletBalanceUpdatedAt"] == "2024-03-09T16:00:00+00:00"


def test_conversation_payload_reads_local_state(monkeypatch):
    mod = load_module()
    monkeypatch.setattr(
        mod,
        "_load_state",
        lambda: {
            "conversations": {
                "kaspa:qpeer123": {
                    "peer_address": "kaspa:qpeer123",
                    "status": "pending",
                    "their_alias": None,
                }
            }
        },
    )

    payload = mod._conversation_payload("kaspa:qpeer123")

    assert payload["chatId"] == "kaspa:qpeer123"
    assert payload["conversation"]["status"] == "pending"


def test_cmd_address_uses_wallet_inspection(monkeypatch, capsys):
    mod = load_module()
    monkeypatch.setattr(
        mod,
        "_wallet_inspection",
        lambda bridge_base, tx_id=None: {
            "wallet": {
                "address": "kaspa:qwallet123",
                "network": "mainnet",
                "fundingState": "ready",
            },
            "balanceSnapshot": {},
        },
    )

    mod.cmd_address(argparse.Namespace(bridge_base="http://127.0.0.1:3010"))
    output = json.loads(capsys.readouterr().out)

    assert output == {
        "address": "kaspa:qwallet123",
        "network": "mainnet",
        "fundingState": "ready",
    }


def test_cmd_tx_check_returns_tx_query(monkeypatch, capsys):
    mod = load_module()
    monkeypatch.setattr(
        mod,
        "_wallet_inspection",
        lambda bridge_base, tx_id=None: {
            "wallet": {
                "address": "kaspa:qwallet123",
                "network": "mainnet",
                "fundingState": "ready",
            },
            "balanceSnapshot": {},
            "txQuery": {
                "txId": tx_id,
                "found": True,
                "matches": [{"source": "pending_utxo", "txId": tx_id}],
            },
        },
    )

    mod.cmd_tx_check(
        argparse.Namespace(bridge_base="http://127.0.0.1:3010", tx_id="tx-topup")
    )
    output = json.loads(capsys.readouterr().out)

    assert output["txQuery"]["txId"] == "tx-topup"
    assert output["txQuery"]["found"] is True


def test_kas_to_sompi_string_handles_decimal_kas():
    mod = load_module()

    assert mod._kas_to_sompi_string("1.01") == "101000000"


def test_cmd_send_kaspa_preview_posts_wallet_preview(monkeypatch, capsys):
    mod = load_module()
    seen = {}

    def fake_request_json(method, path, *, base_url, payload=None):
        seen["call"] = (method, path, base_url, payload)
        return {
            "canSend": True,
            "destinationAddress": payload["destinationAddress"],
            "amountSompi": payload["amountSompi"],
            "feeSompi": "120000",
            "totalRequiredSompi": "101120000",
        }

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    mod.cmd_send_kaspa_preview(
        argparse.Namespace(
            bridge_base="http://127.0.0.1:3010",
            destination_address="kaspa:qdest123",
            amount_kas="1.01",
            amount_sompi=None,
            fee_policy="priority",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert seen["call"] == (
        "POST",
        "/wallet/send-kaspa/preview",
        "http://127.0.0.1:3010",
        {
            "destinationAddress": "kaspa:qdest123",
            "amountSompi": "101000000",
            "feePolicy": "priority",
        },
    )
    assert output["preview"]["amountKas"] == "1.01"
    assert output["preview"]["feeKas"] == "0.0012"
    assert output["preview"]["totalRequiredKas"] == "1.0112"


def test_cmd_sign_message_posts_to_bridge(monkeypatch, capsys):
    mod = load_module()
    seen = {}

    def fake_request_json(method, path, *, base_url, payload=None):
        seen["call"] = (method, path, base_url, payload)
        return {
            "address": "kaspa:qwallet123",
            "publicKey": "02abc",
            "signature": "sig:hello",
        }

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    mod.cmd_sign_message(
        argparse.Namespace(
            bridge_base="http://127.0.0.1:3010",
            message="hello",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert seen["call"] == (
        "POST",
        "/wallet/sign-message",
        "http://127.0.0.1:3010",
        {"message": "hello"},
    )
    assert output["signature"]["signature"] == "sig:hello"
