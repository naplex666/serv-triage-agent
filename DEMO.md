# DEMO.md — 2-minute demo script

Total ~2 minutes. Run in MOCK mode if there is no API key (the badge
says MOCK); run in LIVE mode with `SERV_API_KEY` set for the real SERV
Reasoning call.

## 0:00–0:15 — What this is
> "SERV Triage Agent: paste a raw bug-bounty finding, get a structured
> verdict through the 7-question triage gate — valid or not, severity,
> confidence, and the reasoning trail a reviewer can audit."

## 0:15–0:45 — Web UI, valid finding
1. Start the server: `python3 -m serv_triage.server --port 8000`
2. Open http://127.0.0.1:8000/ — point at the MOCK/LIVE badge.
3. Click the sample **valid-walletconnect-chain-scope** — the form fills
   with the anonymised WalletConnect chain-scope finding.
4. Click **Triage finding**. Read out: verdict **valid**, severity
   **low**, confidence **90**, and the Q1–Q7 trace. Note: this sample is
   anonymised from a real filed report.

## 0:45–1:15 — Invalid + thin findings
5. Click sample **invalid-false-positive** (owner can set fee to 100%)
   → verdict **invalid**, questions failed **Q4, Q7**. Say: "the gate
   kills admin-only power with no attacker path."
6. Click sample **needs-more-info** ("withdraw sometimes fails") →
   verdict **needs-more-info**, and read the recommended next step
   ("ask the reporter for exact steps, code, and impact").

## 1:15–1:45 — CLI + live mode
7. In a terminal: `python3 -m serv_triage --sample valid-walletconnect-chain-scope`
   — same verdict as JSON, pipeable.
8. If live: `export SERV_API_KEY=...` and re-run — the badge flips to
   LIVE and the verdict comes from SERV Reasoning. Mention the measured
   cost: ~1,900 tokens per triage on gpt-5.4-nano.

## 1:45–2:00 — Close
> "Same gate, same JSON, CLI or web. The verdict is a triage opinion —
> a real report still needs a human-reviewed runnable proof of
> concept."

## If something goes wrong live
- Content-filter refusal ("I can't share that."): retry — it is flaky
  on security wording (2 of 3 live calls refused during development).
- No key / no credits: the app falls back to MOCK automatically; the
  demo still works end to end.
