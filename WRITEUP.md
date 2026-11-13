# SERV Triage Agent — submission write-up (Open Track)

## What we built

A bug-bounty triage agent. A hunter pastes a raw finding — title,
description, code — and the agent returns a structured verdict through
the **7-question triage gate** used by real bounty hunters, with an
auditable reasoning trail:

```json
{ "verdict": "valid | likely-valid | needs-more-info | invalid",
  "severity": "critical | high | medium | low | informational",
  "confidence": 0-100, "summary": "...", "evidence": ["..."],
  "questions_failed": ["Q1"], "reasoning_trace": "Q1 ...\nQ2 ...",
  "recommended_next_step": "..." }
```

Two interfaces, same pipeline: a CLI (`python -m serv_triage`) and a
one-page web UI (`python -m serv_triage.server`, stdlib only, no build
step, no pip install). Without an API key the app runs in clearly
labelled MOCK mode with a deterministic stub, so the demo always works.

## How it uses SERV Reasoning

The gate is the system prompt: seven questions applied in order —
exploitable right now? impact accepted? in scope? no privilege needed?
not already known? impact proven with numbers? not a known-invalid
class? One failure kills or downgrades; borderline rounds severity
*down*. The call is `POST /v1/chat/completions` (OpenAI-compatible,
Bearer key, `reasoning_effort: low`, model `gpt-5.4-mini` by default,
`gpt-5.4-nano` for the cheapest runs). A system prompt is required on
every request — the client refuses to call without one — and the
response's reasoning summary is harvested into the audit trail.

Why SERV fits: triage is a judgment task — the instructions are stable
(the same gate every time) while the inputs vary wildly. SERV Reasoning
compiles that stable procedure into bounded, auditable reasoning instead
of free-form chain-of-thought, so the trace a reviewer checks is the
actual decision path, not vibes.

## What we learned building it (honest notes)

- **The live model is stricter than our mock.** On the bundled valid
  sample (anonymised from a real filed report), the mock says
  valid/low; live `gpt-5.4-nano` said invalid, Q1 failed — it demands
  the exact executable payloads (method calls, parameters, observed
  results), not high-level steps. That strictness is the product
  working as designed; it also tells us real submissions must include
  exact PoC details. The parser now normalises the model's real field
  names (`supportingEvidence`, `failedQuestions`,
  `perQuestionReasoning`, `nextAction`) and 0–1 confidence floats.
- **Security-triage wording trips the content filter.** 2 of 3 live
  calls with the same prompt were refused (`finish_reason:
  content_filter`, "I can't share that."). Retrying usually gets
  through. A production version would retry and would soften
  trigger words in the prompt without weakening the gate.
- **Measured cost (13 Nov 2026, gpt-5.4-nano, effort low):** ~1,161
  prompt tokens + ~720–910 completion tokens per triage (~1,900–2,100
  total, ~170–240 of them reasoning tokens). Check the OpenServ Models
  page for current per-token pricing.

## Track

Open Track (04) — any idea, any stack, must use SERV Reasoning.

## Links

- Repo: https://github.com/naplex666/serv-triage-agent
- Demo: see DEMO.md (2-minute script). Live mode needs
  `SERV_API_KEY` from console.openserv.ai; without it the app runs in
  MOCK mode.
