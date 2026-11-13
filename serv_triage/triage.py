"""Pipeline: raw finding -> SERV Reasoning -> structured verdict.

One function, `triage`, drives the whole flow so the CLI, the web UI
and the tests all exercise the exact same path:
  finding dict -> system prompt + user message -> client.complete()
  -> parse + validate the verdict JSON -> result dict with mode/model
  and the reasoning trace as an auditable trail.
"""

from . import gate
from .serv_client import get_client


def triage(finding, client=None):
    """Triage one finding. Returns a result dict (never raises for a bad
    model reply — a parse failure is reported as needs-more-info with the
    raw output kept in the trace, so the pipeline never crashes a demo).
    """
    client = client or get_client()
    user_text = gate.build_user_message(finding)
    reply = client.complete(gate.SYSTEM_PROMPT, user_text)
    try:
        verdict = gate.parse_verdict(reply["content"])
    except ValueError as exc:
        return {
            "verdict": "needs-more-info",
            "severity": "informational",
            "confidence": 20,
            "summary": f"Could not parse a verdict from the model reply: {exc}",
            "evidence": [],
            "questions_failed": ["Q1"],
            "reasoning_trace": (
                "Model reply could not be parsed as verdict JSON.\n"
                f"Raw reply (first 500 chars):\n{reply['content'][:500]}"
            ),
            "recommended_next_step": "Re-run triage; if the model keeps "
                                     "returning unparseable output, lower "
                                     "the temperature or tighten the prompt.",
            "mode": reply.get("mode", "unknown"),
            "model": reply.get("model", "unknown"),
            "finding_title": (finding.get("title") or "").strip(),
        }
    # Attach the API's own reasoning trace when it came back separately
    # (live mode); the model's JSON trace is the fallback.
    api_reasoning = (reply.get("reasoning") or "").strip()
    if api_reasoning and api_reasoning != verdict["reasoning_trace"]:
        verdict["reasoning_trace"] = (
            verdict["reasoning_trace"]
            + "\n---\nAPI reasoning trace:\n" + api_reasoning
        )
    verdict["mode"] = reply.get("mode", "unknown")
    verdict["model"] = reply.get("model", "unknown")
    verdict["finding_title"] = (finding.get("title") or "").strip()
    return verdict
