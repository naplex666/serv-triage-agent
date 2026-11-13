"""The 7-question triage gate, as a SERV Reasoning system prompt.

Summarised (in our own words) from the bug-bounty playbook's gate:
the contract-adapted 7-question gate in `bughunter-web3-audit` and the
adversarial-verifier discipline in `bug-bounty-audit-playbook` Step 6B.
The model applies the gate in order and must answer with one JSON object.
"""

SYSTEM_PROMPT = """You are an expert bug-bounty triage analyst. A hunter submits a raw
finding (title, description, code). Your job is to judge whether it is a
real, reportable bug — honestly, not generously. Apply the seven gate
questions IN ORDER. A failed question kills or downgrades the finding
exactly as described. When borderline, round severity DOWN: an honest
low-severity verdict beats an overclaimed invalid one.

Q1 — EXPLOITABLE RIGHT NOW? Can an attacker use this today, step by
step, with concrete calls, arguments and order? If you cannot write down
the exact CALL and RESULT, the finding FAILS Q1.
Q2 — IMPACT ACCEPTED? Is the impact on the target program's accepted
impact list (severity grid / out-of-scope list)? If it maps to a listed
exclusion, it FAILS Q2.
Q3 — IN SCOPE? Is the root cause in an in-scope contract/component at
the audited version? Out of scope, or already fixed there, FAILS Q3.
Q4 — NO PRIVILEGE NEEDED? Does the attack require privileged access an
attacker cannot realistically get? "Admin can do X" is a centralisation
risk, not a bug — FAILS Q4. "Non-admin can do X that only admin should
do" passes.
Q5 — NOT ALREADY KNOWN? Is it already known, fixed, acknowledged or
risk-accepted with unchanged surrounding code? Then it FAILS Q5.
Q6 — IMPACT PROVEN, NOT JUST POSSIBLE? The proof must MOVE value,
FREEZE funds, or BREAK an invariant, with numbers. "Technically
possible", "returns a wrong number", or "reverts" without quantified
loss FAILS Q6 (downgrade severity instead of killing, and say so).
Q7 — NOT A KNOWN-INVALID CLASS? Kill without a chain: gas optimisation
presented as a finding; missing events; admin-can-set-fee-to-100%;
theoretical oracle manipulation with no profitable path (cost > gain);
informational / naming / documentation nits with no impact; a duplicate
of a known issue; "requires admin misconfiguration" with no proof it
triggers by default. Any of these FAILS Q7.

SEVERITY (only for findings that survive the gate):
- critical: direct loss of user funds at scale, or full protocol takeover.
- high: loss of funds / unauthorised privileged action, needs one
  realistic precondition at most.
- medium: funds frozen / denial of service / griefing with real impact.
- low: limited impact, narrow preconditions, or small subset of users.
- informational: real observation with no security impact.
Downgrade one level each for: requires a specific admin configuration;
impact limited to a small subset of users; needs a long time window
(> 24h); the protocol can detect and pause before loss; impact is yield
loss, not principal loss. Theoretical with no practical attack goes to
informational. Attack costs more than the attacker gains means invalid.

VERDICT:
- "valid": survives all seven questions with a concrete attack path.
- "likely-valid": survives, but one question is only weakly evidenced
  (state which in questions_failed or in the summary).
- "needs-more-info": the submission is too thin to judge (no steps, no
  code, no impact) — list exactly what is missing.
- "invalid": fails a gate question — name the failed questions.

CONFIDENCE is 0-100 and reflects the strength of the EVIDENCE, not your
enthusiasm. No proof of concept and no code means confidence below 60.

OUTPUT — return ONLY this JSON object, no prose before or after it:
{
  "verdict": "valid | likely-valid | needs-more-info | invalid",
  "severity": "critical | high | medium | low | informational",
  "confidence": 0-100,
  "summary": "one or two sentences: what the bug is and why it got this verdict",
  "evidence": ["short quotes or facts from the submission that support the verdict"],
  "questions_failed": ["Q1", ...] (empty list when nothing failed),
  "reasoning_trace": "your per-question reasoning, Q1 to Q7, one short line each",
  "recommended_next_step": "the single most useful next action"
}
"""

VERDICTS = ("valid", "likely-valid", "needs-more-info", "invalid")
SEVERITIES = ("critical", "high", "medium", "low", "informational")
REQUIRED_FIELDS = (
    "verdict",
    "severity",
    "confidence",
    "summary",
    "evidence",
    "questions_failed",
    "reasoning_trace",
    "recommended_next_step",
)

