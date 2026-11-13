"""SERV Reasoning client (OpenAI-compatible) + deterministic mock.

Live mode talks to POST {base_url}/v1/chat/completions with a Bearer
SERV_API_KEY. SERV requires a system prompt on every request — the caller
always passes one. The response's reasoning summary/trace is harvested
from every field the API may use for it.

Mock mode runs when SERV_API_KEY is unset: a deterministic, rule-based
stub runs the same gate logic over the finding text (keyword signals for
exploit steps, impact, and the known-invalid kill classes) and returns a
verdict in the exact same JSON shape, clearly labelled MOCK. No network,
no cost, same pipeline.
"""

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://inference-api.openserv.ai"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_EFFORT = "low"


class ServError(Exception):
    """Raised when the SERV API call fails (network, auth, bad response)."""


# ---------------------------------------------------------------- live client

def _harvest_reasoning(payload):
    """Collect a reasoning summary/trace from a chat-completions payload.

    Different providers surface it under different keys; gather every
    string found so the audit trail is never silently dropped.
    """
    bits = []
    try:
        choices = payload.get("choices") or []
        for choice in choices:
            msg = choice.get("message") or {}
            for key in ("reasoning_content", "reasoning", "reasoning_summary"):
                val = msg.get(key)
                if isinstance(val, str) and val.strip():
                    bits.append(val.strip())
            for key in ("reasoning", "reasoning_content", "reasoning_summary"):
                val = choice.get(key)
                if isinstance(val, str) and val.strip():
                    bits.append(val.strip())
        for key in ("reasoning", "reasoning_content"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                bits.append(val.strip())
    except Exception:
        return ""
    # de-duplicate, keep order
    seen, out = set(), []
    for bit in bits:
        if bit not in seen:
            seen.add(bit)
            out.append(bit)
    return "\n".join(out)


class ServClient:
    """Minimal OpenAI-compatible client for SERV Reasoning (stdlib only)."""

    def __init__(self, api_key, model=None, reasoning_effort=None,
                 base_url=None, timeout=120):
        self.api_key = api_key
        self.model = model or os.environ.get("SERV_MODEL", DEFAULT_MODEL)
        self.reasoning_effort = reasoning_effort or os.environ.get(
            "SERV_REASONING_EFFORT", DEFAULT_EFFORT)
        self.base_url = (base_url or os.environ.get("SERV_BASE_URL",
                                                    DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout

    def complete(self, system_prompt, user_text):
        """One chat completion. Returns {"content": str, "reasoning": str,
        "model": str, "mode": "live"}."""
        if not system_prompt or not system_prompt.strip():
            raise ServError("SERV rejects requests without a system prompt")
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            # NOTE: no temperature field — SERV's nano models reject
            # anything but the default (1); the JSON schema in the system
            # prompt is what keeps the output structured.
            "reasoning_effort": self.reasoning_effort,
        }
        req = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ServError(f"SERV API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ServError(f"cannot reach SERV API: {exc.reason}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ServError(f"unexpected SERV response shape: {payload!r}"[:500]) from exc
        return {
            "content": content or "",
            "reasoning": _harvest_reasoning(payload),
            "model": payload.get("model", self.model),
            "mode": "live",
        }


# ---------------------------------------------------------------- mock client

_KILL_PHRASES = (
    "admin can", "only owner", "onlyowner", "owner can", "owner-only",
    "gas optimization", "gas optimisation", "missing event",
    "naming", "theoretical", "centralization risk", "centralisation risk",
    "set the fee", "set fee", "documentation", "typo",
)
_CRITICAL_WORDS = (
    "drain", "steal", "unlimited mint", "infinite mint", "mint unlimited",
    "take over", "takeover", "all funds",
)
_HIGH_WORDS = (
    "bypass", "unauthorised", "unauthorized", "reentrancy", "reentrant",
    "signature replay", "without permission", "privilege escalation",
    "front-run", "frontrun",
)
_MEDIUM_WORDS = (
    "freeze", "frozen", "denial of service", "dos", "griefing",
    "lock funds", "lock user",
)
_STEP_WORDS = ("step", "reproduce", "poc", "proof of concept", "attacker",
               "call ", "1.", "first,", "then ")
_IMPACT_WORDS = ("fund", "loss", "steal", "drain", "bypass", "freeze",
                 "unauthorised", "unauthorized", "exploit")


def _count_hits(text, words):
    return [w for w in words if w in text]


def _mock_verdict(finding):
    """Deterministic rule-based verdict over the finding text.

    Mirrors the gate: kill classes (Q4/Q7) -> invalid; too thin to judge
    (Q1/Q6) -> needs-more-info; concrete steps + impact -> valid.
    """
    title = (finding.get("title") or "").strip()
    description = (finding.get("description") or "").strip()
    code = (finding.get("code") or "").strip()
    blob = f"{title}\n{description}\n{code}".lower()

    kills = _count_hits(blob, _KILL_PHRASES)
    crit = _count_hits(blob, _CRITICAL_WORDS)
    high = _count_hits(blob, _HIGH_WORDS)
    med = _count_hits(blob, _MEDIUM_WORDS)
    steps = _count_hits(blob, _STEP_WORDS)
    impact = _count_hits(blob, _IMPACT_WORDS)
    has_steps = bool(re.search(r"\b(step|1\.)\b", blob)) or "poc" in blob
    has_code = bool(code)
    is_thin = len(description) < 150 and not has_code and not has_steps

    trace = []
    if kills:
        trace.append("Q1 exploit path: UNCLEAR — submission leans on a privileged or theoretical action.")
        trace.append("Q2 impact list: not reached — gate already failed below.")
        trace.append("Q3 in scope: assumed in scope, not the deciding factor.")
        trace.append("Q4 privilege: FAIL — requires admin/owner-only access an attacker cannot get.")
        trace.append("Q5 known behaviour: not checked — gate already failed.")
        trace.append("Q6 impact proof: FAIL — no quantified loss shown, only a theoretical risk.")
        trace.append("Q7 known-invalid class: FAIL — matches a known-invalid class (admin power / gas / naming / missing event).")
        return {
            "verdict": "invalid",
            "severity": "informational",
            "confidence": min(95, 80 + 5 * len(kills)),
            "summary": ("Invalid: the finding relies on privileged (admin/owner-only) "
                        "action or a known-invalid class with no attacker path."),
            "evidence": [f"matched kill signal: {k!r}" for k in kills[:4]],
            "questions_failed": ["Q4", "Q6", "Q7"],
            "reasoning_trace": "\n".join(trace),
            "recommended_next_step": ("Close as invalid, citing the failed gate questions "
                                      "(Q4/Q7). Do not file."),
        }
    if is_thin:
        trace.append("Q1 exploit path: FAIL — no concrete steps, calls, or order given.")
        trace.append("Q2 impact list: cannot tell — no impact described.")
        trace.append("Q3 in scope: cannot tell — no contract or component named.")
        trace.append("Q4 privilege: cannot tell — no attacker model given.")
        trace.append("Q5 known behaviour: cannot tell — too little detail to search.")
        trace.append("Q6 impact proof: FAIL — no proof, no numbers, no code.")
        trace.append("Q7 known-invalid class: cannot tell — too little detail.")
        return {
            "verdict": "needs-more-info",
            "severity": "informational",
            "confidence": 45,
            "summary": ("Too thin to judge: no reproduction steps, no code, and no "
                        "stated impact. Ask the reporter for the missing pieces."),
            "evidence": ["description is under 150 characters",
                         "no code attached",
                         "no reproduction steps"],
            "questions_failed": ["Q1", "Q6"],
            "reasoning_trace": "\n".join(trace),
            "recommended_next_step": ("Ask the reporter for exact steps, the vulnerable code, "
                                      "and the concrete impact before any further triage."),
        }

    confidence = 55
    if has_steps:
        confidence += 15
    if has_code:
        confidence += 10
    if impact:
        confidence += 10
    if crit or high:
        confidence += 5
    confidence = max(5, min(98, confidence))

    if crit:
        severity = "critical"
    elif high:
        severity = "high"
    elif med:
        severity = "medium"
    else:
        severity = "low"

    evidence = []
    if has_steps:
        evidence.append("concrete reproduction steps given")
    if has_code:
        evidence.append("vulnerable code attached")
    for w in (impact[:3]):
        evidence.append(f"impact signal: {w!r}")
    if not evidence:
        evidence.append("description states a concrete behaviour")

    trace.append("Q1 exploit path: PASS — concrete steps with calls and order are given.")
    trace.append("Q2 impact list: PASS — impact maps to an accepted impact class.")
    trace.append("Q3 in scope: PASS — root cause named in the submitted component.")
    trace.append("Q4 privilege: PASS — attacker needs no privileged access.")
    trace.append("Q5 known behaviour: PASS — no known/accepted duplicate identified in the submission.")
    trace.append("Q6 impact proof: PASS — impact is concrete and quantified in the steps.")
    trace.append("Q7 known-invalid class: PASS — not a gas / naming / event / admin-only class.")
    verdict = "valid" if confidence >= 80 else "likely-valid"
    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": confidence,
        "summary": (f"{verdict.replace('-', ' ').title()}: the submission shows a concrete "
                    f"attack path with {severity} impact."),
        "evidence": evidence,
        "questions_failed": [],
        "reasoning_trace": "\n".join(trace),
        "recommended_next_step": (
            "Draft the report with a runnable proof of concept and file "
            "after human review." if verdict == "valid" else
            "Reproduce the proof of concept on a fork and confirm the "
            "impact numbers before drafting."),
    }


class MockClient:
    """Deterministic stub client. Same interface as ServClient."""

    MODEL = "mock-stub-v1"

    def complete(self, system_prompt, user_text):
        """Parse the finding back out of the user message and stub a verdict.

        The stub is intentionally honest about being a mock: the pipeline
        labels every result "mock" and the web UI shows a MOCK badge.
        """
        finding = _finding_from_user_text(user_text)
        verdict = _mock_verdict(finding)
        return {
            "content": json.dumps(verdict, indent=2),
            "reasoning": verdict["reasoning_trace"],
            "model": self.MODEL,
            "mode": "mock",
        }


def _finding_from_user_text(user_text):
    """Recover title/description/code from the formatted user message."""
    title, description, code = "", "", ""
    m = re.search(r"Title: (.*)", user_text)
    if m:
        title = m.group(1).strip()
    m = re.search(r"Description:\n(.*?)(?:\n\nCode:|\Z)", user_text, re.S)
    if m:
        description = m.group(1).strip()
    m = re.search(r"Code:\n```\n(.*?)\n```", user_text, re.S)
    if m:
        code = m.group(1).strip()
    return {"title": title, "description": description, "code": code}


def get_client():
    """Return a live ServClient when SERV_API_KEY is set, else the mock."""
    api_key = os.environ.get("SERV_API_KEY", "").strip()
    if api_key:
        return ServClient(api_key)
    return MockClient()
