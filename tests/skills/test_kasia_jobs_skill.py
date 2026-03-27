from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "autonomous-ai-agents"
    / "kasia-jobs"
    / "scripts"
    / "kasia_jobs.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("kasia_jobs_skill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parser_exposes_greenfield_board_control_surface():
    mod = load_module()
    parser = mod.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    commands = set(subparsers.choices)

    assert "wallet-address" in commands
    assert "wallet-status" in commands
    assert "wallet-tx" in commands
    assert "agent-me" in commands
    assert "jobs" in commands
    assert "browse" in commands
    assert "job" in commands
    assert "my-poster" in commands
    assert "claim-job" in commands
    assert "submissions" in commands
    assert "messages" in commands
    assert "transport-events" in commands
    assert "escrow" in commands
    assert "coordinator-notices" in commands
    assert "escrow-actions" in commands
    assert "coordinator-diagnostics" in commands
    assert "verify-submission" in commands
    assert "release-job" in commands
    assert "job-messages" not in commands


def test_wallet_status_surfaces_bridge_balance(monkeypatch):
    mod = load_module()

    monkeypatch.setattr(
        mod,
        "_request_json",
        lambda method, path, *, base_url, payload=None, token=None: {
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
                "matureUtxoCount": 1,
                "pendingUtxoCount": 0,
                "trackedPendingUtxoCount": 0,
            },
            "recommendedMinBalanceSompi": "40000000",
        },
    )

    payload = mod._bridge_wallet_payload()

    assert payload["wallet"]["address"] == "kaspa:qwallet123"
    assert payload["wallet"]["fundingState"] == "low"
    assert payload["wallet"]["onChainBalanceKas"] == "0.97123696"
    assert payload["wallet"]["availableMatureBalanceKas"] == "0.97123696"
    assert payload["wallet"]["recommendedMinBalanceKas"] == "0.4"


def test_wallet_tx_passes_through_tx_query(monkeypatch):
    mod = load_module()
    seen_paths = []

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        seen_paths.append(path)
        return {
            "wallet": {
                "address": "kaspa:qwallet123",
                "network": "mainnet",
                "fundingState": "ready",
            },
            "balanceSnapshot": {},
            "txQuery": {
                "txId": "tx-topup",
                "found": True,
                "matches": [{"source": "pending_utxo", "txId": "tx-topup"}],
            },
        }

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    payload = mod._bridge_wallet_payload(tx_id="tx-topup")

    assert seen_paths == ["/wallet?txId=tx-topup"]
    assert payload["txQuery"]["found"] is True


def test_poster_dashboard_prefers_job_status_over_missing_escrow(monkeypatch):
    mod = load_module()
    jobs = [
        {
            "id": "job-complete",
            "title": "Completed job",
            "status": "completed",
            "budgetKas": "1",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
            "awardedWorker": {"address": "kaspa:qp6v08cef4v2eyn9lxsrnvjplytemr53gdmwuyjc2gprj6lfl22jxwh65x8cx"},
        },
        {
            "id": "job-claimed",
            "title": "Claimed job",
            "status": "claimed",
            "budgetKas": "1",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
            "awardedWorker": {"address": "kaspa:qp6v08cef4v2eyn9lxsrnvjplytemr53gdmwuyjc2gprj6lfl22jxwh65x8cx"},
        },
        {
            "id": "job-awaiting-funds",
            "title": "Awaiting funds job",
            "status": "open",
            "budgetKas": "1",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
        },
        {
            "id": "job-open-no-escrow",
            "title": "Open job",
            "status": "open",
            "budgetKas": "1",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
        },
        {
            "id": "job-pending-claims",
            "title": "Decision needed",
            "status": "open",
            "budgetKas": "1",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
            "claims": [
                {
                    "id": "claim-1",
                    "status": "pending",
                    "estimatedHours": 3,
                    "worker": {"address": "kaspa:qptestclaimworker1"},
                },
                {
                    "id": "claim-2",
                    "status": "pending",
                    "estimatedHours": 1,
                    "worker": {"address": "kaspa:qptestclaimworker2"},
                },
            ],
            "escrow": {"status": "funded"},
        },
        {
            "id": "job-needs-release",
            "title": "Ready to pay worker",
            "status": "completed",
            "budgetKas": "2",
            "createdAt": "2026-03-26T00:00:00Z",
            "updatedAt": "2026-03-26T00:00:00Z",
            "escrow": {"status": "reserved"},
            "awardedWorker": {"address": "kaspa:qptestreleaseworker1"},
        },
    ]

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        assert method == "GET"
        assert path == "/jobs/me/poster"
        return {"jobs": jobs}

    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(
        mod,
        "_maybe_request_json",
        lambda method, path, *, base_url, payload=None, token=None: (
            {
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "1.01",
                    "depositAddress": "kaspa:qpv9aglks2l7y4vfny4u7hj32zqr2rs984s9zdzvszql4jfwtgpjujsw6dgh4",
                }
            }
            if path == "/jobs/job-awaiting-funds/escrow"
            else None
        ),
    )

    payload = mod._poster_dashboard_payload(base_url="http://board", token="token")

    assert payload["summary"]["completed"] == 1
    assert payload["summary"]["inProgress"] == 1
    assert payload["summary"]["awaitingFunding"] == 1
    assert payload["summary"]["needsFundingSetup"] == 1
    assert payload["summary"]["needsClaimDecision"] == 1
    assert payload["summary"]["needsRelease"] == 1
    assert payload["suggestedClaimDecisions"] == [
        {
            "jobId": "job-pending-claims",
            "title": "Decision needed",
            "claimId": "claim-2",
            "reason": "lowest_estimated_hours",
        }
    ]