# Models do not always obey the exact field names in the system prompt.
# Accept the common aliases a model actually returns (observed live:
# supportingEvidence / failedQuestions / perQuestionReasoning / nextAction,
# confidence as a 0-1 float) and normalise them to the canonical schema.
_FIELD_ALIASES = {
    "verdict": ("verdict",),
    "severity": ("severity",),
    "confidence": ("confidence",),
    "summary": ("summary",),
    "evidence": ("evidence", "supportingEvidence", "supporting_evidence"),
    "questions_failed": ("questions_failed", "failedQuestions",
                         "failed_questions", "failed_gates"),
    "reasoning_trace": ("reasoning_trace", "perQuestionReasoning",
                        "per_question_reasoning", "reasoning", "trace"),
    "recommended_next_step": ("recommended_next_step", "nextAction",
                              "next_action", "recommendedNextStep", "next_step"),
}


def _pick(data, canonical):
    for key in _FIELD_ALIASES[canonical]:
        if key in data:
            return data[key]
    return None


def _format_trace(value):
    """Normalise a reasoning trace (str, list, or per-question dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        lines = []
        for key in sorted(value, key=lambda k: str(k)):
            lines.append(f"{key}: {value[key]}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value)


def _normalise_confidence(value):
    """Accept 0-100 ints and 0-1 floats (models return both)."""
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"confidence must be a number 0-100, got {value!r}") from exc
    if 0 <= num <= 1 and isinstance(value, float):
        num = num * 100
    if not 0 <= num <= 100:
        raise ValueError(f"confidence out of range 0-100: {value!r}")
    return int(round(num))


def build_user_message(finding):
    """Format a raw finding (dict with title/description/code) for the model."""
    title = (finding.get("title") or "").strip()
    description = (finding.get("description") or "").strip()
    code = (finding.get("code") or "").strip()
    parts = ["Triage this finding through the 7-question gate."]
    parts.append(f"Title: {title}" if title else "Title: (none given)")
    parts.append(f"Description:\n{description}" if description else "Description: (none given)")
    if code:
        parts.append(f"Code:\n```\n{code}\n```")
    else:
        parts.append("Code: (none given)")
    return "\n\n".join(parts)


def extract_json(text):
    """Extract the first JSON object from model output.

    Handles plain JSON, ```json fenced blocks, and prose around the object.
    Raises ValueError when no parseable object is found.
    """
    if not text or not text.strip():
        raise ValueError("empty model output, no verdict JSON found")
    cleaned = text.strip()
    for fence in ("```json", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence):].lstrip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].rstrip()
            break
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    try:
        return __import__("json").loads(cleaned[start:end + 1])
    except Exception as exc:  # noqa: BLE001 - re-raised with context
        raise ValueError(f"verdict JSON is not parseable: {exc}") from exc


def validate_verdict(data):
    """Validate a parsed verdict dict against the output schema.

    Normalises common model field aliases and 0-1 confidence floats,
    coerces confidence to int, and returns a normalised dict.
    Raises ValueError on any schema violation.
    """
    if not isinstance(data, dict):
        raise ValueError("verdict must be a JSON object")
    normalised = {}
    for field in REQUIRED_FIELDS:
        value = _pick(data, field)
        if value is None:
            raise ValueError(f"verdict is missing field: {field}")
        normalised[field] = value
    verdict = str(normalised["verdict"]).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict value: {data['verdict']!r}")
    severity = str(normalised["severity"]).strip().lower()
    if severity not in SEVERITIES:
        raise ValueError(f"invalid severity value: {data['severity']!r}")
    confidence = _normalise_confidence(normalised["confidence"])
    evidence = normalised["evidence"]
    questions_failed = normalised["questions_failed"]
    if isinstance(evidence, str):
        evidence = [evidence]
    if isinstance(questions_failed, str):
        questions_failed = [questions_failed]
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        raise ValueError("evidence must be a list of strings")
    if not isinstance(questions_failed, list) or not all(
        isinstance(q, str) for q in questions_failed
    ):
        raise ValueError("questions_failed must be a list of strings")
    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": confidence,
        "summary": str(normalised["summary"]),
        "evidence": list(evidence),
        "questions_failed": list(questions_failed),
        "reasoning_trace": _format_trace(normalised["reasoning_trace"]),
        "recommended_next_step": str(normalised["recommended_next_step"]),
    }


def parse_verdict(text):
    """Parse + validate raw model output into a normalised verdict dict."""
    return validate_verdict(extract_json(text))
