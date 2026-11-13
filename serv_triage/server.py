"""Web UI: one HTML page + a tiny JSON API, stdlib http.server only.

  python -m serv_triage.server [--port 8000] [--host 127.0.0.1]

Routes:
  GET  /                  the form page
  GET  /api/samples       bundled sample list
  GET  /api/sample/<name> one bundled sample as JSON
  POST /api/triage        {"title","description","code"} -> verdict JSON

No build step, no external assets, no JavaScript framework.
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .serv_client import get_client
from .triage import triage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(ROOT, "samples")

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SERV Triage Agent — bug-bounty finding triage</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 860px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.5; }
  h1 { font-size: 1.6rem; margin-bottom: .2rem; }
  .sub { color: #555; margin-top: 0; }
  label { display: block; font-weight: 600; margin: 1rem 0 .3rem; }
  input[type=text], textarea { width: 100%; box-sizing: border-box; padding: .6rem;
    border: 1px solid #bbb; border-radius: 6px; font: inherit; }
  textarea { min-height: 110px; font-family: ui-monospace, monospace; font-size: .9rem; }
  button { margin-top: 1rem; padding: .6rem 1.2rem; font: inherit; font-weight: 600;
    border: 0; border-radius: 6px; background: #111; color: #fff; cursor: pointer; }
  button.secondary { background: #eee; color: #111; margin-left: .5rem; }
  button:disabled { opacity: .5; cursor: wait; }
  #result { display: none; margin-top: 2rem; border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.2rem; }
  .badge { display: inline-block; padding: .15rem .6rem; border-radius: 999px;
    font-size: .85rem; font-weight: 700; color: #fff; }
  .badge.mock { background: #b45309; } .badge.live { background: #15803d; }
  .v-valid { background: #15803d; } .v-likely-valid { background: #65a30d; }
  .v-needs-more-info { background: #b45309; } .v-invalid { background: #b91c1c; }
  .sev-critical { background: #7f1d1d; } .sev-high { background: #b91c1c; }
  .sev-medium { background: #b45309; } .sev-low { background: #0369a1; }
  .sev-informational { background: #64748b; }
  .confbar { height: 10px; background: #eee; border-radius: 5px; overflow: hidden; }
  .confbar > div { height: 100%; background: #111; }
  pre.trace { background: #f6f6f6; padding: .8rem; border-radius: 6px;
    white-space: pre-wrap; font-size: .88rem; }
  .err { color: #b91c1c; font-weight: 600; }
  .samples { margin-top: .5rem; font-size: .9rem; color: #555; }
  .samples button { padding: .3rem .7rem; margin: .2rem .2rem 0 0; font-size: .85rem; }
</style>
</head>
<body>
<h1>SERV Triage Agent</h1>
<p class="sub">Paste a raw bug-bounty finding. SERV Reasoning runs it through the
7-question triage gate and returns a structured verdict with an auditable
reasoning trail. No API key? It runs in <b>MOCK</b> mode with a deterministic
stub — same pipeline, clearly labelled.</p>

<form id="form">
  <label for="title">Title</label>
  <input type="text" id="title" placeholder="e.g. WalletConnect session processes out-of-scope chains">
  <label for="description">Description (steps, impact, what the attacker does)</label>
  <textarea id="description" placeholder="Step 1… Step 2… Impact: …"></textarea>
  <label for="code">Code (optional)</label>
  <textarea id="code" placeholder="paste the vulnerable snippet"></textarea>
  <button type="submit" id="go">Triage finding</button>
  <button type="button" class="secondary" id="clear">Clear</button>
</form>

<p class="samples">Try a bundled sample:
  <span id="sampleButtons">loading…</span></p>

<div id="result"></div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function loadSamples() {
  const res = await fetch("/api/samples");
  const names = await res.json();
  $("sampleButtons").innerHTML = "";
  names.forEach(n => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = n; b.className = "secondary";
    b.onclick = async () => {
      const r = await fetch("/api/sample/" + encodeURIComponent(n));
      const s = await r.json();
      $("title").value = s.title || "";
      $("description").value = s.description || "";
      $("code").value = s.code || "";
    };
    $("sampleButtons").appendChild(b);
  });
}

$("form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const btn = $("go"); btn.disabled = true; btn.textContent = "Triaging…";
  const box = $("result"); box.style.display = "block";
  box.innerHTML = "<p>Running the 7-question gate through SERV Reasoning…</p>";
  try {
    const res = await fetch("/api/triage", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: $("title").value,
        description: $("description").value, code: $("code").value }) });
    const r = await res.json();
    if (!res.ok) throw new Error(r.error || ("HTTP " + res.status));
    const mode = (r.mode || "?").toUpperCase();
    box.innerHTML =
      "<p><span class='badge " + esc(r.mode) + "'>" + mode + " MODE</span> " +
      "<span class='badge v-" + esc(r.verdict) + "'>" + esc(r.verdict.toUpperCase()) + "</span> " +
      "<span class='badge sev-" + esc(r.severity) + "'>" + esc(r.severity.toUpperCase()) + "</span> " +
      "<span>model: " + esc(r.model || "?") + "</span></p>" +
      "<p><b>Confidence: " + esc(r.confidence) + "/100</b></p>" +
      "<div class='confbar'><div style='width:" + esc(r.confidence) + "%'></div></div>" +
      "<p>" + esc(r.summary) + "</p>" +
      "<h3>Evidence</h3><ul>" +
      (r.evidence || []).map(e => "<li>" + esc(e) + "</li>").join("") + "</ul>" +
      "<h3>Gate questions failed</h3><p>" +
      ((r.questions_failed || []).length ? esc(r.questions_failed.join(", ")) : "none — all seven passed") + "</p>" +
      "<h3>Reasoning trace (auditable)</h3><pre class='trace'>" + esc(r.reasoning_trace) + "</pre>" +
      "<h3>Recommended next step</h3><p>" + esc(r.recommended_next_step) + "</p>";
  } catch (e) {
    box.innerHTML = "<p class='err'>Triage failed: " + esc(e.message) + "</p>";
  }
  btn.disabled = false; btn.textContent = "Triage finding";
});

$("clear").onclick = () => {
  $("title").value = ""; $("description").value = ""; $("code").value = "";
  $("result").style.display = "none";
};

loadSamples();
</script>
</body>
</html>
"""