def test_dashboard_reports_board_identity_mismatch(monkeypatch):
    mod = load_module()
    board_address = "kaspa:qp69kh7sqc3u8624mhc78xj65pmxq9jm8egayjk26x6k54hudrfwxns9tl7tj"
    worker_address = "kaspa:qp6v08cef4v2eyn9lxsrnvjplytemr53gdmwuyjc2gprj6lfl22jxwh65x8cx"

    monkeypatch.setattr(
        mod,
        "_load_session",
        lambda: {"identity": {"address": board_address, "displayName": "Poster"}},
    )
    monkeypatch.setattr(
        mod,
        "_detect_local_kasia_identity",
        lambda: {"address": worker_address, "source": "bridge"},
    )
    monkeypatch.setattr(
        mod,
        "_poster_dashboard_payload",
        lambda **_: {
            "summary": {
                "totalJobs": 1,
                "awaitingFunding": 0,
                "needsFundingSetup": 0,
                "needsClaimDecision": 1,
                "readyForClaims": 0,
                "inProgress": 0,
                "awaitingReview": 0,
                "needsRelease": 0,
                "completed": 0,
                "refunded": 0,
            },
            "nextActions": ["Review a pending claim."],
        },
    )
    monkeypatch.setattr(
        mod,
        "_worker_dashboard_payload",
        lambda **_: {
            "summary": {
                "pendingClaims": 0,
                "acceptedClaims": 0,
                "assignedInProgress": 0,
                "awaitingReview": 0,
            },
            "nextActions": [],
        },
    )

    payload = mod._dashboard_payload(base_url="http://board", token="token")

    assert payload["identity"]["addressesMatch"] is False
    assert board_address in payload["identity"]["roleWarning"]
    assert worker_address in payload["identity"]["roleWarning"]
    assert payload["nextActions"][0] == payload["identity"]["roleWarning"]
    assert payload["mode"]["suggestedFocus"] == "poster"


def test_intent_post_requests_only_missing_budget(monkeypatch, capsys):
    mod = load_module()

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="post",
            request_text="Create a dancing lobster single page html.",
            budget_kas=None,
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=None,
            allow_awaiting_funds=False,
            min_score=1,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is False
    assert payload["missingFields"] == ["budgetKas"]
    assert payload["preferredUserQuestion"] == "What budget do you want to offer in KAS?"


