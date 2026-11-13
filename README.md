# SERV Triage Agent

A bug-bounty triage agent built on **SERV Reasoning** (OpenServ) for the
SERV Hackathon Edition 02, **Open Track**. Paste a raw finding — title,
description, code — and the agent returns a structured verdict through
the 7-question triage gate from a real bug-bounty playbook, with an
auditable reasoning trail.

## Why SERV Reasoning fits this

Triage is a *judgment* task: the instructions are stable (the same gate,
every time) while the inputs vary wildly (every finding is different).
That is exactly where SERV Reasoning is strongest — bounded, auditable
reasoning over a fixed decision procedure, instead of free-form
chain-of-thought that drifts. The gate is deterministic in structure
(Q1→Q7, one failure kills or downgrades), so the reasoning trace the API
returns is a real audit trail a human reviewer can check, not vibes.

## What it returns (JSON)

```json
{
  "verdict": "valid | likely-valid | needs-more-info | invalid",
  "severity": "critical | high | medium | low | informational",
  "confidence": 0,
  "summary": "...",
  "evidence": ["..."],
  "questions_failed": ["Q4", "Q7"],
  "reasoning_trace": "Q1 ...\nQ2 ...\n...",
  "recommended_next_step": "...",
  "mode": "live | mock",
  "model": "gpt-5.4-mini"
}
```

## Quick start

Python 3.10+ standard library only — no `pip install`, no build step.

```bash
# MOCK mode (no key needed, deterministic stub, free):
python3 -m serv_triage --sample valid-walletconnect-chain-scope

# Web UI:
python3 -m serv_triage.server --port 8000
# open http://127.0.0.1:8000/

# LIVE mode (SERV Reasoning, prepaid credits):
cp .env.example .env   # fill in SERV_API_KEY from console.openserv.ai
export SERV_API_KEY=...            # or source .env
python3 -m serv_triage --file my-finding.json
```

Environment variables: `SERV_API_KEY` (unset = MOCK),
`SERV_MODEL` (default `gpt-5.4-mini`),
`SERV_REASONING_EFFORT` (default `low`),
`SERV_BASE_URL` (default `https://inference-api.openserv.ai`),
`PORT` (default `8000`).

## Live mode

```bash
cp .env.example .env   # fill in SERV_API_KEY from console.openserv.ai
export SERV_API_KEY=...
python3 -m serv_triage --sample valid-walletconnect-chain-scope
```

The key is read from the environment only — never commit it (`.env`
is git-ignored; only `.env.example` ships). The client sends a system
prompt on every request (SERV rejects calls without one), uses
`reasoning_effort` low by default, and does **not** send a `temperature`
field — SERV's nano models reject anything but the default.

**Measured live (13 Nov 2026, `gpt-5.4-nano`, effort low):** ~1,161
prompt tokens + ~720–910 completion tokens per triage (~1,900–2,100
total, ~170–240 of them reasoning tokens). Check the OpenServ Models
page for current per-token pricing to turn that into a dollar figure.

**Two honest live findings:**
- The live model is stricter than the mock: on the bundled valid
  sample it returned **invalid / informational / confidence 45**,
  failing Q1 — it wants the exact executable payloads, not
  high-level steps. The verdict parser normalises the model's real
  field names (`supportingEvidence`, `failedQuestions`,
  `perQuestionReasoning`, `nextAction`) and 0–1 confidence floats.
- Security-triage wording trips the content filter: 2 of 3 live
  calls with the same prompt were refused (`finish_reason:
  content_filter`, "I can't share that."). Retrying usually gets
  through; the CLI surfaces the failure instead of crashing.

## CLI

```bash
python3 -m serv_triage --file finding.json
python3 -m serv_triage --sample invalid-false-positive
python3 -m serv_triage --title "X" --description "..." --code "..."
echo '{"title":"...","description":"..."}' | python3 -m serv_triage
python3 -m serv_triage --file finding.json --out verdict.json
```

## The 7-question gate (system prompt)

Summarised from our bug-bounty playbook (`bug-bounty-audit-playbook` +
`bughunter-web3-audit`): Q1 exploitable right now with concrete steps?
Q2 impact on the accepted list? Q3 root cause in scope? Q4 no privileged
access needed? Q5 not already known/accepted? Q6 impact proven with
numbers (moves value / freezes funds / breaks an invariant)? Q7 not a
known-invalid class (gas optimisation, missing events, admin-can-set-fee,
theoretical oracle, naming nits, duplicates)? One failure kills or
downgrades; borderline rounds severity *down*.

## Samples

- `samples/valid-walletconnect-chain-scope.json` — valid / low
  (anonymised from a real filed report: a WalletConnect session processes
  signing requests on chains outside its scope).
- `samples/invalid-false-positive.json` — invalid (owner-can-set-fee-100%).
- `samples/needs-more-info.json` — too thin to judge.

## Tests

```bash
python3 -m unittest discover -s tests -v   # 12 tests, mock pipeline + gate parser
```

## Project layout

```
serv_triage/
  gate.py         7-question gate system prompt + verdict JSON parser/validator
  serv_client.py  SERV HTTP client (urllib) + deterministic mock stub
  triage.py       pipeline: finding -> SERV -> parsed verdict
  cli.py          argparse CLI
  server.py       web UI (http.server, single HTML page)
samples/          3 example findings
tests/            mock end-to-end + schema validation tests
```

## Honest notes

- The verdict is a *triage opinion*, not a filing decision. Every real
  report still needs a human-reviewed runnable proof of concept.
- MOCK mode is a deterministic keyword stub for demoing the pipeline
  without credits. It is clearly labelled MOCK everywhere; it is not
  SERV Reasoning and its verdicts must not be presented as model output.
- SERV Reasoning needs a system prompt on every request — the client
  always sends one, and refuses to call without it.
