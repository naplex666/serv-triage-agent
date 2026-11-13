"""CLI: triage a raw bug finding through SERV Reasoning (or the mock).

Usage:
  python -m serv_triage --file samples/valid-walletconnect-chain-scope.json
  python -m serv_triage --sample valid-walletconnect-chain-scope
  python -m serv_triage --title "X" --description "..." --code "..."
  echo '{"title": "...", "description": "..."}' | python -m serv_triage
  python -m serv_triage --file finding.txt --title "Short title"

Input file: JSON with title/description/code keys, or plain text (the
whole file becomes the description). SERV_API_KEY unset -> MOCK mode.
"""

import argparse
import json
import os
import sys

from .serv_client import get_client
from .triage import triage

SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "samples")


def _load_finding_from_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"title": "", "description": raw, "code": ""}
    if not isinstance(data, dict):
        raise ValueError("finding JSON must be an object with title/description/code")
    return {
        "title": str(data.get("title") or ""),
        "description": str(data.get("description") or ""),
        "code": str(data.get("code") or ""),
    }


def _load_sample(name):
    base = name[:-5] if name.endswith(".json") else name
    path = os.path.join(SAMPLES_DIR, base + ".json")
    if not os.path.exists(path):
        available = sorted(f[:-5] for f in os.listdir(SAMPLES_DIR)
                           if f.endswith(".json"))
        raise ValueError(f"no sample named {name!r}; available: {', '.join(available)}")
    return _load_finding_from_file(path)


def _read_stdin():
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {"title": str(data.get("title") or ""),
                    "description": str(data.get("description") or ""),
                    "code": str(data.get("code") or "")}
    except json.JSONDecodeError:
        pass
    return {"title": "", "description": raw, "code": ""}


def build_parser():
    p = argparse.ArgumentParser(
        prog="serv-triage",
        description="Triage a raw bug finding through SERV Reasoning.")
    p.add_argument("--file", help="finding file (JSON or plain text)")
    p.add_argument("--sample", help="bundled sample name, e.g. valid-walletconnect-chain-scope")
    p.add_argument("--title", default="", help="finding title")
    p.add_argument("--description", default="", help="finding description")
    p.add_argument("--code", default="", help="vulnerable code snippet")
    p.add_argument("--out", help="also write the verdict JSON to this file")
    p.add_argument("--model", help="override SERV_MODEL")
    p.add_argument("--effort", help="override SERV_REASONING_EFFORT (low/medium/high)")
    p.add_argument("--quiet", action="store_true",
                   help="print only the verdict JSON, no human summary")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.sample:
            finding = _load_sample(args.sample)
        elif args.file:
            finding = _load_finding_from_file(args.file)
        elif args.title or args.description or args.code:
            finding = {"title": args.title, "description": args.description,
                       "code": args.code}
        elif not sys.stdin.isatty():
            finding = _read_stdin()
            if finding is None:
                build_parser().error("no finding given (use --file, --sample, flags, or stdin)")
        else:
            build_parser().error("no finding given (use --file, --sample, flags, or stdin)")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not (finding.get("title") or finding.get("description")):
        print("error: finding needs at least a title or a description",
              file=sys.stderr)
        return 2

    client = get_client()
    if args.model or args.effort:
        if hasattr(client, "model"):
            if args.model:
                client.model = args.model
            if args.effort:
                client.reasoning_effort = args.effort
    try:
        result = triage(finding, client)
    except Exception as exc:  # noqa: BLE001 - surfaced cleanly, exit 1
        print(f"error: triage failed: {exc}", file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not args.quiet:
        mode = result.get("mode", "?").upper()
        print(f"\n[{mode}] verdict={result['verdict']} severity={result['severity']} "
              f"confidence={result['confidence']} model={result.get('model')}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