def test_intent_post_returns_quote_and_create_args(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(
        mod,
        "_quote_job_funding",
        lambda *, budget_kas, base_url: {
            "budgetKas": budget_kas,
            "fundingTargetKas": "1.01",
            "minJobBudgetKas": "0.1",
            "belowMinimum": False,
        },
    )

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="post",
            request_text="post a kasia job for a duck pedaling on a bike",
            budget_kas="1",
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=None,
            allow_awaiting_funds=False,
            min_score=1,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is True
    assert payload["suggestedTitle"] == "Duck pedaling on a bike"
    assert payload["createJobArgs"] == {
        "title": "Duck pedaling on a bike",
        "prompt": "post a kasia job for a duck pedaling on a bike",
        "budgetKas": "1",
        "verifierType": "manual_review",
    }
    assert "funding target is 1.01 KAS" in payload["preferredUserFacingReply"]


def test_intent_post_can_extract_budget_from_plain_language_reply(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(
        mod,
        "_quote_job_funding",
        lambda *, budget_kas, base_url: {
            "budgetKas": budget_kas,
            "fundingTargetKas": "1.01",
            "minJobBudgetKas": "0.1",
            "belowMinimum": False,
        },
    )

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="post",
            request_text="i want someone to make me a page displaying a dancing lobster. i'm thinking 1kas budget",
            budget_kas=None,
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=None,
            allow_awaiting_funds=False,
            min_score=1,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is True
    assert payload["derivedBudgetFromRequest"] is True
    assert payload["suggestedTitle"] == "Page displaying a dancing lobster"
    assert payload["createJobArgs"]["budgetKas"] == "1"
    assert payload["createJobArgs"]["prompt"] == "i want someone to make me a page displaying a dancing lobster"


def test_intent_browse_wraps_recommendations(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_filtered_recommendations",
        lambda **_: {
            "recommendations": [{"job": {"id": "job-1", "title": "Duck bike page"}}],
            "bestActionable": {"job": {"id": "job-1", "title": "Duck bike page"}},
            "bestNearMatch": {"job": {"id": "job-1", "title": "Duck bike page"}},
            "humanSummary": "1 recommended job found; 1 can be claimed now.",
            "conversationNextStep": "Offer to claim it now.",
            "summary": {
                "recommendationCount": 1,
                "actionableCount": 1,
                "awaitingFundingCount": 0,
            },
            "nextActions": ["Claimable now: job-1 (Duck bike page)."],
        },
    )

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="browse",
            request_text=None,
            budget_kas=None,
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=72,
            allow_awaiting_funds=False,
            min_score=1,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["followUpIntent"] == "claim"
    assert payload["humanSummary"] == "1 recommended job found; 1 can be claimed now."


def test_intent_check_reports_auth_setup_requirement(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(
        mod,
        "_require_token",
        lambda: (_ for _ in ()).throw(SystemExit("Run auth first.")),
    )

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="check",
            request_text=None,
            budget_kas=None,
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=None,
            allow_awaiting_funds=False,
            min_score=1,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is False
    assert payload["setupRequired"] is True
    assert payload["nextStep"] == "Run auth first, then retry this intent."


def test_review_intent_prioritizes_needs_release(monkeypatch):
    mod = load_module()

    monkeypatch.setattr(
        mod,
        "_poster_dashboard_payload",
        lambda **_: {
            "summary": {
                "totalJobs": 2,
                "awaitingFunding": 0,
                "needsFundingSetup": 0,
                "needsClaimDecision": 0,
                "readyForClaims": 0,
                "inProgress": 0,
                "awaitingReview": 1,
                "needsRelease": 1,
                "completed": 0,
                "refunded": 0,
            }
        },
    )

    payload = mod._review_intent_payload(base_url="http://board", token="token")

    assert payload["nextStep"] == "Release reserved escrow for the next completed job so the worker gets paid."
    assert payload["humanSummary"].startswith("1 needing release, 1 awaiting review")


def test_intent_claim_returns_claim_preview(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_filtered_recommendations",
        lambda **_: {
            "recommendations": [
                {
                    "job": {"id": "job-1", "title": "Duck bike page"},
                    "policy": {"actionable": True},
                    "score": 88,
                }
            ],
            "bestActionable": {"job": {"id": "job-1", "title": "Duck bike page"}},
            "bestNearMatch": {"job": {"id": "job-1", "title": "Duck bike page"}},
            "humanSummary": "1 recommended job found; 1 can be claimed now.",
            "conversationNextStep": "Offer to claim it now.",
            "summary": {
                "recommendationCount": 1,
                "actionableCount": 1,
                "awaitingFundingCount": 0,
            },
            "nextActions": ["Claimable now: job-1 (Duck bike page)."],
        },
    )

    mod.cmd_intent(
        argparse.Namespace(
            base_url="http://board",
            intent="claim",
            request_text=None,
            budget_kas=None,
            title=None,
            job_id=None,
            verifier_type="manual_review",
            limit=5,
            status=["open"],
            new_since_hours=72,
            allow_awaiting_funds=False,
            min_score=50,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is True
    assert payload["selectedRecommendation"]["job"]["id"] == "job-1"
    assert payload["claimPreview"]["command"] == "claim-best"
    assert payload["claimPreview"]["minScore"] == 50


def test_claim_job_claims_specific_job(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, token=None, payload=None):
        if method == "POST" and path == "/jobs/job-42/claims":
            assert token == "token"
            assert payload == {
                "message": "Good fit for this one",
                "estimatedHours": 2,
            }
            return {
                "claim": {
                    "id": "claim-42",
                    "status": "pending",
                    "message": payload["message"],
                    "estimatedHours": payload["estimatedHours"],
                },
                "created": True,
            }
        if method == "GET" and path == "/jobs/job-42":
            return {
                "job": {
                    "id": "job-42",
                    "title": "Specific lobster page",
                    "execution": {"platform": "kasia"},
                }
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_maybe_bootstrap_coordinator_handshake", lambda **_: None)
    monkeypatch.setattr(mod, "_maybe_send_kasia_notice", lambda **_: None)

    mod.cmd_claim_job(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-42",
            message="Good fit for this one",
            estimated_hours=2,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["claim"]["id"] == "claim-42"
    assert payload["created"] is True
    assert payload["jobExecution"]["platform"] == "kasia"


def test_recommendations_include_human_summary_and_next_step(monkeypatch):
    mod = load_module()

    recommendation_payload = {
        "recommendations": [
            {
                "job": {
                    "id": "job-1",
                    "title": "Duck bike page",
                    "createdAt": "2026-03-26T00:00:00Z",
                },
                "policy": {
                    "actionable": False,
                    "warnings": ["Awaiting funding before claim."],
                },
                "reasons": ["Awaiting funding before claim."],
                "score": 88,
            }
        ]
    }

    monkeypatch.setattr(
        mod,
        "_request_json",
        lambda *args, **kwargs: recommendation_payload,
    )

    payload = mod._filtered_recommendations(
        base_url="http://board",
        token="token",
        limit=5,
        statuses=["open"],
        new_since_hours=72,
    )

    assert "none are claimable right now" in payload["humanSummary"].lower()
    assert payload["bestNearMatch"]["job"]["id"] == "job-1"
    assert "watch" in payload["conversationNextStep"].lower()
    assert "post a new job" in payload["conversationNextStep"].lower()
    assert any("post a new job" in action.lower() for action in payload["nextActions"])


def test_funding_instructions_show_manual_funding_steps(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        if path.endswith("/escrow"):
            return {
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "1.51",
                    "depositAddress": "kaspa:qpv9aglks2l7y4vfny4u7hj32zqr2rs984s9zdzvszql4jfwtgpjujsw6dgh4",
                }
            }
        return {
            "job": {
                "id": "job-duck",
                "title": "Duck bike page",
                "budgetKas": "1.5",
            }
        }

    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(mod, "_detect_local_kasia_identity", lambda: None)

    mod.cmd_funding_instructions(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-duck",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    funding = payload["funding"]
    assert funding["noFundsMovedYet"] is True
    assert funding["canHermesMoveFundsDirectly"] is False
    assert "your wallet" in funding["whyHermesCannotSendFromChat"]
    assert "did not move any KAS" in funding["humanExplanation"]
    assert "send the exact amount from your wallet" in funding["humanExplanation"]
    assert funding["afterFundingOptions"] == [
        "watch this job for claims",
        "any claims on my jobs?",
        "pick the best claimant",
    ]
    assert funding["steps"][0] == "No funds have moved yet."


def test_create_job_returns_funding_follow_up(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_request_json",
        lambda method, path, *, base_url, token=None, payload=None: {
            "job": {
                "id": "job-duck",
                "title": "Dancing Lobster",
                "budgetKas": "1",
            },
            "escrow": {
                "status": "awaiting_funds",
                "fundingTargetKas": "1.01",
                "depositAddress": "kaspa:qtestdeposit123",
            },
        },
    )

    mod.cmd_create_job(
        argparse.Namespace(
            base_url="http://board",
            title="Dancing Lobster",
            prompt="Create a dancing lobster single page html.",
            budget_kas="1",
            deliverables=[],
            verifier_type="manual_review",
            summary=None,
            deadline=None,
            execution_chat_id=None,
            execution_notes=None,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["escrow"]["status"] == "awaiting_funds"
    assert payload["nextCommand"] == {
        "command": "funding-instructions",
        "jobId": "job-duck",
    }
    assert "live escrow state" in payload["nextAction"]


def test_funding_instructions_expose_local_wallet_funding_when_available(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        if path == "/jobs/job-lobster":
            return {
                "job": {
                    "id": "job-lobster",
                    "title": "Dancing Lobster",
                    "budgetKas": "1",
                }
            }
        if path == "/jobs/job-lobster/escrow":
            return {
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "1.01",
                    "fundingTargetSompi": "101000000",
                    "depositAddress": "kaspa:qtestdeposit123",
                }
            }
        raise AssertionError(path)

    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(
        mod,
        "_detect_local_kasia_identity",
        lambda: {"address": "kaspa:qwallet123", "source": "bridge"},
    )
    monkeypatch.setattr(
        mod,
        "_request_json_result",
        lambda method, path, *, base_url, payload=None, token=None: {
            "ok": True,
            "data": {
                "canSend": True,
                "feeSompi": "120000",
                "totalRequiredSompi": "101120000",
            },
        },
    )

    mod.cmd_funding_instructions(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-lobster",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    funding = payload["funding"]
    assert funding["canHermesMoveFundsDirectly"] is True
    assert funding["localWalletFunding"]["walletAddress"] == "kaspa:qwallet123"
    assert funding["localWalletFunding"]["amountKas"] == "1.01"
    assert "pay from your wallet, or should I fund it from mine" in funding["steps"][1]
    assert funding["fundingChoiceQuestion"] == "Do you want to pay from your wallet, or should I fund it from mine?"
    assert "sending the exact amount from your wallet" in funding["humanExplanation"]
    assert "from my wallet" in funding["humanExplanation"]
    assert funding["mustUsePreferredUserFacingReply"] is True
    assert "Do you want to pay from your wallet, or should I fund it from mine?" in funding["preferredUserFacingReply"]
    assert "still needs funding" in funding["preferredUserFacingReply"]


def test_funding_instructions_explain_when_hermes_wallet_cannot_cover_it(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, token=None, payload=None):
        if path == "/jobs/job-lobster":
            return {
                "job": {
                    "id": "job-lobster",
                    "title": "Dancing Lobster",
                    "budgetKas": "1",
                }
            }
        if path == "/jobs/job-lobster/escrow":
            return {
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "1.01",
                    "fundingTargetSompi": "101000000",
                    "depositAddress": "kaspa:qtestdeposit123",
                }
            }
        raise AssertionError(path)

    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(
        mod,
        "_detect_local_kasia_identity",
        lambda: {"address": "kaspa:qwallet123", "source": "bridge"},
    )
    monkeypatch.setattr(
        mod,
        "_request_json_result",
        lambda method, path, *, base_url, payload=None, token=None: {
            "ok": True,
            "data": {
                "canSend": False,
                "feeSompi": "120000",
                "totalRequiredSompi": "101120000",
                "error": "Insufficient funds after fee",
            },
        },
    )

    mod.cmd_funding_instructions(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-lobster",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    funding = payload["funding"]
    assert funding["canHermesMoveFundsDirectly"] is False
    assert funding["fundingChoiceQuestion"] is None
    assert "can't fund this from my wallet right now" in funding["humanExplanation"]
    assert "Insufficient funds after fee" in funding["humanExplanation"]
    assert "can't fund it from my wallet right now" in funding["preferredUserFacingReply"]
    assert "Insufficient funds after fee" in funding["preferredUserFacingReply"]
    assert any("cannot fund it from its own wallet right now" in step for step in funding["steps"])


def test_create_job_does_not_emit_legacy_conversation_hints(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_request_json",
        lambda method, path, *, base_url, token=None, payload=None: {
            "job": {
                "id": "job-duck",
                "title": "Dancing Lobster",
                "budgetKas": "1",
            },
            "escrow": {
                "status": "awaiting_funds",
                "fundingTargetKas": "1.01",
                "fundingTargetSompi": "101000000",
                "depositAddress": "kaspa:qtestdeposit123",
            },
        },
    )
    monkeypatch.setattr(
        mod,
        "_request_json_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("create-job should not preview wallet state")),
    )

    mod.cmd_create_job(
        argparse.Namespace(
            base_url="http://board",
            title="Dancing Lobster",
            prompt="Create a dancing lobster single page html.",
            budget_kas="1",
            deliverables=[],
            verifier_type="manual_review",
            summary=None,
            deadline=None,
            execution_chat_id=None,
            execution_notes=None,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert "conversationHints" not in payload
    assert payload["nextCommand"] == {
        "command": "funding-instructions",
        "jobId": "job-duck",
    }


def test_create_job_normalizes_nested_job_escrow(monkeypatch, capsys):
    mod = load_module()

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(
        mod,
        "_request_json",
        lambda method, path, *, base_url, token=None, payload=None: {
            "job": {
                "id": "job-nested",
                "title": "Nested Escrow",
                "budgetKas": "0.5",
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "0.51",
                    "fundingTargetSompi": "51000000",
                    "depositAddress": "kaspa:qnesteddeposit123",
                },
            },
        },
    )

    mod.cmd_create_job(
        argparse.Namespace(
            base_url="http://board",
            title="Nested Escrow",
            prompt="Create a nested escrow test.",
            budget_kas="0.5",
            deliverables=[],
            verifier_type="manual_review",
            summary=None,
            deadline=None,
            execution_chat_id=None,
            execution_notes=None,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["escrow"]["depositAddress"] == "kaspa:qnesteddeposit123"
    assert payload["nextCommand"] == {
        "command": "funding-instructions",
        "jobId": "job-nested",
    }


def test_fund_job_from_local_wallet_sends_and_records(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        if method == "GET" and path == "/jobs/job-fund":
            return {
                "job": {
                    "id": "job-fund",
                    "title": "Fund me",
                }
            }
        if method == "GET" and path == "/jobs/job-fund/escrow":
            return {
                "escrow": {
                    "status": "awaiting_funds",
                    "fundingTargetKas": "1.01",
                    "fundingTargetSompi": "101000000",
                    "depositAddress": "kaspa:qdeposit123",
                }
            }
        raise AssertionError((method, path, payload))

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)
    monkeypatch.setattr(
        mod,
        "_detect_local_kasia_identity",
        lambda: {"address": "kaspa:qwallet123", "source": "bridge"},
    )
    monkeypatch.setattr(
        mod,
        "_preview_send_with_kasia_bridge",
        lambda **kwargs: {
            "canSend": True,
            "feeSompi": "120000",
            "totalRequiredSompi": "101120000",
        },
    )
    monkeypatch.setattr(
        mod,
        "_send_with_kasia_bridge",
        lambda **kwargs: {
            "txId": "fund_tx_123",
            "accepted": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_request_json_result",
        lambda method, path, *, base_url, payload=None, token=None: {
            "ok": True,
            "data": {
                "escrow": {
                    "status": "funded",
                    "fundingTxRef": payload["fundingTxRef"],
                    "fundedAmountSompi": payload["amountSompi"],
                }
            },
        },
    )

    mod.cmd_fund_job(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-fund",
            funding_tx_ref=None,
            amount_sompi=None,
            from_local_wallet=True,
            fee_policy="priority",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["fundingMode"] == "local_kasia_wallet"
    assert payload["fundingTxRef"] == "fund_tx_123"
    assert payload["boardRecorded"] is True
    assert payload["escrow"]["status"] == "funded"
    assert payload["humanExplanation"].startswith("I funded this job from my wallet.")


def test_release_job_posts_release_request(monkeypatch, capsys):
    mod = load_module()

    def fake_request_json(method, path, *, base_url, payload=None, token=None):
        assert method == "POST"
        assert path == "/jobs/job-release/release"
        assert token == "token"
        assert payload == {
            "releaseTxRef": "release_tx_123",
            "amountSompi": "101000000",
            "toAddress": "kaspa:qworker123",
        }
        return {
            "escrow": {
                "status": "released",
                "releaseTxRef": "release_tx_123",
            }
        }

    monkeypatch.setattr(mod, "_require_token", lambda: "token")
    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    mod.cmd_release_job(
        argparse.Namespace(
            base_url="http://board",
            job_id="job-release",
            release_tx_ref="release_tx_123",
            amount_sompi="101000000",
            to_address="qworker123",
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["escrow"]["status"] == "released"
    assert payload["escrow"]["releaseTxRef"] == "release_tx_123"