def _sample_names():
    if not os.path.isdir(SAMPLES_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))


def _read_sample(name):
    safe = os.path.basename(name)
    path = os.path.join(SAMPLES_DIR, safe + ".json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep stdout clean
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server naming
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/samples":
            self._send_json(_sample_names())
        elif parsed.path.startswith("/api/sample/"):
            name = parsed.path[len("/api/sample/"):]
            try:
                self._send_json(_read_sample(name))
            except (OSError, ValueError):
                self._send_json({"error": f"no sample named {name!r}"}, status=404)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802 - http.server naming
        parsed = urlparse(self.path)
        if parsed.path != "/api/triage":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json({"error": "request body must be JSON"}, status=400)
            return
        finding = {
            "title": str(data.get("title") or ""),
            "description": str(data.get("description") or ""),
            "code": str(data.get("code") or ""),
        }
        if not (finding["title"] or finding["description"]):
            self._send_json(
                {"error": "finding needs at least a title or a description"},
                status=400)
            return
        try:
            result = triage(finding, get_client())
        except Exception as exc:  # noqa: BLE001 - surfaced as JSON error
            self._send_json({"error": f"triage failed: {exc}"}, status=502)
            return
        self._send_json(result)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="serv-triage-server",
        description="Serve the SERV Triage Agent web UI.")
    parser.add_argument("--host", default=os.environ.get("SERV_TRIAGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    mode = "MOCK (no SERV_API_KEY set)" if not os.environ.get("SERV_API_KEY") else "LIVE"
    print(f"SERV Triage Agent ({mode}) at http://{args.host}:{args.port}/",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
