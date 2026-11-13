"""End-to-end tests for the mock pipeline (no API key, no network).

Run:  python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serv_triage import gate
from serv_triage.serv_client import MockClient
from serv_triage.triage import triage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "samples")


def load_sample(name):
    with open(os.path.join(SAMPLES_DIR, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


class TestMockPipeline(unittest.TestCase):
    def setUp(self):
        self.client = MockClient()

    def test_valid_sample(self):
        s = load_sample("valid-walletconnect-chain-scope")
        result = triage(s, self.client)
        self.assertEqual(result["verdict"], s["expected"]["verdict"])
        self.assertEqual(result["severity"], s["expected"]["severity"])
        self.assertEqual(result["mode"], "mock")
        self.assertGreaterEqual(result["confidence"], 80)
        self.assertEqual(result["questions_failed"], [])

    def test_invalid_sample(self):
        s = load_sample("invalid-false-positive")
        result = triage(s, self.client)
        self.assertEqual(result["verdict"], s["expected"]["verdict"])
        self.assertEqual(result["severity"], s["expected"]["severity"])
        self.assertEqual(result["mode"], "mock")
        self.assertIn("Q4", result["questions_failed"])
        self.assertIn("Q7", result["questions_failed"])

    def test_needs_more_info_sample(self):
        s = load_sample("needs-more-info")
        result = triage(s, self.client)
        self.assertEqual(result["verdict"], s["expected"]["verdict"])
        self.assertEqual(result["severity"], s["expected"]["severity"])
        self.assertEqual(result["mode"], "mock")
        self.assertIn("Q1", result["questions_failed"])

    def test_mock_is_deterministic(self):
        s = load_sample("valid-walletconnect-chain-scope")
        first = triage(s, self.client)
        second = triage(s, self.client)
        self.assertEqual(first, second)

    def test_reasoning_trace_present(self):
        s = load_sample("valid-walletconnect-chain-scope")
        result = triage(s, self.client)
        for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"):
            self.assertIn(q, result["reasoning_trace"])

    def test_all_samples_validate_against_schema(self):
        for name in ("valid-walletconnect-chain-scope",
                     "invalid-false-positive", "needs-more-info"):
            s = load_sample(name)
            result = triage(s, self.client)
            # re-validate through the same gate the live path uses
            gate.validate_verdict(result)


class TestGateParser(unittest.TestCase):
    def test_plain_json(self):
        verdict = gate.parse_verdict(json.dumps({
            "verdict": "valid", "severity": "high", "confidence": 88,
            "summary": "x", "evidence": ["e"], "questions_failed": [],
            "reasoning_trace": "Q1 pass", "recommended_next_step": "file it",
        }))
        self.assertEqual(verdict["verdict"], "valid")

    def test_fenced_json_block(self):
        raw = ("Here is the verdict:\n```json\n"
               '{"verdict": "invalid", "severity": "informational", '
               '"confidence": 90, "summary": "x", "evidence": [], '
               '"questions_failed": ["Q4"], "reasoning_trace": "t", '
               '"recommended_next_step": "close it"}\n```')
        self.assertEqual(gate.parse_verdict(raw)["verdict"], "invalid")

    def test_rejects_bad_verdict_value(self):
        with self.assertRaises(ValueError):
            gate.parse_verdict(json.dumps({
                "verdict": "maybe", "severity": "low", "confidence": 50,
                "summary": "x", "evidence": [], "questions_failed": [],
                "reasoning_trace": "t", "recommended_next_step": "n",
            }))

    def test_rejects_missing_field(self):
        with self.assertRaises(ValueError):
            gate.parse_verdict(json.dumps({"verdict": "valid"}))

    def test_rejects_unparseable_output(self):
        with self.assertRaises(ValueError):
            gate.parse_verdict("no json here at all")

    def test_live_model_shape_aliases(self):
        # Exact shape returned live by gpt-5.4-nano on 13 Nov 2026:
        # alias field names + confidence as a 0-1 float.
        raw = json.dumps({
            "verdict": "Invalid", "severity": "informational", "confidence": 0.45,
            "summary": "missing exact attack path",
            "supportingEvidence": ["code comment shows no chain check"],
            "failedQuestions": ["Q1"],
            "perQuestionReasoning": {"Q1": "Failed. No exact calls given.",
                                     "Q2": "Not evaluated (gated out by Q1)."},
            "nextAction": "Provide an executable PoC.",
        })
        verdict = gate.parse_verdict(raw)
        self.assertEqual(verdict["verdict"], "invalid")
        self.assertEqual(verdict["confidence"], 45)
        self.assertEqual(verdict["questions_failed"], ["Q1"])
        self.assertEqual(verdict["evidence"],
                         ["code comment shows no chain check"])
        self.assertIn("Q1: Failed.", verdict["reasoning_trace"])
        self.assertEqual(verdict["recommended_next_step"],
                         "Provide an executable PoC.")

    def test_system_prompt_covers_all_seven_questions(self):
        for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"):
            self.assertIn(q, gate.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
