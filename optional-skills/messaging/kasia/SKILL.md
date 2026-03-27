---
name: kasia
description: Operate Hermes on Kasia using its underlying Kaspa wallet identity. Use this for Kasia setup follow-ups, wallet address and balance questions, target resolution, handshake status, DM send checks, and generic Kasia diagnostics that are not specific to kasia-jobs.
version: 0.2.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Kasia, Kaspa, Messaging, Wallet, Diagnostics, Pairing]
    related_skills: [kasia-jobs]
---

# Kasia

This skill is the generic operator guide for Hermes's built-in Kasia integration.

Kasia is the messaging layer. Hermes uses a Kaspa wallet identity underneath it. There is no separate Kasia wallet.

Use the installed helper directly:

`python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py`

Do not grep the repo or invent scratch Python when the helper already covers the task.

## Use This Skill When

- The user asks for Hermes's Kaspa address used on Kasia
- The user asks for wallet balance, spendable balance, or whether Hermes is funded enough to send
- The user asks whether Kasia is healthy, connected, or configured
- The user wants to resolve a `.kas`, address, or broadcast target
- The user wants to inspect a Kasia chat or pending handshake state
- The user wants to send a Kasia message or check the status of a recent send job
- The user wants Hermes to sign a message with its Kaspa identity used for Kasia
- The user wants Hermes to preview or perform a direct KAS send from its own wallet
- The question is about Hermes on Kasia generally, not specifically about the kasia-jobs board

## Rules

- Treat Kasia as messaging over Kaspa, not as a separate wallet system.
- Start with `address`, `wallet`, or `status` for wallet and funding questions.
- Use `sign-message`, `send-kaspa-preview`, and `send-kaspa` for generic wallet actions.
- Use `conversation` or `chat` for peer-specific inspection.
- Use `send-status` for a prior Kasia send job id.
- Do not call the bridge `/messages` queue from this skill. The gateway owns inbox polling.
- If the user is in an active `kasia-jobs` conversation, stay there unless the question is clearly generic Kasia infrastructure.

## Quick Reference

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py status
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py address
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py wallet
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py tx-check <txid>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py resolve <target>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py chat <chat_id>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py conversation <chat_id>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py handshake-initiate <chat_id> --display-name "Hermes"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py handshake-respond <chat_id>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send <chat_id> --message "<text>"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-status <job_id>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py sign-message --message "<text>"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-kaspa-preview <address> --amount-kas 1.01 --fee-policy auto
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-kaspa <address> --amount-kas 1.01 --fee-policy auto
```

## Procedure

### Wallet And Health

For questions like `what's your address?`, `do you have enough KAS?`, or `is Kasia working?`:

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py address
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py wallet
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py status
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py tx-check <txid>
```

Response shaping:

- `address`: answer with the Kaspa address plainly
- `wallet`: include on-chain balance, mature/spendable balance, pending balance, and funding state
- `tx-check`: say whether the tx is currently visible to Hermes's wallet and where it was seen
- `status`: mention bridge connectivity plus the active indexer and node URLs when relevant

### Wallet Actions

For generic wallet actions tied to Hermes's Kasia identity:

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py sign-message --message "<text>"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-kaspa-preview <address> --amount-kas 1.01 --fee-policy auto
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-kaspa <address> --amount-kas 1.01 --fee-policy auto
```

Use `send-kaspa-preview` before `send-kaspa` when the user is checking affordability or wants confirmation first.
Use `--fee-policy low|normal|priority|auto` if the user explicitly wants a different fee-rate policy.

### Resolve And Inspect A Peer

For `.kas` names, raw addresses, or broadcast channels:

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py resolve <target>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py chat <chat_id>
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py conversation <chat_id>
```

Use `conversation` when you need local handshake or alias state. Use `chat` when you only need the bridge-facing chat identity.

### Handshakes

If a user wants Hermes to open or answer a Kasia DM relationship:

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py handshake-initiate <chat_id> --display-name "Hermes"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py handshake-respond <chat_id>
```

### Send And Delivery Checks

For generic Kasia DMs:

```bash
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send <chat_id> --message "<text>"
python3 ~/.hermes/skills/messaging/kasia/scripts/kasia.py send-status <job_id>
```

Use `send-status` only with the bridge job id returned by `send`.

## Fallback Diagnostics

If `status` shows the bridge is unhealthy or underfunded, use the built-in Hermes diagnostics:

```bash
python3 -m hermes_cli.main kasia doctor
```

## Response Shaping

- For wallet questions, answer directly instead of giving a long dump.
- Distinguish on-chain balance from mature/spendable balance.
- Treat direct sends as Kaspa wallet operations that power Kasia, not as a separate wallet product.
- If Hermes is low on funds, say so plainly and mention that Kasia delivery may fail until the Kaspa wallet is topped up.
- If a question is really about a job escrow or job funding path, switch back to `kasia-jobs`.
